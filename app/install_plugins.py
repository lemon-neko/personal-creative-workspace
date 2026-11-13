"""Provision the fixed desktop plugins from verified local upstream checkouts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.atomic import atomic_write_text, content_lock
from app.plugin_packages import (
    AUTOLOOP_COMMIT, VERSIONS, read_manifest, require_web_package, tree_hash, verify_packages,
)
from app.plugin_paths import HUB_URL, plugin_root
from app.privacy import default_data_root, prepare_private_root
from app.workflow_hub import EVENT_TYPE, RULE, plugin_environment

def refresh_web(root: Path, web: Path) -> None:
    """Replace the Web bundle and its checksum while retaining plugin data."""
    require_web_package(web)
    if root.is_symlink() or root.parent.is_symlink() or not root.is_dir():
        raise ValueError("插件目录无效")
    with content_lock(root), tempfile.TemporaryDirectory(dir=root) as tmp:
        verify_packages(root, package="web")
        manifest_path = root / "packages.json"
        previous_manifest = manifest_path.read_text()
        manifest = read_manifest(root)
        stage = Path(tmp)
        pending = stage / "web"
        previous = stage / "previous"
        shutil.copytree(web, pending, symlinks=True)
        manifest["sha256"]["web"] = tree_hash(pending)
        if json.loads(previous_manifest) == manifest:
            return
        current = root / "web"
        current.rename(previous)
        try:
            pending.rename(current)
            atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
        except BaseException:
            if current.exists():
                current.rename(pending)
            previous.rename(current)
            if not manifest_path.exists() or manifest_path.read_text() != previous_manifest:
                atomic_write_text(manifest_path, previous_manifest)
            raise


def provision(data_root: Path, web: Path, engine_source: Path) -> None:
    root = plugin_root(prepare_private_root(data_root))
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("插件目录无效")
    root.mkdir(mode=0o700, exist_ok=True)
    with content_lock(root):
        if (root / "packages.json").is_file():
            verify_packages(root)
            return
        if any((root / part).exists() or (root / part).is_symlink()
               for part in ("web", "autoloop", "autoloop-data", "packages.json")):
            raise RuntimeError("发现未完成的插件安装，请检查旧目录")
        commit = subprocess.check_output(["git", "-C", str(engine_source), "rev-parse", "HEAD"], text=True).strip()
        if commit != AUTOLOOP_COMMIT:
            raise ValueError("需要 Agent Autoloop v1.8.1")
        require_web_package(web)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            stage = Path(tmp)
            shutil.copytree(web, stage / "web", symlinks=True)
            web_hash = tree_hash(stage / "web")
            engine = stage / "autoloop"
            engine.mkdir()
            archive = stage / "upstream.tar"
            subprocess.run(["git", "-C", str(engine_source), "archive", "-o", str(archive), commit], check=True)
            subprocess.run(["tar", "-xf", str(archive), "-C", str(engine)], check=True)
            home = stage / "autoloop-data"
            home.mkdir(mode=0o700)
            cwd = root / "autoloop-data"
            atomic_write_text(home / "rules.json", json.dumps({
                "timezone": "Asia/Shanghai", "sources": {"workbench": {"name": "羽白工作台"}},
                "agents": {"gateway": {"name": "工作台模型网关", "worker": "workbench", "use": "command", "command": ["false"]}},
                "channels": {},
                "rules": [{"name": RULE, "when": {"source": "workbench", "types": [EVENT_TYPE]},
                           "to": "gateway", "cwd": str(cwd), "parallel": 2}],
            }, ensure_ascii=False, indent=2))
            binary = ["node", str(engine / "bin/agent-autoloop.ts")]
            env = plugin_environment(home)
            subprocess.run([*binary, "check"], check=True, env=env, capture_output=True)
            keys = {
                role: subprocess.check_output([*binary, "key", "new", role, "workbench"], text=True, env=env).strip()
                for role in ("owner", "worker", "source")
            }
            atomic_write_text(home / "workbench-keys.json", json.dumps(keys))
            atomic_write_text(home / "config.json", json.dumps({
                "url": HUB_URL, "hub": {"listen": HUB_URL.removeprefix("http://")}, "owner": keys["owner"],
            }))
            manifest = {"versions": VERSIONS, "sha256": {"web": web_hash, "autoloop": tree_hash(engine)}}
            atomic_write_text(stage / "packages.json", json.dumps(manifest, indent=2))
            verify_packages(stage)
            published = []
            try:
                for name in ("web", "autoloop", "autoloop-data", "packages.json"):
                    (stage / name).rename(root / name)
                    published.append(name)
            except BaseException:
                for name in reversed(published):
                    (root / name).rename(stage / name)
                raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    install.add_argument("--web", type=Path, required=True)
    install.add_argument("--autoloop", type=Path, required=True)
    commands.add_parser("refresh-web").add_argument("--web", type=Path, required=True)
    commands.add_parser("enable")
    commands.add_parser("disable")
    args = parser.parse_args()
    root = plugin_root(args.data_root)
    if args.command == "install":
        provision(args.data_root, args.web.resolve(), args.autoloop.resolve())
    elif args.command == "refresh-web":
        refresh_web(root, args.web.resolve())
    elif args.command == "enable":
        verify_packages(root)
        atomic_write_text(root / "enabled", "1\n")
    else:
        if root.is_symlink() or root.parent.is_symlink():
            raise ValueError("插件目录无效")
        (root / "enabled").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
