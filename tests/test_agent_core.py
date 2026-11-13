from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.agent_core as agent_core_module
from app.agent_core import AgentCoreRepository
from app.main import create_app
from app.search import SearchResult


def test_agent_core_initializes_default_project_idempotently(tmp_path: Path) -> None:
    repository = AgentCoreRepository(tmp_path)
    second = AgentCoreRepository(tmp_path)

    assert [project.id for project in repository.projects()] == [
        "project-personal-agent-team"
    ]
    assert len(second.projects()) == 1
    with sqlite3.connect(tmp_path / "workspace.db") as connection:
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE subsystem='agent_core'"
        ).fetchone()[0]
    assert version == 3


def test_action_link_migration_preserves_existing_tasks_and_rolls_back(tmp_path, monkeypatch):
    migrate = agent_core_module.apply_migrations

    def old_schema(*args, **kwargs):
        kwargs["migrations"].pop(2)
        kwargs["migrations"].pop(3)
        return migrate(*args, **kwargs)

    def broken_upgrade(*args, **kwargs):
        kwargs["migrations"][2] += "\nINSERT INTO missing_table VALUES(1);"
        return migrate(*args, **kwargs)

    monkeypatch.setattr(agent_core_module, "apply_migrations", old_schema)
    old = AgentCoreRepository(tmp_path)
    task = old.create_task(title="既有任务", objective="保留旧任务", task_type="research",
                           project_id=agent_core_module.DEFAULT_PROJECT_ID)
    monkeypatch.setattr(agent_core_module, "apply_migrations", broken_upgrade)
    with pytest.raises(sqlite3.OperationalError):
        AgentCoreRepository(tmp_path)
    with old.connect() as connection:
        assert connection.execute("SELECT version FROM schema_migrations WHERE subsystem='agent_core'").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='focus_action_tasks'").fetchone() is None
    monkeypatch.setattr(agent_core_module, "apply_migrations", migrate)
    assert AgentCoreRepository(tmp_path).task(task.id) == task


def test_local_task_run_creates_private_review_artifact(tmp_path: Path) -> None:
    repository = AgentCoreRepository(tmp_path)
    task = repository.create_task(
        title="理解 Agent Harness",
        objective="基于现有资料整理 Agent Harness 的边界、状态和失败恢复。",
        task_type="learning",
        project_id="project-personal-agent-team",
        priority=1,
    )
    run = repository.plan_task(task.id)
    assert repository.plan_task(task.id).id == run.id

    artifact = repository.execute_run(
        run.id,
        (
            SearchResult(
                "card-1",
                "knowledge-card",
                "Harness 是运行时边界",
                "包含状态、工具和失败恢复。",
                "/knowledge/cards/card-1",
                "知识卡",
            ),
        ),
    )

    assert repository.run(run.id).status == "reviewing"  # type: ignore[union-attr]
    assert repository.task(task.id).status == "reviewing"  # type: ignore[union-attr]
    assert [step.status for step in repository.steps(run.id)] == [
        "completed",
        "completed",
        "completed",
    ]
    assert repository.tool_calls(run.id)[0].input_summary.startswith("本地关键词")
    assert task.objective not in repository.tool_calls(run.id)[0].input_summary
    assert "未调用模型" in repository.artifact_content(artifact.id)
    artifact_path = tmp_path / "working" / "agent-artifacts" / artifact.storage_key
    assert artifact_path.stat().st_mode & 0o777 == 0o600

    repository.approve_run(run.id)
    assert repository.run(run.id).status == "completed"  # type: ignore[union-attr]
    assert repository.task(task.id).status == "completed"  # type: ignore[union-attr]
    assert repository.artifact(artifact.id).status == "accepted"  # type: ignore[union-attr]


