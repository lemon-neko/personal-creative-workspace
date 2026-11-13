"""Configure the pinned local Autoloop Hub and supervise its in-process Worker."""

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from app.plugin_packages import HUB_ENTRYPOINT, verify_packages
from app.plugin_paths import HUB_URL
from app.process_logs import ProcessLogs
from app.process_supervisor import ProcessSupervisor, RecoveryPolicy, RunningService, SetupError, child_process, finish_cleanup
from app.workflow import Workflow
from app.workflow_hub import plugin_environment
from app.workflow_worker import WorkflowWorker


class Autoloop:
    def __init__(self, root: Path, logs: ProcessLogs, workflow: Workflow | None):
        self.root = root
        self.logs = logs
        self.workflow = workflow
        self.worker = ProcessSupervisor("autoloop-worker", self._launch_worker, policy=RecoveryPolicy(failure_limit=5))
        self.hub = ProcessSupervisor("autoloop-hub", self._launch_hub, policy=RecoveryPolicy(startup_timeout=30))

    def _configuration(self) -> tuple[str, Path, dict[str, str]]:
        try:
            verify_packages(self.root, package="autoloop")
        except (OSError, ValueError) as error:
            detail = str(error) if isinstance(error, ValueError) else "无法读取 Autoloop 包"
            raise SetupError(detail) from error
        if self.workflow is None:
            raise SetupError("Autoloop 执行后端配置无效")
        home = self.root / "autoloop-data"
        config_file, key_file = home / "config.json", home / "workbench-keys.json"
        if home.is_symlink() or any(path.is_symlink() or not path.is_file() for path in (config_file, key_file)):
            raise SetupError("Autoloop 专用配置或凭据路径无效")
        try:
            config = json.loads(config_file.read_text())
            keys = json.loads(key_file.read_text())
        except (OSError, ValueError) as error:
            raise SetupError("Autoloop 专用配置或凭据无效") from error
        if not isinstance(keys, dict) or not all(
            isinstance(keys.get(role), str) and keys[role] for role in ("owner", "source", "worker")
        ):
            raise SetupError("Autoloop 凭据无效")
        if config != {"url": HUB_URL, "hub": {"listen": HUB_URL.removeprefix("http://")}, "owner": keys["owner"]}:
            raise SetupError("Autoloop 须使用专用回环配置")
        node = shutil.which("node")
        if not node:
            raise SetupError("未找到 Autoloop 所需的 Node.js")
        return node, home, keys

    @asynccontextmanager
    async def _launch_hub(self):
        try:
            node, home, keys = await asyncio.to_thread(self._configuration)
        except SetupError:
            if self.workflow is not None:
                self.workflow.error = "Autoloop 安装或配置无效，请检查本机插件"
            raise
        workflow = self.workflow
        assert workflow is not None
        worker_started = False

        async def health():
            nonlocal worker_started
            healthy = await workflow.autoloop.healthy()
            if healthy and not worker_started:
                await self.worker.start()
                worker_started = True
            return healthy

        command = (node, str(self.root / "autoloop" / HUB_ENTRYPOINT), "up")
        async with child_process(command, env=plugin_environment(home), logs=self.logs, health=health) as service:
            async with workflow.autoloop.connect(HUB_URL, keys):
                try:
                    yield service
                finally:
                    await finish_cleanup(self.worker.stop())
                    workflow.ready = False
                    workflow.error = "Autoloop 暂不可用，等待重连"

    @asynccontextmanager
    async def _launch_worker(self):
        workflow = self.workflow
        assert workflow is not None
        workflow.ready = False
        workflow.error = "正在连接 Autoloop Worker"
        workflow.store.recover_interrupted_turns()
        task = asyncio.create_task(WorkflowWorker(workflow).run(), name="autoloop-worker")

        async def health():
            return workflow.ready

        try:
            yield RunningService(health, task.done)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            workflow.ready = False
            workflow.error = "Autoloop Worker 暂不可用"
