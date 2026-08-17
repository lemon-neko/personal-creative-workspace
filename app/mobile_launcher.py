"""Fail-closed launcher for the private Tailscale mobile gateway."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import uvicorn

from app.mobile import MobileStore
from app.privacy import default_data_root, prepare_private_root


TAILSCALE_APP_CLI = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def tailscale_cli() -> str:
    discovered = shutil.which("tailscale")
    if discovered:
        return discovered
    if TAILSCALE_APP_CLI.is_file():
        return str(TAILSCALE_APP_CLI)
    raise RuntimeError("未找到 Tailscale CLI；请先安装并登录 Tailscale")


def _json_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"命令执行失败：{' '.join(command)}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Tailscale 返回了无法识别的状态") from error
    if not isinstance(value, dict):
        raise RuntimeError("Tailscale 状态格式无效")
    return value


def _contains_value(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(
            needle in str(key) or _contains_value(item, needle)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_value(item, needle) for item in value)
    return needle in str(value)


def _funnel_enabled(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if "funnel" in str(key).casefold() and item not in (False, None, {}, []):
                return True
            if _funnel_enabled(item):
                return True
    elif isinstance(value, list):
        return any(_funnel_enabled(item) for item in value)
    return False


def validate_mobile_environment(store: MobileStore) -> tuple[str, str]:
    config = store.config()
    if not config.enabled or not config.tailnet_host:
        raise RuntimeError("请先在桌面工作台的“设置 → 手机同步”启用移动网关")
    cli = tailscale_cli()
    status = _json_command([cli, "status", "--json"])
    if str(status.get("BackendState", "")).casefold() != "running":
        raise RuntimeError("Tailscale 尚未连接，请先完成登录")
    serve = _json_command([cli, "serve", "status", "--json"])
    if _funnel_enabled(serve):
        raise RuntimeError("检测到 Tailscale Funnel；请先关闭公网 Funnel")
    if not _contains_value(serve, "127.0.0.1:8766"):
        raise RuntimeError(
            "Tailscale Serve 尚未指向移动网关；请执行：\n"
            f"  {cli} serve --bg http://127.0.0.1:8766"
        )
    if not _contains_value(serve, config.tailnet_host):
        raise RuntimeError("Serve HTTPS 主机与工作台配置不一致")
    return cli, config.base_url


def main() -> None:
    os.umask(0o077)
    data_root = prepare_private_root(default_data_root())
    store = MobileStore(data_root)
    try:
        _, address = validate_mobile_environment(store)
    except RuntimeError as error:
        print(f"手机同步未启动：{error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(f"羽白工作台已通过私人 Tailnet 提供：{address}")
    uvicorn.run(
        "app.mobile_main:app",
        host="127.0.0.1",
        port=8766,
        reload=False,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
