from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.assistant import (
    AssistantContextBuilder,
    AssistantEvidence,
    AssistantRecommendation,
    AssistantRepository,
    AssistantSuggestion,
    validate_assistant_result,
)
from app.content import load_items
from app.main import create_app
from app.workspace import create_item, items_directory


def _result(source_id: str, *, skill_id: str = "") -> dict:
    actions = [
        {
            "type": "create-thought",
            "title": "记录当前选择",
            "body": "写下选择、约束和完成后的反馈。",
            "skill_id": "",
            "priority": 3,
        }
    ]
    if skill_id:
        actions.append(
            {
                "type": "create-learning-task",
                "title": "完成一个最小可靠性练习",
                "body": "为当前薄弱技能补一组可复现测试。",
                "skill_id": skill_id,
                "priority": 4,
            }
        )
    return {
        "user_intent_summary": "判断当前最先推进的事项",
        "assistant_summary": "先完成一个可验证的小闭环。",
        "priority_title": "完成最小可验证闭环",
        "reason": "它同时减少技能差距并产生项目证据。",
        "steps": ["明确验收条件", "完成最小实现", "运行测试并记录结果"],
        "success_criteria": "产生一个通过测试、可复盘的提交。",
        "evidence": [{"source_id": source_id, "reason": "这是当前活跃来源"}],
        "assumptions": ["本周可安排连续时间"],
        "clarifying_question": "",
        "suggested_actions": actions,
    }


class FakeAssistantGateway:
    enabled = True
    provider = SimpleNamespace(value="local")
    config = SimpleNamespace(base_url="http://127.0.0.1:11434/v1", model="fake")

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def assistant_candidate(self, _material: str) -> dict:
        self.calls += 1
        return self.payload


@pytest.fixture
def assistant_client(tmp_path: Path) -> TestClient:
    application = create_app(content_root=tmp_path, enable_scheduler=False)
    return TestClient(application)


def test_assistant_context_is_high_signal_and_excludes_private_fields(
    assistant_client: TestClient,
) -> None:
    application = assistant_client.app
    career = application.state.career
    career.save_profile(
        target_roles="Agent 应用开发",
        contact="private-contact@example.test",
        education="私密教育全文",
        experience="私密简历全文",
        facts="私密档案事实",
    )
    skill = career.add_skill(name="LangGraph", current_level=1, target_level=4)
    job = career.add_job(
        company="虚构公司",
        title="Agent 工程师",
        jd_text="PRIVATE_JD_FULL_TEXT 需要 LangGraph",
    )
    career.set_job_skill_gap(
        job_id=job.id,
        skill_id=skill.id,
        importance=5,
        gap_note="缺少可靠性评测证据",
    )
    task = career.add_learning_task(
        skill_id=skill.id,
        title="补齐 LangGraph 恢复测试",
        status="active",
        priority=5,
    )
    thought = create_item(
        application.state.content_root,
        title="先把可靠性闭环跑通 13812345678",
        body="目前最缺的是可以展示的恢复测试。联系 13812345678，路径 /Users/demo/private.txt。",
    )

    snapshot = AssistantContextBuilder(
        application.state.content_root,
        career,
        application.state.search,
        application.state.video,
    ).build("我现在应该先做什么")

    assert "Agent 应用开发" in snapshot.material
    assert "缺少可靠性评测证据" in snapshot.material
    assert "agent-path-minimal-agent" in snapshot.material
    assert task.id not in snapshot.material
    assert thought.id in snapshot.material
    assert "private-contact@example.test" not in snapshot.material
    assert "私密教育全文" not in snapshot.material
    assert "私密简历全文" not in snapshot.material
    assert "私密档案事实" not in snapshot.material
    assert "PRIVATE_JD_FULL_TEXT" not in snapshot.material
    assert "13812345678" not in snapshot.material
    assert "/Users/demo/private.txt" not in snapshot.material
    assert str(application.state.data_root) not in snapshot.material


