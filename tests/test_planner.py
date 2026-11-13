import sqlite3
from datetime import date

import pytest

import app.focus as focus_module
from app.focus import FocusRepository, planner_slot, planner_slot_key


def test_planner_moves_leave_deadline_and_reject_stale_drop(tmp_path):
    repository = FocusRepository(tmp_path)
    today = date(2026, 11, 11)
    event_id = repository.create_daily_event("排程样例", today, due_on="2026-11-14")
    initial = planner_slot("2026-11-12", "09:30")
    repository.set_planner_slot(event_id, today, initial, "")
    with pytest.raises(ValueError, match="安排已变化"):
        repository.set_planner_slot(event_id, today, None, "")
    assert repository.planner_slots()[event_id] == initial
    assert repository.daily_event(event_id).due_on == "2026-11-14"
    with pytest.raises(ValueError, match="整点或半点"):
        planner_slot("2026-11-12", "09:15")
    repository.set_planner_slot(event_id, today, None, planner_slot_key(initial))
    assert event_id not in repository.planner_slots()
    assert repository.daily_event(event_id).due_on == "2026-11-14"


def test_planner_migration_rolls_back_and_preserves_existing_events(tmp_path, monkeypatch):
    migrate = focus_module.apply_migrations

    def legacy(*args, **kwargs):
        kwargs["migrations"].pop(4)
        return migrate(*args, **kwargs)

    monkeypatch.setattr(focus_module, "apply_migrations", legacy)
    old = FocusRepository(tmp_path)
    with old.connect() as connection:
        connection.execute("INSERT INTO daily_events VALUES(?,?,?,?,?)", ("event-test", "已有事项", "2026-11-12", "planned", "2026-11-11"))
    monkeypatch.setattr(focus_module, "apply_migrations", migrate)
    with monkeypatch.context() as failure:
        failure.setattr(focus_module, "SCHEMA_V4", focus_module.SCHEMA_V4 + "INSERT INTO missing VALUES (1);")
        with pytest.raises(sqlite3.OperationalError):
            FocusRepository(tmp_path)
    with old.connect() as connection:
        assert connection.execute("SELECT version FROM schema_migrations WHERE subsystem='focus'").fetchone()[0] == 3
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='planner_slots'").fetchone() is None
    upgraded = FocusRepository(tmp_path)
    assert upgraded.daily_event("event-test").title == "已有事项"
    assert not upgraded.planner_slots()
