"""Explicit inventory and isolated recovery exercise for private workspace data."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.backup import INCLUDED_ROOTS, restore_encrypted_backup
from app.database import MOBILE_REGISTRY, WORKSPACE_REGISTRY
from app.privacy import default_data_root, prepare_private_root


SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class RecoveryInventory:
    created_at: str
    markdown_files: int
    attachment_files: int
    database_files: int
    total_bytes: int
    aggregate_sha256: str
    schema_versions: tuple[tuple[str, str, int], ...]


def _digest_file(path: Path) -> tuple[int, bytes]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.digest()


def _schema_versions(path: Path, registry: str) -> tuple[tuple[str, str, int], ...]:
    if not path.is_file():
        return ()
    try:
        with sqlite3.connect(path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (registry,),
            ).fetchone()
            if not exists:
                return ()
            rows = connection.execute(
                f"SELECT subsystem, version FROM {registry} ORDER BY subsystem"
            ).fetchall()
    except sqlite3.DatabaseError:
        return ()
    database = path.name
    return tuple((database, str(row[0]), int(row[1])) for row in rows)


def create_inventory(data_root: Path) -> RecoveryInventory:
    """Build a content-free recovery anchor using counts, versions and checksums."""

    data_root = data_root.expanduser().resolve()
    aggregate = hashlib.sha256()
    markdown_files = 0
    attachment_files = 0
    database_files = 0
    total_bytes = 0
    candidates: list[Path] = []
    for name in INCLUDED_ROOTS:
        root = data_root / name
        if root.exists():
            candidates.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.name != ".content.lock"
                and ".obsidian" not in path.relative_to(root).parts
            )
    for name in ("workspace.db", "mobile.db"):
        path = data_root / name
        if path.is_file():
            candidates.append(path)

    for path in sorted(candidates, key=lambda value: value.relative_to(data_root).as_posix()):
        relative = path.relative_to(data_root).as_posix()
        size, digest = _digest_file(path)
        total_bytes += size
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest)
        if path.suffix.casefold() == ".md":
            markdown_files += 1
        elif path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            database_files += 1
        else:
            attachment_files += 1

    versions = (
        *_schema_versions(data_root / "workspace.db", WORKSPACE_REGISTRY),
        *_schema_versions(data_root / "mobile.db", MOBILE_REGISTRY),
    )
    return RecoveryInventory(
        created_at=datetime.now(SHANGHAI).replace(microsecond=0).isoformat(),
        markdown_files=markdown_files,
        attachment_files=attachment_files,
        database_files=database_files,
        total_bytes=total_bytes,
        aggregate_sha256=aggregate.hexdigest(),
        schema_versions=tuple(versions),
    )


def write_inventory(inventory: RecoveryInventory, output: Path) -> Path:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.write_text(
        json.dumps(asdict(inventory), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output.chmod(0o600)
    return output


def exercise_restore(archive: Path, password: str, target: Path) -> RecoveryInventory:
    """Restore a backup only into a new empty directory and return its inventory."""

    target = target.expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("隔离恢复目录必须不存在或为空")
    prepare_private_root(target)
    restore_encrypted_backup(archive.expanduser().resolve(), password, target)
    return create_inventory(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="羽白工作台恢复锚点与隔离演练")
    commands = parser.add_subparsers(dest="action", required=True)
    inventory = commands.add_parser("inventory", help="生成不含正文的恢复锚点")
    inventory.add_argument("--data-root", type=Path, default=None)
    inventory.add_argument("--output", type=Path, required=True)
    exercise = commands.add_parser("exercise", help="将加密备份恢复到隔离目录")
    exercise.add_argument("archive", type=Path)
    exercise.add_argument("--target", type=Path, required=True)
    exercise.add_argument("--confirm", required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.action == "inventory":
        root = arguments.data_root or default_data_root()
        path = write_inventory(create_inventory(root), arguments.output)
        print(f"恢复锚点已写入：{path}")
        return
    if arguments.confirm != "ISOLATED-RESTORE":
        raise SystemExit("请使用 --confirm ISOLATED-RESTORE 明确确认隔离恢复")
    password = getpass.getpass("备份口令：")
    result = exercise_restore(arguments.archive, password, arguments.target)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
