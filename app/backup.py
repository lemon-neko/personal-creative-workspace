"""Password-protected private workspace backups."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

import pyzipper


SHANGHAI = ZoneInfo("Asia/Shanghai")
BACKUP_VERSION = 1
INCLUDED_ROOTS = ("content", "documents", "video-projects")


@dataclass(frozen=True)
class BackupPreview:
    created_at: str
    file_count: int
    total_bytes: int
    files: tuple[str, ...]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _snapshot_database(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    with sqlite3.connect(source) as original, sqlite3.connect(destination) as snapshot:
        original.backup(snapshot)
    destination.chmod(0o600)


def create_encrypted_backup(data_root: Path, password: str, output: Path) -> BackupPreview:
    """Create an AES-256 archive with a checksummed manifest."""

    if len(password) < 10:
        raise ValueError("备份口令至少需要 10 个字符")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=data_root / "working") as temp_name:
        temp = Path(temp_name)
        _snapshot_database(data_root / "workspace.db", temp / "workspace.db")
        sources: list[tuple[str, Path]] = []
        if (temp / "workspace.db").exists():
            sources.append(("workspace.db", temp / "workspace.db"))
        for root_name in INCLUDED_ROOTS:
            root = data_root / root_name
            if root.exists():
                sources.extend(
                    (path.relative_to(data_root).as_posix(), path)
                    for path in sorted(root.rglob("*"))
                    if path.is_file() and path.name != ".content.lock"
                )

        files: list[dict] = []
        with pyzipper.AESZipFile(
            output,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as archive:
            archive.setpassword(password.encode("utf-8"))
            archive.setencryption(pyzipper.WZ_AES, nbits=256)
            for archive_name, path in sources:
                data = path.read_bytes()
                files.append(
                    {"path": archive_name, "size": len(data), "sha256": _digest(data)},
                )
                archive.writestr(archive_name, data)
            manifest = {
                "version": BACKUP_VERSION,
                "created_at": datetime.now(SHANGHAI).replace(microsecond=0).isoformat(),
                "files": files,
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    output.chmod(0o600)
    return BackupPreview(
        manifest["created_at"],
        len(files),
        sum(item["size"] for item in files),
        tuple(item["path"] for item in files),
    )


def inspect_encrypted_backup(path: Path, password: str) -> BackupPreview:
    """Decrypt and verify every file without changing workspace data."""

    try:
        with pyzipper.AESZipFile(path) as archive:
            archive.setpassword(password.encode("utf-8"))
            names = archive.namelist()
            if not all(_safe_name(name) for name in names) or "manifest.json" not in names:
                raise ValueError("备份包含不安全路径或缺少清单")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("version") != BACKUP_VERSION or not isinstance(manifest.get("files"), list):
                raise ValueError("备份版本不受支持")
            listed = {str(item.get("path")): item for item in manifest["files"] if isinstance(item, dict)}
            if set(names) != set(listed) | {"manifest.json"}:
                raise ValueError("备份文件与清单不一致")
            for name, item in listed.items():
                data = archive.read(name)
                if len(data) != item.get("size") or _digest(data) != item.get("sha256"):
                    raise ValueError(f"备份校验失败：{name}")
    except (OSError, RuntimeError, pyzipper.BadZipFile, json.JSONDecodeError) as error:
        raise ValueError("备份口令错误或文件已损坏") from error
    return BackupPreview(
        str(manifest.get("created_at", "")),
        len(listed),
        sum(int(item.get("size", 0)) for item in listed.values()),
        tuple(sorted(listed)),
    )


def restore_encrypted_backup(path: Path, password: str, data_root: Path) -> Path:
    """Validate, stage, then atomically swap backed-up roots with rollback copies."""

    preview = inspect_encrypted_backup(path, password)
    working = data_root / "working"
    working.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix="restore-", dir=working))
    try:
        with pyzipper.AESZipFile(path) as archive:
            archive.setpassword(password.encode("utf-8"))
            for name in preview.files:
                destination = staging / PurePosixPath(name)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_bytes(archive.read(name))
                destination.chmod(0o600)

        stamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
        rollback = data_root / f"rollback-{stamp}"
        rollback.mkdir(mode=0o700)
        targets = ["workspace.db", "workspace.db-wal", "workspace.db-shm", *INCLUDED_ROOTS]
        moved: list[str] = []
        installed: list[str] = []
        try:
            for name in targets:
                current = data_root / name
                incoming = staging / name
                if current.exists():
                    current.replace(rollback / name)
                    moved.append(name)
                if incoming.exists():
                    incoming.replace(current)
                    installed.append(name)
            for root_name in INCLUDED_ROOTS:
                directory = data_root / root_name
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                directory.chmod(0o700)
        except Exception:
            for name in reversed(installed):
                current = data_root / name
                if current.is_dir():
                    shutil.rmtree(current, ignore_errors=True)
                else:
                    current.unlink(missing_ok=True)
            for name in reversed(moved):
                saved = rollback / name
                if saved.exists():
                    saved.replace(data_root / name)
            raise
        return rollback
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
