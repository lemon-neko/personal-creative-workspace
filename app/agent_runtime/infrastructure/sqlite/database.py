from pathlib import Path

from app.agent_runtime.infrastructure.sqlite.migrations import MIGRATIONS
from app.database import WORKSPACE_REGISTRY, apply_migrations


def initialize(data_root: Path, *, migrate=apply_migrations) -> None:
    migrate(
        data_root / "workspace.db",
        registry=WORKSPACE_REGISTRY,
        subsystem="agent_core",
        snapshot_root=data_root / "working" / "db-migrations",
        migrations=dict(MIGRATIONS),
    )