def test_assistant_income_context_contains_only_money_engine_summary(
    assistant_client: TestClient,
) -> None:
    application = assistant_client.app
    income = application.state.income
    product = income.active_product()
    income.update_role(
        product.id,
        "product",
        status="active",
        observable_result="不应进入助手的内部观察结果",
        next_action="完成模板包",
        requires_confirmation=True,
    )
    entry = income.add_entry(
        source_key="digital_product",
        entry_type="revenue",
        gross_fen=990,
        note="PRIVATE_BUYER_AND_PAYMENT_NOTE",
    )
    income.add_metric_snapshot(
        product.id,
        observed_at="2026-08-25",
        impressions=10,
        store_clicks=2,
        paid_orders=1,
        delivered_orders=1,
        refunds=0,
    )

    snapshot = AssistantContextBuilder(
        application.state.content_root,
        application.state.career,
        application.state.search,
        application.state.video,
        income,
    ).build("收入下一步是什么")

    assert product.name in snapshot.material
    assert "opportunity-agent-reliability-launch-kit" in snapshot.material
    assert '"profile_tier": "T2"' in snapshot.material
    assert '"verification_ready": false' in snapshot.material
    assert "完成模板包" in snapshot.material
    assert '"paid_orders": 1' in snapshot.material
    assert entry.id not in snapshot.material
    assert "PRIVATE_BUYER_AND_PAYMENT_NOTE" not in snapshot.material
    assert "不应进入助手的内部观察结果" not in snapshot.material


def test_assistant_result_rejects_forged_sources_skills_and_bad_shape() -> None:
    valid = _result("source-1", skill_id="skill-1")
    recommendation = validate_assistant_result(
        valid,
        allowed_source_ids={"source-1"},
        allowed_skill_ids={"skill-1"},
    )
    assert recommendation.priority_title == "完成最小可验证闭环"
    assert len(recommendation.steps) == 3

    forged_source = json.loads(json.dumps(valid))
    forged_source["evidence"][0]["source_id"] = "invented"
    with pytest.raises(ValueError, match="本轮上下文之外"):
        validate_assistant_result(
            forged_source,
            allowed_source_ids={"source-1"},
            allowed_skill_ids={"skill-1"},
        )

    forged_skill = json.loads(json.dumps(valid))
    forged_skill["suggested_actions"][1]["skill_id"] = "invented"
    with pytest.raises(ValueError, match="不存在的技能"):
        validate_assistant_result(
            forged_skill,
            allowed_source_ids={"source-1"},
            allowed_skill_ids={"skill-1"},
        )

    missing_step = json.loads(json.dumps(valid))
    missing_step["steps"] = ["只有一步"]
    with pytest.raises(ValueError, match="三个步骤"):
        validate_assistant_result(
            missing_step,
            allowed_source_ids={"source-1"},
            allowed_skill_ids={"skill-1"},
        )

    missing_evidence = json.loads(json.dumps(valid))
    missing_evidence["evidence"] = []
    with pytest.raises(ValueError, match="至少一个"):
        validate_assistant_result(
            missing_evidence,
            allowed_source_ids={"source-1"},
            allowed_skill_ids={"skill-1"},
        )


