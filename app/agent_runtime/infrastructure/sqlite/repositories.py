import json
from sqlite3 import Connection

from app.agent_runtime.domain.models import AgentRun, AgentStep, Artifact, ToolCall, WorkspaceProject, WorkspaceTask
from app.agent_runtime.domain.states import DEFAULT_PROJECT_ID


class RuntimeRepository:
    """Agent Runtime queries on the current unit of work's connection."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def projects(self, *, include_archived: bool = False) -> tuple[WorkspaceProject, ...]:
        where = "" if include_archived else "WHERE status <> 'archived'"
        rows = self.connection.execute(
            f"SELECT * FROM workspace_projects {where} ORDER BY updated_at DESC"
        ).fetchall()
        return tuple(WorkspaceProject(**dict(row)) for row in rows)

    def project(self, project_id: str) -> WorkspaceProject | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_projects WHERE id=?", (project_id,)
        ).fetchone()
        return WorkspaceProject(**dict(row)) if row else None

    def tasks(self, *, project_id: str = "") -> tuple[WorkspaceTask, ...]:
        where = "WHERE project_id=?" if project_id else ""
        values = (project_id,) if project_id else ()
        rows = self.connection.execute(
            f"SELECT * FROM workspace_tasks {where} ORDER BY priority, updated_at DESC",
            values,
        ).fetchall()
        return tuple(WorkspaceTask(**dict(row)) for row in rows)

    def task(self, task_id: str) -> WorkspaceTask | None:
        row = self.connection.execute(
            "SELECT * FROM workspace_tasks WHERE id=?", (task_id,)
        ).fetchone()
        return WorkspaceTask(**dict(row)) if row else None

    def runs(self, *, task_id: str = "") -> tuple[AgentRun, ...]:
        where = "WHERE task_id=?" if task_id else ""
        values = (task_id,) if task_id else ()
        rows = self.connection.execute(
            f"SELECT * FROM agent_runs {where} ORDER BY created_at DESC, rowid DESC", values
        ).fetchall()
        return tuple(AgentRun(**dict(row)) for row in rows)

    def run(self, run_id: str) -> AgentRun | None:
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE id=?", (run_id,)
        ).fetchone()
        return AgentRun(**dict(row)) if row else None

    def steps(self, run_id: str) -> tuple[AgentStep, ...]:
        rows = self.connection.execute(
            "SELECT * FROM agent_steps WHERE run_id=? ORDER BY position", (run_id,)
        ).fetchall()
        return tuple(AgentStep(**dict(row)) for row in rows)

    def tool_calls(self, run_id: str) -> tuple[ToolCall, ...]:
        rows = self.connection.execute(
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
        rows = self.connection.execute(
            f"SELECT * FROM artifacts {where} ORDER BY created_at DESC", values
        ).fetchall()
        return tuple(Artifact(**dict(row)) for row in rows)

    def artifact(self, artifact_id: str) -> Artifact | None:
        row = self.connection.execute(
            "SELECT * FROM artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        return Artifact(**dict(row)) if row else None

    def decision(self, run_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM agent_run_decisions WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return {"question": row["question"], "options": json.loads(row["options_json"]), "answer": row["answer"]}

    def planned_decisions(self) -> dict[str, str]:
        return dict(self.connection.execute(
            """SELECT d.run_id,CASE WHEN d.answer='' THEN 'decision' ELSE 'resume' END
            FROM agent_run_decisions d JOIN agent_runs r ON r.id=d.run_id WHERE r.status='planned'"""
        ).fetchall())

    def seed_project(self, stamp: str) -> None:
        self.connection.execute(
            """INSERT OR IGNORE INTO workspace_projects (id,title,description,status,created_at,updated_at)
            VALUES(?,'Personal Agent Team','个人工作台统一任务运行时的默认项目。','active',?,?)""",
            (DEFAULT_PROJECT_ID, stamp, stamp),
        )

    def _insert(self, table: str, record) -> None:
        values = tuple(record.__dict__.values())
        placeholders = ",".join("?" for _ in values)
        self.connection.execute(f"INSERT INTO {table} VALUES({placeholders})", values)

    def add_project(self, project: WorkspaceProject) -> None:
        self._insert("workspace_projects", project)

    def add_task(self, task: WorkspaceTask) -> None:
        self._insert("workspace_tasks", task)

    def add_run(self, run: AgentRun, steps: tuple[AgentStep, ...]) -> None:
        self._insert("agent_runs", run)
        for step in steps:
            self._insert("agent_steps", step)

    def planned_run(self, task_id: str) -> AgentRun | None:
        row = self.connection.execute(
            """SELECT * FROM agent_runs WHERE task_id=? AND status='planned'
            ORDER BY created_at DESC LIMIT 1""", (task_id,),
        ).fetchone()
        return AgentRun(**dict(row)) if row else None

    def set_task_state(self, task_id: str, status: str, action: str, stamp: str) -> None:
        self.connection.execute(
            "UPDATE workspace_tasks SET status=?,next_action=?,revision=revision+1,updated_at=? WHERE id=?",
            (status, action, stamp, task_id),
        )

    def set_objective(self, task_id: str, objective: str, stamp: str) -> None:
        self.connection.execute(
            "UPDATE workspace_tasks SET objective=?,revision=revision+1,updated_at=? WHERE id=?",
            (objective, stamp, task_id),
        )

    def add_decision(self, run_id: str, question: str, options: list[str]) -> None:
        self.connection.execute(
            "INSERT INTO agent_run_decisions VALUES(?,?,?,'')",
            (run_id, question, json.dumps(options, ensure_ascii=False)),
        )

    def answer_decision(self, run_id: str, answer: str) -> None:
        self.connection.execute("UPDATE agent_run_decisions SET answer=? WHERE run_id=?", (answer, run_id))

    def claim_run(self, run_id: str, stamp: str) -> None:
        self.connection.execute(
            "UPDATE agent_runs SET status='running',started_at=?,current_step=1 WHERE id=?",
            (stamp, run_id),
        )

    def set_run_progress(self, run_id: str, status: str, step: int) -> None:
        self.connection.execute("UPDATE agent_runs SET status=?,current_step=? WHERE id=?", (status, step, run_id))

    def finish_run(self, run_id: str, status: str, stamp: str, error_code: str = "") -> None:
        self.connection.execute(
            "UPDATE agent_runs SET status=?,completed_at=?,error_code=? WHERE id=?",
            (status, stamp, error_code, run_id),
        )

    def set_step(self, step_id: str, status: str, stamp: str, artifact_id: str = "") -> None:
        if status == "running":
            self.connection.execute(
                "UPDATE agent_steps SET status=?,started_at=? WHERE id=?", (status, stamp, step_id),
            )
        else:
            self.connection.execute(
                "UPDATE agent_steps SET status=?,output_artifact_id=?,completed_at=? WHERE id=?",
                (status, artifact_id, stamp, step_id),
            )

    def finish_steps(self, run_id: str, status: str, stamp: str, *, include_pending: bool = False) -> None:
        self.connection.execute(
            """UPDATE agent_steps SET status=?,completed_at=? WHERE run_id=?
            AND (status='running' OR (status='pending' AND ?))""",
            (status, stamp, run_id, include_pending),
        )

    def add_tool_call(self, call: ToolCall) -> None:
        self._insert("tool_calls", call)

    def add_artifact(self, artifact: Artifact) -> None:
        self._insert("artifacts", artifact)

    def set_artifact_status(self, artifact_id: str, status: str, accepted_at: str = "") -> None:
        self.connection.execute(
            "UPDATE artifacts SET status=?,accepted_at=? WHERE id=?", (status, accepted_at, artifact_id),
        )

    def reject_candidates(self, run_id: str) -> None:
        self.connection.execute("UPDATE artifacts SET status='rejected' WHERE run_id=? AND status='review'", (run_id,))

    def running_runs(self) -> tuple[AgentRun, ...]:
        return tuple(AgentRun(**dict(row)) for row in self.connection.execute(
            "SELECT * FROM agent_runs WHERE status='running'"
        ))
