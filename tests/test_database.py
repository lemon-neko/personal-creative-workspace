from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database import (
    MOBILE_REGISTRY,
    WORKSPACE_REGISTRY,
    apply_migrations,
    connect_database,
    initialize_mobile_database,
    initialize_workspace_database,
    register_schema,
)


def test_existing_workspace_database_gets_snapshot_and_registry(tmp_path: Path) -> None:
    path = tmp_path / "workspace.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE legacy_value(id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO legacy_value(id) VALUES(1)")
        connection.execute("PRAGMA user_version = 2")

    snapshot = initialize_workspace_database(tmp_path)

    assert snapshot is not None and snapshot.is_file()
    assert snapshot.stat().st_mode & 0o777 == 0o600
    with connect_database(path) as connection:
        assert connection.execute("SELECT id FROM legacy_value").fetchone()[0] == 1
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (WORKSPACE_REGISTRY,),
        ).fetchone()

    assert initialize_workspace_database(tmp_path) is None


def test_schema_registration_is_idempotent_and_rejects_newer_data(
    tmp_path: Path,
) -> None:
    initialize_workspace_database(tmp_path)
    path = tmp_path / "workspace.db"
    register_schema(
        path,
        registry=WORKSPACE_REGISTRY,
        subsystem="example",
        version=2,
    )
    register_schema(
        path,
        registry=WORKSPACE_REGISTRY,
        subsystem="example",
        version=2,
    )
    with pytest.raises(RuntimeError, match="高于当前应用"):
        register_schema(
            path,
            registry=WORKSPACE_REGISTRY,
            subsystem="example",
            version=1,
        )


def test_mobile_database_uses_separate_registry(tmp_path: Path) -> None:
    initialize_mobile_database(tmp_path)
    with connect_database(tmp_path / "mobile.db") as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (MOBILE_REGISTRY,),
        ).fetchone()


def test_transactional_migration_failure_preserves_previous_version(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workspace.db"
    snapshots = tmp_path / "working" / "db-migrations"
    apply_migrations(
        path,
        registry=WORKSPACE_REGISTRY,
        subsystem="sample",
        snapshot_root=snapshots,
        migrations={1: "CREATE TABLE sample_value(id INTEGER PRIMARY KEY);"},
    )
    with connect_database(path) as connection:
        connection.execute("INSERT INTO sample_value(id) VALUES(1)")

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(
            path,
            registry=WORKSPACE_REGISTRY,
            subsystem="sample",
            snapshot_root=snapshots,
            migrations={
                1: "CREATE TABLE sample_value(id INTEGER PRIMARY KEY);",
                2: (
                    "CREATE TABLE should_rollback(id INTEGER PRIMARY KEY);\n"
                    "INSERT INTO missing_table(id) VALUES(1);"
                ),
            },
        )

    with connect_database(path) as connection:
        assert connection.execute("SELECT id FROM sample_value").fetchone()[0] == 1
        assert connection.execute(
            f"SELECT version FROM {WORKSPACE_REGISTRY} WHERE subsystem='sample'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='should_rollback'"
        ).fetchone() is None
    assert tuple(snapshots.glob("workspace-before-sample-v1-to-v2-*.db"))


def test_migration_refuses_database_newer_than_application(tmp_path: Path) -> None:
    path = tmp_path / "workspace.db"
    snapshots = tmp_path / "working" / "db-migrations"
    apply_migrations(
        path,
        registry=WORKSPACE_REGISTRY,
        subsystem="future",
        snapshot_root=snapshots,
        migrations={1: "CREATE TABLE future_value(id INTEGER PRIMARY KEY);"},
    )
    register_schema(
        path,
        registry=WORKSPACE_REGISTRY,
        subsystem="future",
        version=2,
    )

    with pytest.raises(RuntimeError, match="高于当前应用"):
        apply_migrations(
            path,
            registry=WORKSPACE_REGISTRY,
            subsystem="future",
            snapshot_root=snapshots,
            migrations={1: "CREATE TABLE future_value(id INTEGER PRIMARY KEY);"},
        )
