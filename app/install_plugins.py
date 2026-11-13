"""Provision the fixed desktop plugins from verified local upstream checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.atomic import atomic_write_text, content_lock
from app.plugins import plugin_root
from app.privacy import default_data_root, prepare_private_root
from app.workflow_hub import EVENT_TYPE, HUB_URL, RULE, plugin_environment

AUTOLOOP_COMMIT = "e8748fd0c2aad4013e5996c3188535567070f24a"
VERSIONS = {"super-productivity": "20.0.0", "agent-autoloop": "1.8.1"}
PACKAGE_VERSIONS = {"web": "super-productivity", "autoloop": "agent-autoloop"}


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(directory.rglob("*")):
        if file.is_symlink():
            raise ValueError("插件构建不允许符号链接")
        if file.is_file():
            digest.update(str(file.relative_to(directory)).encode() + b"\0")
            digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def verify_packages(root: Path, *, package: str | None = None) -> None:
    manifest = json.loads((root / "packages.json").read_text())
    versions = manifest["versions"]
    names = (package,) if package is not None else tuple(PACKAGE_VERSIONS)
    if package is None and versions != VERSIONS:
        raise ValueError("本地插件包版本或校验值不符")
    for name in names:
        upstream = PACKAGE_VERSIONS[name]
        if versions[upstream] != VERSIONS[upstream] or tree_hash(root / name) != manifest["sha256"][name]:
            raise ValueError("本地插件包版本或校验值不符")


def require_web_package(web: Path) -> None:
    if not (web / "index.html").is_file() or not (web / "assets/bundled-plugins/yubai-workbench/plugin.js").is_file():
        raise ValueError("需要已构建的 Super Productivity Web 插件包")


def refresh_web(root: Path, web: Path) -> None:
    """Replace the Web bundle and its checksum while retaining plugin data."""
    require_web_package(web)
    with content_lock(root), tempfile.TemporaryDirectory(dir=root) as tmp:
        verify_packages(root)
        manifest_path = root / "packages.json"
        previous_manifest = manifest_path.read_text()
        manifest = json.loads(previous_manifest)
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
            if manifest_path.read_text() != previous_manifest:
                atomic_write_text(manifest_path, previous_manifest)
            raise


def provision(data_root: Path, web: Path, engine_source: Path) -> None:
    root = plugin_root(prepare_private_root(data_root))
    root.mkdir(mode=0o700, exist_ok=True)
    with content_lock(root):
        if (root / "packages.json").is_file():
            verify_packages(root)
            return
        if any((root / part).exists() for part in ("web", "autoloop", "autoloop-data")):
            raise RuntimeError("发现未完成的插件安装，请检查旧目录")
        commit = subprocess.check_output(["git", "-C", str(engine_source), "rev-parse", "HEAD"], text=True).strip()
        if commit != AUTOLOOP_COMMIT:
            raise ValueError("需要 Agent Autoloop v1.8.1")
        require_web_package(web)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            stage = Path(tmp)
            shutil.copytree(web, stage / "web")
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
            manifest = {"versions": VERSIONS, "sha256": {name: tree_hash(stage / name) for name in ("web", "autoloop")}}
            for name in ("web", "autoloop", "autoloop-data"):
                (stage / name).rename(root / name)
            atomic_write_text(root / "packages.json", json.dumps(manifest, indent=2))


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
        (root / "enabled").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
