"""Supervise local child processes and managed coroutines with bounded recovery."""

from __future__ import annotations

import asyncio
import os
import signal
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.process_logs import ProcessLogs


class ProcessState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    FAILED = "failed"


def timestamp(delay: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")


@dataclass
class ProcessSnapshot:
    name: str
    state: ProcessState = ProcessState.STOPPED
    pid: int | None = None
    restart_count: int = 0
    started_at: str = ""
    last_exit_code: int | None = None
    last_error: str = ""
    last_health_check_at: str = ""
    last_health_ok: bool | None = None
    next_restart_at: str | None = None
    desired_state: str = "stopped"


@dataclass(frozen=True)
class RecoveryPolicy:
    startup_timeout: float = 15
    probe_interval: float = 1
    probe_timeout: float = 5
    failure_limit: int = 3
    initial_delay: float = 1
    max_delay: float = 30
    budget: int = 5
    window: float = 300


@dataclass(frozen=True)
class RunningService:
    health: Callable[[], Awaitable[bool]]
    exited: Callable[[], bool]
    exit_code: Callable[[], int | None] = lambda: None
    pid: int | None = None


class SetupError(RuntimeError):
    """A static configuration issue that requires an operator to intervene."""


class ProcessSupervisor:
    def __init__(
        self, name: str, launch: Callable[[], AbstractAsyncContextManager[RunningService]], *,
        policy: RecoveryPolicy = RecoveryPolicy(),
    ):
        self._snapshot = ProcessSnapshot(name)
        self.launch = launch
        self.policy = policy
        self._task: asyncio.Task | None = None
        self._operation = asyncio.Lock()

    @property
    def snapshot(self) -> ProcessSnapshot:
        return replace(self._snapshot)

    def unavailable(self, message: str) -> None:
        self._snapshot.state = ProcessState.FAILED
        self._snapshot.last_error = message

    async def start(self) -> None:
        async with self._operation:
            if self._task is not None and not self._task.done():
                return
            self._snapshot = ProcessSnapshot(self._snapshot.name, ProcessState.STARTING, desired_state="running")
            self._task = asyncio.create_task(self._supervise(), name=f"supervise:{self._snapshot.name}")

    async def stop(self) -> None:
        async with self._operation:
            self._snapshot.desired_state = "stopped"
            self._snapshot.next_restart_at = None
            if self._task is not None:
                self._task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._task
                self._task = None
            self._snapshot.state = ProcessState.STOPPED

    async def _supervise(self) -> None:
        loop = asyncio.get_running_loop()
        restarts: deque[float] = deque()
        state = self._snapshot
        while state.desired_state == "running":
            state.state = ProcessState.STARTING
            state.next_restart_at = None
            service = None
            try:
                async with self.launch() as service:
                    state.pid = service.pid
                    state.started_at = timestamp()
                    state.last_error = await self._monitor(service)
                    state.state = ProcessState.DEGRADED
            except SetupError as error:
                self.unavailable(str(error))  # Adapters supply fixed diagnostics.
                return
            except OSError:
                state.last_error = "无法启动或回收服务"
            except Exception:
                state.last_error = "服务启动或监督异常"
            finally:
                if service is not None:
                    state.last_exit_code = service.exit_code()
                state.pid = None
            now = loop.time()
            while restarts and now - restarts[0] >= self.policy.window:
                restarts.popleft()
            state.restart_count = len(restarts)
            if state.desired_state == "stopped":
                break
            if len(restarts) >= self.policy.budget:
                self.unavailable(f"{state.last_error}，已用完自动恢复次数")
                return
            delay = min(self.policy.initial_delay * 2 ** len(restarts), self.policy.max_delay)
            state.state = ProcessState.DEGRADED
            state.next_restart_at = timestamp(delay)
            await asyncio.sleep(delay)
            restarts.append(loop.time())
            state.restart_count = len(restarts)

    async def _monitor(self, service: RunningService) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.policy.startup_timeout
        state = self._snapshot
        ready = False
        failures = 0
        while not service.exited():
            remaining = deadline - loop.time() if not ready else self.policy.probe_timeout
            if remaining <= 0:
                return "启动健康检查超时"
            try:
                healthy = await asyncio.wait_for(service.health(), min(remaining, self.policy.probe_timeout))
            except Exception:
                healthy = False
            if service.exited():
                break
            now = loop.time()
            state.last_health_check_at = timestamp()
            state.last_health_ok = healthy
            if healthy:
                state.state = ProcessState.READY
                ready = True
                failures = 0
            elif ready:
                failures += 1
                state.state = ProcessState.DEGRADED
                state.last_error = "健康检查失败"
                if failures >= self.policy.failure_limit:
                    return "健康检查持续失败"
            remaining = deadline - now if not ready else self.policy.probe_interval
            await asyncio.sleep(max(0, min(self.policy.probe_interval, remaining)))
        return "服务意外退出"


async def finish_cleanup(cleanup: Awaitable[None]) -> None:
    task = asyncio.ensure_future(cleanup)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # Complete group cleanup before releasing the runtime lock.
        await asyncio.shield(task)
        raise


def process_environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG", "LC_ALL") if key in os.environ}


def _signal_group(pid: int, signum: signal.Signals) -> bool:
    try:
        os.killpg(pid, signum)
        return True
    except ProcessLookupError:
        return False


async def _terminate(process: asyncio.subprocess.Process, timeout: float) -> None:
    _signal_group(process.pid, signal.SIGTERM)
    deadline = asyncio.get_running_loop().time() + timeout
    while _signal_group(process.pid, 0):
        if asyncio.get_running_loop().time() >= deadline:
            _signal_group(process.pid, signal.SIGKILL)
            break
        await asyncio.sleep(0.05)
    await process.wait()


@asynccontextmanager
async def child_process(
    command: tuple[str, ...], *, env: dict[str, str], logs: ProcessLogs, health: Callable[[], Awaitable[bool]],
    stop_timeout: float = 5,
):
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *command, env=env, start_new_session=True,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    ))
    process = None
    readers = []
    try:
        process = await asyncio.shield(spawn)
        readers = [
            asyncio.create_task(logs.capture(stream, source))
            for stream, source in ((process.stdout, "stdout"), (process.stderr, "stderr"))
        ]
        yield RunningService(health, lambda: process.returncode is not None, lambda: process.returncode, process.pid)
    finally:
        if process is None and not spawn.cancelled():
            with suppress(OSError):
                process = await spawn
        if process is not None:
            async def cleanup():
                try:
                    await _terminate(process, stop_timeout)
                finally:
                    try:
                        await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True), timeout=1)
                    except TimeoutError:
                        pass

            await finish_cleanup(cleanup())
