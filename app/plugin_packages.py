"""Validate the fixed upstream packages before installation or execution."""

import hashlib
import json
import re
from pathlib import Path

from app.plugins import get_plugin

AUTOLOOP_COMMIT = "e8748fd0c2aad4013e5996c3188535567070f24a"
VERSIONS = {"super-productivity": get_plugin("daily").version, "agent-autoloop": get_plugin("workflow").version}
PACKAGE_VERSIONS = {"web": "super-productivity", "autoloop": "agent-autoloop"}
WEB_ENTRYPOINTS = ("index.html", "assets/bundled-plugins/yubai-workbench/plugin.js")
HUB_ENTRYPOINT = "bin/agent-autoloop.ts"
HUB_ENTRYPOINTS = (HUB_ENTRYPOINT, "package.json", "cli/main.ts", "host/up.ts")


def tree_hash(directory: Path) -> str:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("插件包目录无效")
    digest = hashlib.sha256()
    for entry in sorted(directory.rglob("*")):
        if entry.is_symlink():
            raise ValueError("插件构建不允许符号链接")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError("插件包包含不支持的文件类型")
        content = hashlib.sha256()
        with entry.open("rb") as stream:
            for block in iter(lambda: stream.read(128 * 1024), b""):
                content.update(block)
        digest.update(str(entry.relative_to(directory)).encode() + b"\0" + content.digest())
    return digest.hexdigest()


def read_manifest(root: Path) -> dict:
    path = root / "packages.json"
    if root.is_symlink() or root.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("插件清单缺失或路径无效")
    try:
        with path.open("rb") as stream:
            data = stream.read(8193)
        if len(data) > 8192:
            raise ValueError("插件清单过长")
        manifest = json.loads(data)
    except (UnicodeError, ValueError) as error:
        raise ValueError("插件清单不是有效 JSON") from error
    if not isinstance(manifest, dict) or set(manifest) != {"versions", "sha256"} or not all(
        isinstance(section, dict) for section in manifest.values()
    ):
        raise ValueError("插件清单结构无效")
    return manifest


def require_entries(package: Path, entries: tuple[str, ...]) -> None:
    if package.is_symlink() or not package.is_dir():
        raise ValueError("插件包目录无效")
    for entry in entries:
        current = package
        for part in Path(entry).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("插件入口不允许符号链接")
        if not current.is_file():
            raise ValueError("插件包缺少必要入口")


def require_web_package(web: Path) -> None:
    require_entries(web, WEB_ENTRYPOINTS)


def verify_packages(root: Path, *, package: str | None = None) -> None:
    manifest = read_manifest(root)
    versions, hashes = manifest["versions"], manifest["sha256"]
    names = (package,) if package is not None else tuple(PACKAGE_VERSIONS)
    if package is None and (set(versions) != set(VERSIONS) or set(hashes) != set(PACKAGE_VERSIONS)):
        raise ValueError("插件清单的版本或校验值字段无效")
    for name in names:
        if name not in PACKAGE_VERSIONS:
            raise ValueError("未知插件包")
        upstream = PACKAGE_VERSIONS[name]
        if versions.get(upstream) != VERSIONS[upstream]:
            raise ValueError("本地插件包版本不符")
        expected = hashes.get(name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("插件清单的 SHA-256 字段无效")
        require_entries(root / name, WEB_ENTRYPOINTS if name == "web" else HUB_ENTRYPOINTS)
        if tree_hash(root / name) != expected:
            raise ValueError("本地插件包 SHA-256 校验不符")