def test_assistant_repository_stores_summaries_not_raw_prompt(tmp_path: Path) -> None:
    repository = AssistantRepository(tmp_path)
    recommendation = AssistantRecommendation(
        user_intent_summary="判断优先事项",
        assistant_summary="先完成最小闭环",
        priority_title="可靠性闭环",
        reason="会形成证据",
        steps=("定义", "实现", "验证"),
        success_criteria="测试通过",
        evidence=(AssistantEvidence("source-1", "当前来源", "来源", "/ideas/1"),),
        assumptions=("有两小时",),
        clarifying_question="",
        suggestions=(
            AssistantSuggestion(
                "action-1", "create-thought", "复盘", "记录结果", "", 3
            ),
        ),
    )
    conversation, turn = repository.save_turn(recommendation)
    first = repository.reserve_decision(turn.id, turn.suggestions[0])
    second = repository.reserve_decision(turn.id, turn.suggestions[0])

    assert first.id == second.id
    assert repository.conversation(conversation.id).summary == "先完成最小闭环"
    with sqlite3.connect(repository.database_path) as connection:
        serialized = " ".join(
            str(value)
            for table in (
                "assistant_conversations",
                "assistant_turn_summaries",
                "assistant_decisions",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert "RAW_PRIVATE_QUESTION" not in serialized
    assert "完整外发正文" not in serialized


def test_assistant_preview_does_not_call_model_and_confirmed_actions_are_idempotent(
    assistant_client: TestClient,
) -> None:
    application = assistant_client.app
    skill = application.state.career.add_skill(name="Agent 评测")
    source = create_item(
        application.state.content_root,
        title="当前应该完善评测",
        body="先让项目产生可信证据。",
    )
    snapshot = AssistantContextBuilder(
        application.state.content_root,
        application.state.career,
        application.state.search,
        application.state.video,
    ).build("RAW_PRIVATE_QUESTION 我现在先做什么")
    gateway = FakeAssistantGateway(_result(source.id, skill_id=skill.id))
    application.state.model_gateway = gateway

    preview = assistant_client.post(
        "/assistant/preview", data={"question": "现在先做什么"}
    )
    assert preview.status_code == 200
    assert "先看清楚，再发送" in preview.text
    assert gateway.calls == 0

    outbound = json.loads(snapshot.material)
    source_row = next(row for row in outbound["allowed_sources"] if row["id"] == source.id)
    source_row["title"] = "伪造来源"
    source_row["url"] = "javascript:alert(1)"
    answer = assistant_client.post(
        "/assistant/ask",
        data={"outbound_text": json.dumps(outbound, ensure_ascii=False)},
    )
    assert answer.status_code == 200
    assert "完成最小可验证闭环" in answer.text
    assert "伪造来源" not in answer.text
    assert "javascript:alert" not in answer.text
    assert "当前应该完善评测" in answer.text
    assert gateway.calls == 1
    with sqlite3.connect(application.state.data_root / "workspace.db") as connection:
        saved_text = " ".join(
            str(value)
            for table in ("assistant_conversations", "assistant_turn_summaries")
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert "RAW_PRIVATE_QUESTION" not in saved_text
    conversation = application.state.assistant.conversations()[0]
    turn = application.state.assistant.turns(conversation.id)[0]

    before = len(load_items(items_directory(application.state.content_root)).items)
    data = {
        "decision": "confirm",
        "title": "记录这个选择",
        "body": "记录约束与结果。",
        "priority": 3,
    }
    path = f"/assistant/turns/{turn.id}/actions/action-1"
    first = assistant_client.post(path, data=data, follow_redirects=False)
    second = assistant_client.post(path, data=data, follow_redirects=False)
    after = len(load_items(items_directory(application.state.content_root)).items)

    assert first.status_code == second.status_code == 303
    assert after == before + 1
    decision = application.state.assistant.decision(turn.id, "action-1")
    assert decision.status == "confirmed"
    assert decision.target_id

    learning_path = f"/assistant/turns/{turn.id}/actions/action-2"
    learning = assistant_client.post(
        learning_path,
        data={
            "decision": "confirm",
            "title": "补一组评测",
            "body": "完成最小可靠性练习。",
            "skill_id": skill.id,
            "priority": 4,
        },
        follow_redirects=False,
    )
    repeated = assistant_client.post(
        learning_path,
        data={
            "decision": "confirm",
            "title": "补一组评测",
            "body": "完成最小可靠性练习。",
            "skill_id": skill.id,
            "priority": 4,
        },
        follow_redirects=False,
    )
    assert learning.status_code == repeated.status_code == 303
    assert len(
        [task for task in application.state.career.learning_tasks() if task.title == "补一组评测"]
    ) == 1


def test_assistant_manual_bridge_imports_only_validated_summary(
    assistant_client: TestClient,
) -> None:
    application = assistant_client.app
    source = create_item(
        application.state.content_root,
        title="当前项目",
        body="完成一个可演示闭环。",
    )
    snapshot = AssistantContextBuilder(
        application.state.content_root,
        application.state.career,
        application.state.search,
        application.state.video,
    ).build("下一步做什么")

    created = assistant_client.post(
        "/assistant/manual",
        data={"outbound_text": snapshot.material},
        follow_redirects=False,
    )
    assert created.status_code == 303
    manual = assistant_client.get(created.headers["location"])
    assert manual.status_code == 200
    assert "人工桥接" in manual.text
    task_id = created.headers["location"].rstrip("/").split("/")[-1]

    imported = assistant_client.post(
        f"/assistant/manual/{task_id}/import",
        data={"result": json.dumps(_result(source.id), ensure_ascii=False)},
        follow_redirects=False,
    )
    assert imported.status_code == 303
    assert application.state.assistant.conversations()
    task = application.state.model_tasks.get(task_id)
    assert task.status == "confirmed"


def test_assistant_navigation_and_home_entry_render(assistant_client: TestClient) -> None:
    home = assistant_client.get("/")
    page = assistant_client.get("/assistant")

    assert home.status_code == page.status_code == 200
    assert "问问助手" in home.text
    assert "个人助手" in page.text
    assert 'href="http://testserver/assistant"' in page.text
