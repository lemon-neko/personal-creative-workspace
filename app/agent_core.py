"""Minimal, local-only task runtime for the personal workspace."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.atomic import atomic_write_text, content_lock
from app.database import WORKSPACE_REGISTRY, apply_migrations, connect_database
from app.search import SearchResult
from app.workspace import SHANGHAI


PROJECT_STATUSES = {"active", "paused", "archived"}
TASK_TYPES = {"learning", "research", "creation", "build"}
TASK_STATUSES = {
    "draft",
    "planned",
    "running",
    "reviewing",
    "completed",
    "failed",
    "cancelled",
}
RUN_STATUSES = {"planned", "running", "reviewing", "completed", "failed", "cancelled"}
STEP_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}
ARTIFACT_STATUSES = {"review", "accepted", "rejected"}
MAX_TITLE = 160
MAX_OBJECTIVE = 8_000
MAX_DESCRIPTION = 2_000


ROLE_DEFINITIONS = {
    "learning": ("learning", "学习", "从本地材料组织解释、练习与验收路径。"),
    "research": ("research", "研究", "整理来源、已知事实和仍需验证的问题。"),
    "creation": ("creator", "创作", "把已确认材料组织成可继续编辑的创作工作纸。"),
    "build": ("builder", "构建", "把工程目标整理成约束、步骤和验收清单。"),
}

TASK_TYPE_LABELS = {
    "learning": "学习",
    "research": "研究",
    "creation": "创作",
    "build": "构建",
}

TASK_STATUS_LABELS = {
    "draft": "待规划",
    "planned": "已规划",
    "running": "运行中",
    "reviewing": "待确认",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

RUN_STATUS_LABELS = {
    "planned": "已规划",
    "running": "运行中",
    "reviewing": "待确认",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def _now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


@dataclass(frozen=True)
class WorkspaceProject:
    id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceTask:
    id: str
    project_id: str
    title: str
    objective: str
    task_type: str
    assigned_role: str
    status: str
    priority: int
    next_action: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AgentRun:
    id: str
    task_id: str
    role_key: str
    status: str
    current_step: int
    error_code: str
    created_at: str
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class AgentStep:
    id: str
    run_id: str
    position: int
    step_key: str
    title: str
    status: str
    output_artifact_id: str
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    run_id: str
    step_id: str
    tool_key: str
    status: str
    input_summary: str
    result_summary: str
    created_at: str


@dataclass(frozen=True)
class Artifact:
    id: str
    task_id: str
    run_id: str
    artifact_type: str
    title: str
    status: str
    storage_key: str
    content_hash: str
    summary: str
    created_at: str
    accepted_at: str


class AgentCoreRepository:
    """Persist task metadata and private artifacts without model prompt logs."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.database_path = data_root / "workspace.db"
        self.artifact_root = data_root / "working" / "agent-artifacts"
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifact_root.chmod(0o700)
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="agent_core",
            snapshot_root=data_root / "working" / "db-migrations",
            migrations={
                1: """CREATE TABLE IF NOT EXISTS workspace_projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','paused','archived')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '' REFERENCES workspace_projects(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    task_type TEXT NOT NULL CHECK(task_type IN ('learning','research','creation','build')),
                    assigned_role TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft','planned','running','reviewing','completed','failed','cancelled')),
                    priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5),
                    next_action TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_dependencies (
                    task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE CASCADE,
                    depends_on_task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE RESTRICT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, depends_on_task_id),
                    CHECK(task_id <> depends_on_task_id)
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE CASCADE,
                    role_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('planned','running','reviewing','completed','failed','cancelled')),
                    current_step INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('review','accepted','rejected')),
                    storage_key TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    accepted_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS agent_steps (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    step_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','cancelled')),
                    output_artifact_id TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(run_id, position)
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL REFERENCES agent_steps(id) ON DELETE CASCADE,
                    tool_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_summary TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_tasks_project ON workspace_tasks(project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_task ON agent_runs(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_steps(run_id, position);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, created_at);""",
            },
        )
        self._ensure_default_project()

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def _ensure_default_project(self) -> None:
        stamp = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO workspace_projects
                (id,title,description,status,created_at,updated_at)
                VALUES('project-personal-agent-team','Personal Agent Team',
                '个人工作台统一任务运行时的默认项目。','active',?,?)""",
                (stamp, stamp),
            )

    def projects(self, *, include_archived: bool = False) -> tuple[WorkspaceProject, ...]:
        where = "" if include_archived else "WHERE status <> 'archived'"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM workspace_projects {where} ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(WorkspaceProject(**dict(row)) for row in rows)

    def project(self, project_id: str) -> WorkspaceProject | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspace_projects WHERE id=?", (project_id,)
            ).fetchone()
        return WorkspaceProject(**dict(row)) if row else None

    def create_project(self, *, title: str, description: str = "") -> WorkspaceProject:
        title = _clean(title, MAX_TITLE)
        description = str(description or "").strip()[:MAX_DESCRIPTION]
        if not title:
            raise ValueError("项目名称不能为空")
        stamp = _now()
        project = WorkspaceProject(
            _identifier("project"), title, description, "active", stamp, stamp
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO workspace_projects VALUES(?,?,?,?,?,?)",
                tuple(project.__dict__.values()),
            )
        return project

    def tasks(self, *, project_id: str = "") -> tuple[WorkspaceTask, ...]:
        where = "WHERE project_id=?" if project_id else ""
        values = (project_id,) if project_id else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM workspace_tasks {where} ORDER BY priority, updated_at DESC",
                values,
            ).fetchall()
        return tuple(WorkspaceTask(**dict(row)) for row in rows)

    def task(self, task_id: str) -> WorkspaceTask | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspace_tasks WHERE id=?", (task_id,)
            ).fetchone()
        return WorkspaceTask(**dict(row)) if row else None

    def create_task(
        self,
        *,
        title: str,
        objective: str,
        task_type: str,
        project_id: str,
        priority: int = 3,
    ) -> WorkspaceTask:
        title = _clean(title, MAX_TITLE)
        objective = str(objective or "").strip()[:MAX_OBJECTIVE]
        if not title or not objective:
            raise ValueError("任务名称和目标不能为空")
        if task_type not in TASK_TYPES:
            raise ValueError("任务类型无效")
        if self.project(project_id) is None:
            raise ValueError("项目不存在")
        if priority not in range(1, 6):
            raise ValueError("优先级必须在 1 到 5 之间")
        role_key = ROLE_DEFINITIONS[task_type][0]
        stamp = _now()
        task = WorkspaceTask(
            _identifier("task"),
            project_id,
            title,
            objective,
            task_type,
            role_key,
            "draft",
            priority,
            "生成本地执行计划",
            1,
            stamp,
            stamp,
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO workspace_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(task.__dict__.values()),
            )
        return task

    def plan_task(self, task_id: str) -> AgentRun:
        task = self.task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status not in {"draft", "planned"}:
            raise ValueError("当前任务状态不能重新规划")
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT * FROM agent_runs WHERE task_id=? AND status='planned'
                ORDER BY created_at DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
            if existing:
                return AgentRun(**dict(existing))
            stamp = _now()
            run = AgentRun(
                _identifier("run"), task_id, task.assigned_role, "planned", 0, "", stamp, "", ""
            )
            connection.execute(
                "INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?)",
                tuple(run.__dict__.values()),
            )
            for position, step_key, title in (
                (1, "load-context", "读取本地上下文"),
                (2, "compose-artifact", "组织任务工作纸"),
                (3, "review-artifact", "执行确定性审查"),
            ):
                connection.execute(
                    "INSERT INTO agent_steps VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        _identifier("step"), run.id, position, step_key, title,
                        "pending", "", "", "",
                    ),
                )
            connection.execute(
                """UPDATE workspace_tasks SET status='planned',next_action='运行本地计划',
                revision=revision+1,updated_at=? WHERE id=?""",
                (stamp, task_id),
            )
        return run

    def runs(self, *, task_id: str = "") -> tuple[AgentRun, ...]:
        where = "WHERE task_id=?" if task_id else ""
        values = (task_id,) if task_id else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM agent_runs {where} ORDER BY created_at DESC", values
            ).fetchall()
        return tuple(AgentRun(**dict(row)) for row in rows)

    def run(self, run_id: str) -> AgentRun | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE id=?", (run_id,)
            ).fetchone()
        return AgentRun(**dict(row)) if row else None

    def steps(self, run_id: str) -> tuple[AgentStep, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_steps WHERE run_id=? ORDER BY position", (run_id,)
            ).fetchall()
        return tuple(AgentStep(**dict(row)) for row in rows)

    def tool_calls(self, run_id: str) -> tuple[ToolCall, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_calls WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
        return tuple(ToolCall(**dict(row)) for row in rows)

    def artifacts(self, *, task_id: str = "", run_id: str = "") -> tuple[Artifact, ...]:
        clauses: list[str] = []
        values: list[str] = []
        if task_id:
            clauses.append("task_id=?")
            values.append(task_id)
        if run_id:
            clauses.append("run_id=?")
            values.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM artifacts {where} ORDER BY created_at DESC", values
            ).fetchall()
        return tuple(Artifact(**dict(row)) for row in rows)

    def artifact(self, artifact_id: str) -> Artifact | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
        return Artifact(**dict(row)) if row else None

    def artifact_content(self, artifact_id: str) -> str:
        artifact = self.artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        path = self.artifact_root / artifact.storage_key
        if path.parent != self.artifact_root or not path.is_file():
            raise FileNotFoundError(artifact.storage_key)
        return path.read_text(encoding="utf-8")

    def _set_step(self, step_id: str, *, status: str, artifact_id: str = "") -> None:
        if status not in STEP_STATUSES:
            raise ValueError("步骤状态无效")
        stamp = _now()
        started = stamp if status == "running" else ""
        completed = stamp if status in {"completed", "failed", "cancelled"} else ""
        with self.connect() as connection:
            if status == "running":
                connection.execute(
                    "UPDATE agent_steps SET status=?,started_at=? WHERE id=?",
                    (status, started, step_id),
                )
            else:
                connection.execute(
                    """UPDATE agent_steps SET status=?,output_artifact_id=?,
                    completed_at=? WHERE id=?""",
                    (status, artifact_id, completed, step_id),
                )

    def _record_tool_call(
        self,
        *,
        run_id: str,
        step_id: str,
        result_count: int,
        term_count: int,
    ) -> None:
        call = ToolCall(
            _identifier("tool-call"),
            run_id,
            step_id,
            "workspace.search",
            "completed",
            f"本地关键词 {term_count} 个；未保存原始查询正文",
            f"返回 {result_count} 条本地来源摘要",
            _now(),
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tool_calls VALUES(?,?,?,?,?,?,?,?)",
                tuple(call.__dict__.values()),
            )

    @staticmethod
    def _artifact_markdown(
        task: WorkspaceTask,
        sources: Iterable[SearchResult],
    ) -> str:
        role = next((value for value in ROLE_DEFINITIONS.values() if value[0] == task.assigned_role), None)
        role_label = role[1] if role else task.assigned_role
        rows = list(sources)
        source_lines = "\n".join(
            f"- [{value.source_label}] {value.title} — {re.sub(r'<[^>]+>', '', value.snippet).strip()}"
            for value in rows
        ) or "- 当前本地索引没有命中内容；需要作者补充来源或拆分目标。"
        return (
            f"# {task.title}\n\n"
            f"> 本产物由本地规则式 {role_label} 角色生成，未调用模型，"
            "不代表正式知识结论。\n\n"
            "## 任务目标\n\n"
            f"{task.objective}\n\n"
            "## 本地来源摘要\n\n"
            f"{source_lines}\n\n"
            "## 建议执行路径\n\n"
            "1. 确认目标边界与完成标准。\n"
            "2. 阅读命中的本地来源，标记事实、判断和仍需验证的问题。\n"
            "3. 只在证据充分时形成候选结论；正式入库前关联随想与主题。\n\n"
            "## Reviewer 检查\n\n"
            "- 未调用外部模型或网络。\n"
            "- 未修改随想、知识卡、文章或外部系统。\n"
            "- 产物仅保存在私有工作目录，等待作者确认。\n"
        )

    def execute_run(self, run_id: str, search_results: Iterable[SearchResult]) -> Artifact:
        run = self.run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status == "reviewing":
            existing = self.artifacts(run_id=run_id)
            if existing:
                return existing[0]
        if run.status != "planned":
            raise ValueError("当前运行状态不能执行")
        task = self.task(run.task_id)
        if task is None:
            raise KeyError(run.task_id)
        steps = self.steps(run_id)
        if len(steps) != 3:
            raise RuntimeError("执行计划不完整")
        sources = tuple(search_results)[:8]
        stamp = _now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='running',started_at=?,current_step=1 WHERE id=?",
                (stamp, run_id),
            )
            connection.execute(
                """UPDATE workspace_tasks SET status='running',next_action='等待本地执行完成',
                revision=revision+1,updated_at=? WHERE id=?""",
                (stamp, task.id),
            )
        try:
            self._set_step(steps[0].id, status="running")
            term_count = len(re.findall(r"[\w\u3400-\u9fff]+", task.objective))
            self._record_tool_call(
                run_id=run_id,
                step_id=steps[0].id,
                result_count=len(sources),
                term_count=min(term_count, 8),
            )
            self._set_step(steps[0].id, status="completed")

            self._set_step(steps[1].id, status="running")
            body = self._artifact_markdown(task, sources)
            artifact_id = _identifier("artifact")
            storage_key = f"{artifact_id}.md"
            path = self.artifact_root / storage_key
            with content_lock(self.artifact_root):
                atomic_write_text(path, body, mode=0o600)
            artifact = Artifact(
                artifact_id,
                task.id,
                run_id,
                "task-worksheet",
                f"{task.title} · 任务工作纸",
                "review",
                storage_key,
                hashlib.sha256(body.encode("utf-8")).hexdigest(),
                f"本地来源 {len(sources)} 条；等待作者确认。",
                _now(),
                "",
            )
            try:
                with self.connect() as connection:
                    connection.execute(
                        "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(artifact.__dict__.values()),
                    )
            except Exception:
                path.unlink(missing_ok=True)
                raise
            self._set_step(steps[1].id, status="completed", artifact_id=artifact.id)

            self._set_step(steps[2].id, status="running")
            if "正式知识结论" not in body or "未调用模型" not in body:
                raise RuntimeError("Reviewer 未通过任务产物边界检查")
            self._set_step(steps[2].id, status="completed", artifact_id=artifact.id)
            stamp = _now()
            with self.connect() as connection:
                connection.execute(
                    """UPDATE agent_runs SET status='reviewing',current_step=3 WHERE id=?""",
                    (run_id,),
                )
                connection.execute(
                    """UPDATE workspace_tasks SET status='reviewing',next_action='人工确认任务产物',
                    revision=revision+1,updated_at=? WHERE id=?""",
                    (stamp, task.id),
                )
            return artifact
        except Exception:
            stamp = _now()
            with self.connect() as connection:
                connection.execute(
                    """UPDATE agent_runs SET status='failed',error_code='local-runtime-error',
                    completed_at=? WHERE id=?""",
                    (stamp, run_id),
                )
                connection.execute(
                    """UPDATE workspace_tasks SET status='failed',next_action='检查本地运行记录',
                    revision=revision+1,updated_at=? WHERE id=?""",
                    (stamp, task.id),
                )
            raise

    def approve_run(self, run_id: str) -> None:
        run = self.run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status == "completed":
            return
        if run.status != "reviewing":
            raise ValueError("只有待确认的运行可以接受")
        artifacts = self.artifacts(run_id=run_id)
        if not artifacts:
            raise ValueError("运行没有可确认的产物")
        stamp = _now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE artifacts SET status='accepted',accepted_at=? WHERE run_id=?",
                (stamp, run_id),
            )
            connection.execute(
                "UPDATE agent_runs SET status='completed',completed_at=? WHERE id=?",
                (stamp, run_id),
            )
            connection.execute(
                """UPDATE workspace_tasks SET status='completed',next_action='已完成人工确认',
                revision=revision+1,updated_at=? WHERE id=?""",
                (stamp, run.task_id),
            )

    def cancel_run(self, run_id: str) -> None:
        run = self.run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status in {"completed", "cancelled"}:
            return
        stamp = _now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='cancelled',completed_at=? WHERE id=?",
                (stamp, run_id),
            )
            connection.execute(
                """UPDATE agent_steps SET status='cancelled',completed_at=?
                WHERE run_id=? AND status IN ('pending','running')""",
                (stamp, run_id),
            )
            connection.execute(
                "UPDATE artifacts SET status='rejected' WHERE run_id=? AND status='review'",
                (run_id,),
            )
            connection.execute(
                """UPDATE workspace_tasks SET status='cancelled',next_action='任务已取消',
                revision=revision+1,updated_at=? WHERE id=?""",
                (stamp, run.task_id),
            )
