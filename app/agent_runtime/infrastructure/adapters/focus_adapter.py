from sqlite3 import Connection

from app.agent_runtime.domain.models import WorkspaceTask
from app.focus import record_planner_activity


class FocusAdapter:
    """Focus and Daily associations on the same connection as the task write."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def linked_tasks(self, goal_id: str) -> dict[str, str]:
        rows = self.connection.execute(
            """SELECT l.action_id,l.task_id FROM focus_action_tasks l
            JOIN focus_actions a ON a.id=l.action_id
            JOIN focus_deliverables d ON d.id=a.deliverable_id WHERE d.goal_id=?""",
            (goal_id,),
        )
        return {row["action_id"]: row["task_id"] for row in rows}

    def task_source(self, task_id: str) -> tuple[str, str] | None:
        row = self.connection.execute(
            """SELECT d.goal_id,l.action_id FROM focus_action_tasks l
            JOIN focus_actions a ON a.id=l.action_id
            JOIN focus_deliverables d ON d.id=a.deliverable_id WHERE l.task_id=?""",
            (task_id,),
        ).fetchone()
        return (row["goal_id"], row["action_id"]) if row else None

    def private_task_ids(self) -> set[str]:
        return {row[0] for row in self.connection.execute(
            """SELECT l.task_id FROM focus_action_tasks l
            JOIN focus_actions a ON a.id=l.action_id
            JOIN focus_deliverables d ON d.id=a.deliverable_id
            JOIN focus_goals g ON g.id=d.goal_id WHERE g.visibility='detail_only'"""
        )}

    def daily_task_ids(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT event_id,task_id FROM daily_event_tasks").fetchall())

    def daily_task_source(self, task_id: str) -> str:
        row = self.connection.execute("SELECT event_id FROM daily_event_tasks WHERE task_id=?", (task_id,)).fetchone()
        return row[0] if row else ""

    def attention_runs(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT r.id,CASE WHEN r.status='planned' AND d1.answer='' THEN 'decision'
                WHEN r.status='planned' AND d1.answer<>'' THEN 'resume' ELSE r.status END AS status,t.title
            FROM workspace_tasks t
            JOIN agent_runs r ON r.rowid=(SELECT MAX(rowid) FROM agent_runs WHERE task_id=t.id)
            LEFT JOIN agent_run_decisions d1 ON d1.run_id=r.id
            LEFT JOIN focus_action_tasks l ON l.task_id=t.id
            LEFT JOIN focus_actions a ON a.id=l.action_id
            LEFT JOIN focus_deliverables d ON d.id=a.deliverable_id
            LEFT JOIN focus_goals g ON g.id=d.goal_id
            WHERE r.status IN ('reviewing','failed','planned')
            AND t.status=r.status AND (l.task_id IS NULL OR g.visibility='overview')
            ORDER BY CASE WHEN r.status='reviewing' THEN 0 WHEN d1.answer='' AND r.status='planned' THEN 1
                     WHEN r.status='failed' THEN 2 ELSE 3 END,
                     t.updated_at DESC,r.rowid DESC LIMIT 3"""
        )
        return [dict(row) for row in rows]

    def planner_day(self, event_id: str) -> str:
        row = self.connection.execute("SELECT day FROM planner_slots WHERE event_id=?", (event_id,)).fetchone()
        return row["day"] if row else ""

    def existing_task(self, *, action_id: str, event_id: str) -> WorkspaceTask | None:
        table, key, source_id = self._association(action_id, event_id)
        row = self.connection.execute(
            f"SELECT t.* FROM {table} l JOIN workspace_tasks t ON t.id=l.task_id WHERE l.{key}=?", (source_id,),
        ).fetchone()
        return WorkspaceTask(**dict(row)) if row else None

    def link_task(self, task_id: str, *, action_id: str, event_id: str) -> None:
        table, _, source_id = self._association(action_id, event_id)
        self.connection.execute(f"INSERT INTO {table} VALUES(?,?)", (source_id, task_id))
        record_planner_activity(self.connection, source_id, "交给 AI")

    @staticmethod
    def _association(action_id: str, event_id: str) -> tuple[str, str, str]:
        if action_id:
            return "focus_action_tasks", "action_id", action_id
        return "daily_event_tasks", "event_id", event_id
