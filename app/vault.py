"""Lifecycle vault layout and explicit, checksummed legacy migration."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.content import parse_item
from app.workspace import SHANGHAI, content_directory


@dataclass(frozen=True)
class VaultMigrationEntry:
    source: Path
    destination: Path
    digest: str
    action: str
    kind: str = ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plan_vault_migration(content_root: Path) -> tuple[VaultMigrationEntry, ...]:
    """Plan migration from ``content/items`` without reading or changing bodies."""

    legacy = content_root / "items"
    if not legacy.exists():
        return ()
    entries: list[VaultMigrationEntry] = []
    for source in sorted(legacy.glob("*.md")):
        try:
            item = parse_item(source)
        except (OSError, TypeError, UnicodeError, ValueError):
            entries.append(
                VaultMigrationEntry(source, source, sha256_file(source), "invalid"),
            )
            continue
        destination = content_directory(content_root, item.kind) / source.name
        digest = sha256_file(source)
        if not destination.exists():
            action = "copy"
        elif sha256_file(destination) == digest:
            action = "unchanged"
        else:
            action = "conflict"
        entries.append(
            VaultMigrationEntry(source, destination, digest, action, item.kind),
        )
    return tuple(entries)


def apply_vault_migration(
    content_root: Path,
    entries: tuple[VaultMigrationEntry, ...],
) -> Path | None:
    """Copy and verify legacy items, then preserve the old directory as rollback."""

    blockers = [entry for entry in entries if entry.action in {"invalid", "conflict"}]
    if blockers:
        names = "、".join(entry.source.name for entry in blockers)
        raise ValueError(f"迁移存在无效或冲突文件：{names}")
    copied: list[Path] = []
    try:
        for entry in entries:
            if entry.action != "copy":
                continue
            entry.destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            entry.destination.parent.chmod(0o700)
            shutil.copy2(entry.source, entry.destination)
            entry.destination.chmod(0o600)
            if sha256_file(entry.destination) != entry.digest:
                raise OSError(f"复制后校验失败：{entry.source.name}")
            copied.append(entry.destination)
    except Exception:
        for path in copied:
            path.unlink(missing_ok=True)
        raise

    legacy = content_root / "items"
    if not legacy.exists() or not entries:
        return None
    stamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
    rollback = content_root / f"legacy-items-{stamp}"
    if rollback.exists():
        raise ValueError("迁移回滚目录已存在")
    legacy.replace(rollback)
    rollback.chmod(0o700)
    return rollback
