from contextlib import closing

from app.agent_core import DEFAULT_PROJECT_ID, AgentCoreRepository, WorkspaceTask
from app.agent_runtime.domain.models import WorkspaceTask as RuntimeTask


def test_existing_facade_reopens_the_same_tables_and_records(runtime, planned, tmp_path):
    task, run = planned
    reopened = AgentCoreRepository(tmp_path)
    assert WorkspaceTask is RuntimeTask
    assert reopened.project_service.project(DEFAULT_PROJECT_ID).status == "active"
    assert reopened.task_service.tasks(project_id=DEFAULT_PROJECT_ID)[0].id == task.id
    assert reopened.run_service.runs(task_id=task.id) == (run,)
    with closing(reopened.connect()) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations WHERE subsystem='agent_core'"
        ).fetchone()[0] == 3
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
