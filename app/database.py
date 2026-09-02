"""Shared SQLite connection and version registry for private workspace data."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
WORKSPACE_REGISTRY = "schema_migrations"
MOBILE_REGISTRY = "mobile_schema_migrations"


def connect_database(path: Path, *, foreign_keys: bool = True) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    for candidate in (
        path,
        path.with_name(f"{path.name}-wal"),
        path.with_name(f"{path.name}-shm"),
    ):
        if candidate.exists():
            candidate.chmod(0o600)
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _snapshot_database(path: Path, snapshot_root: Path, label: str) -> Path:
    snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_root.chmod(0o700)
    timestamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
    target = snapshot_root / f"{path.stem}-before-{label}-{timestamp}.db"
    source = sqlite3.connect(path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    target.chmod(0o600)
    return target


def snapshot_database(path: Path, snapshot_root: Path, label: str) -> Path:
    """Create a permission-hardened SQLite backup for an explicit operation."""

    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(path)
    return _snapshot_database(path, snapshot_root, label)


def ensure_migration_registry(
    path: Path,
    *,
    registry: str,
    snapshot_root: Path,
) -> Path | None:
    """Create the registry once and snapshot an existing pre-registry database."""

    snapshot = None
    if path.exists() and path.stat().st_size > 0:
        with sqlite3.connect(path) as probe:
            legacy = not _table_exists(probe, registry)
        if legacy:
            snapshot = _snapshot_database(path, snapshot_root, registry)
    with connect_database(path) as connection:
        connection.execute(
            f"""CREATE TABLE IF NOT EXISTS {registry} (
                subsystem TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at TEXT NOT NULL
            )"""
        )
    path.chmod(0o600)
    return snapshot


def register_schema(
    path: Path,
    *,
    registry: str,
    subsystem: str,
    version: int,
) -> None:
    if version < 1:
        raise ValueError("数据库迁移版本必须大于 0")
    now = datetime.now(SHANGHAI).replace(microsecond=0).isoformat()
    with connect_database(path) as connection:
        row = connection.execute(
            f"SELECT version FROM {registry} WHERE subsystem=?", (subsystem,)
        ).fetchone()
        if row is not None and int(row["version"]) > version:
            raise RuntimeError(
                f"{subsystem} 数据版本高于当前应用，请先升级应用"
            )
        connection.execute(
            f"""INSERT INTO {registry}(subsystem,version,applied_at)
            VALUES(?,?,?)
            ON CONFLICT(subsystem) DO UPDATE SET
                version=excluded.version,
                applied_at=CASE
                    WHEN {registry}.version = excluded.version
                    THEN {registry}.applied_at ELSE excluded.applied_at END""",
            (subsystem, version, now),
        )


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute simple migration scripts without sqlite3.executescript auto-commits."""

    statement = ""
    for line in script.splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("数据库迁移脚本包含不完整语句")


def apply_migrations(
    path: Path,
    *,
    registry: str,
    subsystem: str,
    migrations: Mapping[int, str],
    snapshot_root: Path,
    legacy_version: int = 0,
) -> None:
    """Apply ordered migrations atomically and preserve the previous database."""

    ensure_migration_registry(path, registry=registry, snapshot_root=snapshot_root)
    expected = tuple(range(1, max(migrations, default=0) + 1))
    if tuple(sorted(migrations)) != expected:
        raise ValueError("数据库迁移版本必须从 1 连续递增")
    target = expected[-1] if expected else legacy_version
    now = datetime.now(SHANGHAI).replace(microsecond=0).isoformat()
    with sqlite3.connect(path) as probe:
        row = probe.execute(
            f"SELECT version FROM {registry} WHERE subsystem=?", (subsystem,)
        ).fetchone()
        observed = int(row[0]) if row is not None else legacy_version
        authored_tables = probe.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name NOT IN (?, 'sqlite_sequence')",
            (registry,),
        ).fetchone()[0]
    if observed < target and authored_tables:
        _snapshot_database(
            path,
            snapshot_root,
            f"{subsystem}-v{observed}-to-v{target}",
        )
    connection = connect_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            f"SELECT version FROM {registry} WHERE subsystem=?", (subsystem,)
        ).fetchone()
        current = int(row["version"]) if row is not None else legacy_version
        if current > target:
            raise RuntimeError(f"{subsystem} 数据版本高于当前应用，请先升级应用")
        if row is None and current:
            connection.execute(
                f"INSERT INTO {registry}(subsystem,version,applied_at) VALUES(?,?,?)",
                (subsystem, current, now),
            )
        for version in range(current + 1, target + 1):
            _execute_script(connection, migrations[version])
            connection.execute(
                f"""INSERT INTO {registry}(subsystem,version,applied_at)
                VALUES(?,?,?) ON CONFLICT(subsystem) DO UPDATE SET
                    version=excluded.version, applied_at=excluded.applied_at""",
                (subsystem, version, now),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    path.chmod(0o600)


def initialize_workspace_database(data_root: Path) -> Path | None:
    return ensure_migration_registry(
        data_root / "workspace.db",
        registry=WORKSPACE_REGISTRY,
        snapshot_root=data_root / "working" / "db-migrations",
    )


def initialize_mobile_database(data_root: Path) -> Path | None:
    return ensure_migration_registry(
        data_root / "mobile.db",
        registry=MOBILE_REGISTRY,
        snapshot_root=data_root / "working" / "db-migrations",
    )