def test_agent_run_can_be_cancelled_without_deleting_history(tmp_path: Path) -> None:
    repository = AgentCoreRepository(tmp_path)
    task = repository.create_task(
        title="测试取消",
        objective="验证计划可以安全取消。",
        task_type="research",
        project_id="project-personal-agent-team",
    )
    run = repository.plan_task(task.id)

    repository.cancel_run(run.id)

    assert repository.run(run.id).status == "cancelled"  # type: ignore[union-attr]
    assert repository.task(task.id).status == "cancelled"  # type: ignore[union-attr]
    assert all(step.status == "cancelled" for step in repository.steps(run.id))
    retry = repository.plan_task(task.id)
    assert retry.id != run.id and repository.plan_task(task.id).id == retry.id
    assert repository.run(run.id).status == "cancelled"


def test_agent_core_rejects_invalid_task_and_transition(tmp_path: Path) -> None:
    repository = AgentCoreRepository(tmp_path)
    with pytest.raises(ValueError, match="任务类型无效"):
        repository.create_task(
            title="错误任务",
            objective="不允许未知角色。",
            task_type="chief",
            project_id="project-personal-agent-team",
        )
    task = repository.create_task(
        title="合法任务",
        objective="验证状态机。",
        task_type="build",
        project_id="project-personal-agent-team",
    )
    run = repository.plan_task(task.id)
    with pytest.raises(ValueError, match="待确认"):
        repository.approve_run(run.id)


def test_failed_review_keeps_history_and_can_start_a_new_run(tmp_path, monkeypatch):
    repository = AgentCoreRepository(tmp_path)
    task = repository.create_task(title="验收失败样例", objective="检查本地工作纸", task_type="research",
                                  project_id=agent_core_module.DEFAULT_PROJECT_ID)
    run = repository.plan_task(task.id)
    monkeypatch.setattr(repository, "_artifact_markdown", lambda *args: "无效工作纸")
    with pytest.raises(RuntimeError, match="Reviewer 未通过"):
        repository.execute_run(run.id, ())
    assert repository.run(run.id).status == "failed"
    assert repository.steps(run.id)[-1].status == "failed"
    assert repository.artifacts(run_id=run.id)[0].status == "rejected"
    retry = repository.plan_task(task.id)
    repository.cancel_run(run.id)
    assert repository.task(task.id).status == retry.status == "planned"


def test_agent_core_pages_complete_local_flow(tmp_path: Path) -> None:
    with TestClient(create_app(content_root=tmp_path, enable_scheduler=False)) as client:
        response = client.get("/tasks")
        assert response.status_code == 200
        assert "AI 工作" in response.text
        assert "运行前预览输入" in response.text

        created = client.post(
            "/tasks",
            data={
                "title": "本地学习任务",
                "objective": "整理可靠 Agent 的最小组成。",
                "task_type": "learning",
                "project_id": "project-personal-agent-team",
                "priority": "2",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        task_path = created.headers["location"]
        task_page = client.get(task_path)
        assert task_page.status_code == 200
        assert "生成执行计划" in task_page.text

        planned = client.post(f"{task_path}/plan", follow_redirects=False)
        assert planned.status_code == 303
        run_path = planned.headers["location"]
        assert client.get(run_path).status_code == 200

        executed = client.post(f"{run_path}/execute", follow_redirects=False)
        assert executed.status_code == 303
        review_page = client.get(run_path)
        assert "等待人工确认" in review_page.text
        assert "workspace.search" in review_page.text
        assert "待验收" in client.get("/").text

        approved = client.post(f"{run_path}/approve", follow_redirects=False)
        assert approved.status_code == 303
        assert "已完成" in client.get(run_path).text
        assert "待验收" not in client.get("/").text


def test_agent_core_unknown_resources_are_404(tmp_path: Path) -> None:
    with TestClient(create_app(content_root=tmp_path, enable_scheduler=False)) as client:
        assert client.get("/tasks/missing").status_code == 404
        assert client.get("/runs/missing").status_code == 404
        assert client.get("/artifacts/missing").status_code == 404
