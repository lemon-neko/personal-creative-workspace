import sqlite3
from datetime import date

import pytest

from app.agent_core import DEFAULT_PROJECT_ID


def test_failed_source_link_leaves_no_task(runtime, focus, monkeypatch):
    fields = dict(title="虚构任务", objective="核对资料", task_type="research", project_id=DEFAULT_PROJECT_ID)
    with pytest.raises(sqlite3.IntegrityError):
        runtime.create_task(**fields, source_event_id="event-missing")
    assert not runtime.tasks()

    def fail(*_args):
        raise sqlite3.OperationalError("activity write failed")

    monkeypatch.setattr("app.agent_runtime.infrastructure.adapters.focus_adapter.record_planner_activity", fail)
    event_id = focus.create_daily_event("虚构事件", date(2026, 11, 13))
    with pytest.raises(sqlite3.OperationalError, match="activity write failed"):
        runtime.create_task(**fields, source_event_id=event_id)
    assert not runtime.tasks()
    assert runtime.daily_task_ids() == {}
