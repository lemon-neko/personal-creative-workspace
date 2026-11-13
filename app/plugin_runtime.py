"""Launch and supervise the desktop plugin processes."""

from __future__ import annotations

import asyncio
import fcntl
import json
import shutil
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx

from app.install_plugins import require_web_package, verify_packages
from app.plugins import DAILY_ORIGIN, WORKBENCH_ORIGIN
from app.workflow import Workflow
from app.workflow_hub import HUB_URL, plugin_environment
from app.workflow_worker import WorkflowWorker


async def supervise(command, *, env=None):
    while True:
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
        except OSError:
            pass
        finally:
            if process and process.returncode is None:
                with suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=4)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        await asyncio.sleep(2)


@asynccontextmanager
async def run_plugin_tasks(*coroutines):
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def start_daily_web(root: Path):
    try:
        await asyncio.to_thread(verify_packages, root, package="web")
        require_web_package(root / "web")
    except (KeyError, OSError, TypeError, ValueError):
        yield False
        return
    async with run_plugin_tasks(supervise([sys.executable, "-m", "app.plugin_web", str(root / "web")])):
        yield True


@asynccontextmanager
async def start_workflow(workflow: Workflow | None):
    if workflow is None:
        yield
        return
    root = workflow.store.root
    home = root / "autoloop-data"
    node = shutil.which("node")
    try:
        await asyncio.to_thread(verify_packages, root, package="autoloop")
        config = json.loads((home / "config.json").read_text())
        credentials = json.loads((home / "workbench-keys.json").read_text())
        if config != {"url": HUB_URL, "hub": {"listen": HUB_URL.removeprefix("http://")}, "owner": credentials["owner"]}:
            raise ValueError("插件须使用专用本机配置")
        if not all(isinstance(credentials.get(role), str) and credentials[role] for role in ("owner", "source", "worker")):
            raise ValueError("插件凭据缺失")
        if not node or not (root / "autoloop/bin/agent-autoloop.ts").is_file():
            raise ValueError("插件文件缺失")
    except (KeyError, OSError, TypeError, ValueError):
        workflow.error = "Autoloop 安装或配置无效，请检查本机插件"
        yield
        return
    workflow.store.recover_interrupted_turns()
    try:
        async with workflow.autoloop.connect(HUB_URL, credentials), run_plugin_tasks(
            supervise([node, str(root / "autoloop/bin/agent-autoloop.ts"), "up"], env=plugin_environment(home)),
            WorkflowWorker(workflow).run(),
        ):
            yield
    finally:
        workflow.ready = False


@asynccontextmanager
async def start_plugins(root: Path | None, workflow: Workflow | None):
    if root is None:
        yield False
        return
    with (root / "worker.lock").open("a") as lock:
        (root / "worker.lock").chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if workflow is not None:
                workflow.error = "插件已由另一工作台进程启动"
            yield False
            return
        async with start_daily_web(root) as daily_verified, start_workflow(workflow):
            yield daily_verified


async def daily_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1, trust_env=False) as http:
            response = await http.head(DAILY_ORIGIN)
        return response.status_code == 200 and f"frame-ancestors {WORKBENCH_ORIGIN}" in response.headers.get("content-security-policy", "")
    except httpx.HTTPError:
        return False
