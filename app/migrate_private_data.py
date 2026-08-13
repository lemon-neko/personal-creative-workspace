"""Copy legacy repository content into the private application data directory."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.privacy import default_data_root, prepare_private_root


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MigrationEntry:
    source: Path
    destination: Path
    digest: str
    action: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _equivalent_after_asset_migration(source: Path, destination: Path) -> bool:
    if source.suffix.lower() != ".md":
        return False
    try:
        legacy = source.read_text(encoding="utf-8").replace(
            "/static/images/",
            "/assets/",
        )
        return destination.read_text(encoding="utf-8") == legacy
    except (OSError, UnicodeError):
        return False


def plan_migration(source_root: Path, data_root: Path) -> tuple[MigrationEntry, ...]:
    """Describe an idempotent copy without changing either directory."""

    destination_root = data_root / "content"
    entries: list[MigrationEntry] = []
    if not source_root.exists():
        return ()
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        digest = _sha256(source)
        if not destination.exists():
            action = "copy"
        elif _sha256(destination) == digest or _equivalent_after_asset_migration(
            source,
            destination,
        ):
            action = "unchanged"
        else:
            action = "conflict"
        entries.append(MigrationEntry(source, destination, digest, action))
    return tuple(entries)


def apply_migration(entries: tuple[MigrationEntry, ...]) -> None:
    """Copy non-conflicting files and preserve source files."""

    conflicts = [entry for entry in entries if entry.action == "conflict"]
    if conflicts:
        names = ", ".join(entry.source.name for entry in conflicts)
        raise ValueError(f"目标目录存在内容不同的同名文件：{names}")
    for entry in entries:
        if entry.action != "copy":
            continue
        entry.destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(entry.source, entry.destination)
        entry.destination.chmod(0o600)
        if _sha256(entry.destination) != entry.digest:
            entry.destination.unlink(missing_ok=True)
            raise OSError(f"复制后校验失败：{entry.source.name}")


def migrate_legacy_assets(source: Path, data_root: Path) -> tuple[Path, ...]:
    """Copy legacy article images and rewrite private Markdown asset URLs."""

    destination_root = data_root / "content" / "assets"
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination_root.chmod(0o700)
    copied: list[Path] = []
    if source.exists():
        for image in sorted(source.iterdir()):
            if not image.is_file() or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            destination = destination_root / image.name
            if destination.exists() and _sha256(destination) != _sha256(image):
                raise ValueError(f"私有配图目录存在内容不同的同名文件：{image.name}")
            if not destination.exists():
                shutil.copy2(image, destination)
                destination.chmod(0o600)
                copied.append(destination)
    for markdown in (data_root / "content" / "items").glob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        rewritten = text.replace("/static/images/", "/assets/")
        if rewritten != text:
            markdown.write_text(rewritten, encoding="utf-8")
            markdown.chmod(0o600)
    return tuple(copied)


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移羽白工作台的本地内容")
    parser.add_argument("--apply", action="store_true", help="实际复制；默认仅预览")
    parser.add_argument("--source", type=Path, default=REPO_ROOT / "content")
    parser.add_argument("--destination", type=Path, default=default_data_root())
    args = parser.parse_args()

    data_root = args.destination.expanduser().resolve()
    entries = plan_migration(args.source.expanduser().resolve(), data_root)
    for entry in entries:
        print(f"{entry.action:9} {entry.source} -> {entry.destination} [{entry.digest[:12]}]")
    if args.apply:
        prepare_private_root(data_root)
        apply_migration(entries)
        assets = migrate_legacy_assets(REPO_ROOT / "app" / "static" / "images", data_root)
        for asset in assets:
            print(f"asset     {asset}")
        print("迁移完成；原始文件仍然保留。")
    else:
        print("这是 dry-run；添加 --apply 后才会复制。")


if __name__ == "__main__":
    main()
