"""Own the exclusive desktop plugin lifecycle and operator controls."""

import asyncio
import fcntl
import os
import stat
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from app.autoloop_plugin import Autoloop
from app.daily_plugin import DailyWeb
from app.process_logs import ProcessLogs
from app.process_supervisor import ProcessState, ProcessSupervisor
from app.workflow import Workflow


class PluginRuntimeManager:
    def __init__(self, root: Path, workflow: Workflow | None):
        self.root = root
        self.workflow = workflow
        self.web_logs = ProcessLogs(root / "logs", "super-productivity")
        self.hub_logs = ProcessLogs(root / "logs", "autoloop-hub")
        self.daily = DailyWeb(root, self.web_logs)
        self.web = ProcessSupervisor("super-productivity", self.daily.launch)
        self.autoloop = Autoloop(root, self.hub_logs, workflow)
        self.controls = {"daily": self.web, "workflow": self.autoloop.hub}
        self._control = asyncio.Lock()
        self._owns_lock = False

    @property
    def daily_ready(self) -> bool:
        return self.web.snapshot.state == ProcessState.READY

    async def daily_available(self) -> bool:
        return self.daily_ready and await self.daily.available() and self.daily_ready

    @property
    def can_control(self) -> bool:
        return self._owns_lock

    def snapshots(self):
        return (
            ("Super Productivity", "daily", self.web.snapshot, self.web_logs),
            ("Autoloop Hub", "workflow", self.autoloop.hub.snapshot, self.hub_logs),
            ("Autoloop Worker", "", self.autoloop.worker.snapshot, None),
        )

    def _lock(self, resources: AsyncExitStack) -> None:
        if self.root.is_symlink() or self.root.parent.is_symlink():
            raise OSError("插件目录无效")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        fd = os.open(self.root / "worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        resources.callback(os.close, fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("插件锁文件无效")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fchmod(fd, 0o600)
        self._owns_lock = True

    def _unavailable(self, error: str) -> None:
        for supervisor in self.controls.values():
            supervisor.unavailable(error)
        if self.workflow is not None:
            self.workflow.error = error

    @asynccontextmanager
    async def running(self, *, enabled: bool):
        async with AsyncExitStack() as resources:
            if enabled:
                try:
                    self._lock(resources)
                except BlockingIOError:
                    self._unavailable("插件已由另一工作台进程管理")
                except OSError:
                    self._unavailable("无法获取本机插件运行锁")
                if self._owns_lock:
                    resources.push_async_callback(self.shutdown)
                    await self.web.start()
                    await self.autoloop.hub.start()
            yield self

    async def shutdown(self) -> None:
        async with self._control:
            self._owns_lock = False
            try:
                await self.autoloop.hub.stop()
            finally:
                await self.web.stop()

    async def control(self, plugin_id: str, action: str) -> None:
        supervisor = self.controls[plugin_id]
        if action not in {"start", "stop", "restart"}:
            raise KeyError(action)
        async with self._control:
            if not self._owns_lock:
                raise RuntimeError("本机插件未启用或运行锁不可用")
            if action in {"stop", "restart"}:
                await supervisor.stop()
            if action in {"start", "restart"}:
                await supervisor.start()
