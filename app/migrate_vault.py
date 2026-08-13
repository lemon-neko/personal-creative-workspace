"""CLI for the private lifecycle-directory migration."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.privacy import default_data_root, prepare_private_root
from app.vault import apply_vault_migration, plan_vault_migration


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移羽白工作台的生命周期目录")
    parser.add_argument("--apply", action="store_true", help="实际迁移；默认 dry-run")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=default_data_root(),
        help="私人工作台数据根目录",
    )
    args = parser.parse_args()
    data_root = args.data_root.expanduser().resolve()
    content_root = data_root / "content"
    entries = plan_vault_migration(content_root)
    for entry in entries:
        print(
            f"{entry.action:9} {entry.source} -> {entry.destination} "
            f"[{entry.digest[:12]}]",
        )
    if not args.apply:
        print("这是 dry-run；添加 --apply 后才会复制、校验并保留回滚目录。")
        return
    prepare_private_root(data_root)
    rollback = apply_vault_migration(content_root, entries)
    if rollback:
        print(f"迁移完成；旧目录保存在 {rollback}")
    else:
        print("没有需要迁移的旧内容。")


if __name__ == "__main__":
    main()
