import asyncio
import os
import signal
import stat
import sys
from contextlib import asynccontextmanager

import pytest

from app import process_logs, process_supervisor
from app.process_logs import ProcessLogs
from app.process_supervisor import (
    ProcessState, ProcessSupervisor, RecoveryPolicy, RunningService, child_process, process_environment,
)


async def eventually(check, timeout=3):
    async def poll():
        while not check():
            await asyncio.sleep(.005)
    await asyncio.wait_for(poll(), timeout)


@pytest.mark.parametrize("failure", ["spawn", "exit", "timeout", "health"])
def test_bounded_recovery_and_manual_stop(failure):
    async def scenario():
        launches = []
        active = []
        healthy = True
        loop = asyncio.get_running_loop()

        async def probe():
            return failure != "timeout" and healthy

        @asynccontextmanager
        async def launch():
            launches.append(loop.time())
            if failure == "spawn":
                raise OSError("SECRET should not appear")
            active.append(True)
            try:
                yield RunningService(probe, lambda: failure == "exit", lambda: 9 if failure == "exit" else None, 42)
            finally:
                active.pop()

        supervisor = ProcessSupervisor("fixture", launch, policy=RecoveryPolicy(
            startup_timeout=.03, probe_interval=.005, failure_limit=2,
            initial_delay=.02, max_delay=.04, budget=2,
        ))
        await supervisor.start()
        if failure == "health":
            await eventually(lambda: supervisor.snapshot.state == ProcessState.READY)
            healthy = False
            await eventually(lambda: supervisor.snapshot.state == ProcessState.DEGRADED)
            assert supervisor.snapshot.last_health_ok is False
        await eventually(lambda: supervisor.snapshot.state == ProcessState.FAILED)
        failed = supervisor.snapshot
        assert failed.restart_count == 2 and len(launches) == 3 and not active
        assert launches[1] - launches[0] >= .019 and launches[2] - launches[1] >= .039
        assert "SECRET" not in failed.last_error
        assert failed.last_exit_code == (9 if failure == "exit" else None)
        await supervisor.stop()
        await supervisor.stop()
        assert supervisor.snapshot.desired_state == "stopped"
        await asyncio.sleep(.06)
        assert len(launches) == 3

    asyncio.run(scenario())


def test_stop_cancels_scheduled_restart():
    async def scenario():
        launches = []

        @asynccontextmanager
        async def launch():
            launches.append(True)
            raise OSError
            yield

        supervisor = ProcessSupervisor("fixture", launch, policy=RecoveryPolicy(initial_delay=.1))
        await supervisor.start()
        await eventually(lambda: supervisor.snapshot.next_restart_at)
        await supervisor.stop()
        await asyncio.sleep(.12)
        assert launches == [True]
        assert supervisor.snapshot.state == ProcessState.STOPPED

    asyncio.run(scenario())


def test_process_group_is_signalled_and_pipes_are_drained(tmp_path, monkeypatch):
    async def scenario():
        logs = ProcessLogs(tmp_path / "logs", "fixture")
        sent = []
        original = process_supervisor._signal_group

        def track(pid, sig):
            sent.append((pid, sig))
            return original(pid, sig)

        monkeypatch.setattr(process_supervisor, "_signal_group", track)
        monkeypatch.setenv("LLM_API_KEY", "synthetic-secret")
        env = process_environment()
        assert "LLM_API_KEY" not in env

        async def health():
            return True

        code = (
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "print('INFO: Shutting down',flush=True); "
            "print('Authorization: Bearer synthetic-secret',file=__import__('sys').stderr,flush=True); "
            "print('x'*9000,flush=True); time.sleep(60)"
        )
        async with child_process((sys.executable, "-u", "-c", code), env=env, logs=logs, health=health,
                                 stop_timeout=.05) as child:
            await eventually(lambda: "超长输出" in logs.tail() and "[stderr]" in logs.tail())
            assert os.getpgid(child.pid) == child.pid
        assert (child.pid, signal.SIGTERM) in sent and (child.pid, signal.SIGKILL) in sent
        assert child.exited()
        assert "synthetic-secret" not in logs.path.read_text()
        assert "[stdout]" in logs.tail() and "INFO: Shutting down" in logs.tail()
        assert stat.S_IMODE(logs.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(logs.root.stat().st_mode) == 0o700

    asyncio.run(scenario())


def test_log_rotation_keeps_one_previous_file_and_rechecks_display(tmp_path, monkeypatch):
    monkeypatch.setattr(process_logs, "MAX_FILE", 100)
    logs = ProcessLogs(tmp_path / "logs", "fixture")
    for _ in range(3):
        logs._append(b"2026-01-01T00:00:00+00:00 [stderr] password=fixture-private\n")
    assert sorted(p.name for p in logs.root.iterdir()) == ["fixture.log", "fixture.log.1"]
    assert all(path.stat().st_size <= 100 for path in logs.root.iterdir())
    assert "fixture-private" not in logs.tail()
