import asyncio
import stat
from contextlib import asynccontextmanager

import httpx
from fastapi.testclient import TestClient

from app import autoloop_plugin, daily_plugin
from app.main import create_app
from app.plugin_paths import DAILY_ORIGIN, WORKBENCH_ORIGIN
from app.plugin_runtime import PluginRuntimeManager
from app.plugin_web import web_app
from app.process_supervisor import ProcessState, RecoveryPolicy, RunningService
from tests.test_process_supervisor import eventually
from tests.test_workflow_plugins import csrf


FAST = RecoveryPolicy(startup_timeout=.2, probe_interval=.005, initial_delay=.01)


def test_worker_restart_and_hub_recovery_are_isolated_and_release_lock(tmp_path, monkeypatch):
    async def scenario():
        application = create_app(data_root=tmp_path)
        from app.workflow import Workflow

        workflow = Workflow(tmp_path, application.state.model_gateway)
        workflow.error = ""
        root = application.state.plugin_directory
        events = []
        worker_count = 0
        hub_count = 0
        fail_worker = asyncio.Event()
        fail_hub = False

        async def hub_health():
            return not fail_hub

        async def web_health(_):
            return True

        @asynccontextmanager
        async def connect(*_args):
            events.append("client opened")
            try:
                yield
            finally:
                events.append("client closed")

        @asynccontextmanager
        async def child(command, *, health, **_kwargs):
            nonlocal hub_count
            label = "web" if "app.plugin_web" in command else "hub"
            if label == "hub":
                hub_count += 1
            events.append(f"{label} started")
            try:
                yield RunningService(health, lambda: False, pid=99)
            finally:
                events.append(f"{label} stopped")

        async def worker(self):
            nonlocal worker_count
            worker_count += 1
            events.append("worker started")
            self.workflow.ready = True
            try:
                if worker_count == 1:
                    await fail_worker.wait()
                    raise KeyError("synthetic unexpected failure")
                await asyncio.Future()
            finally:
                events.append("worker stopped")

        monkeypatch.setattr(daily_plugin, "verify_packages", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(daily_plugin, "child_process", child)
        monkeypatch.setattr(daily_plugin, "daily_available", web_health)
        monkeypatch.setattr(autoloop_plugin, "child_process", child)
        monkeypatch.setattr(autoloop_plugin.Autoloop, "_configuration", lambda _: ("node", root, {}))
        monkeypatch.setattr(autoloop_plugin.WorkflowWorker, "run", worker)
        monkeypatch.setattr(workflow.autoloop, "healthy", hub_health)
        monkeypatch.setattr(workflow.autoloop, "connect", connect)

        manager = PluginRuntimeManager(root, workflow)
        for unit in (manager.web, manager.autoloop.hub, manager.autoloop.worker):
            unit.policy = FAST
        async with manager.running(enabled=True):
            await eventually(lambda: all(row[2].state == ProcessState.READY for row in manager.snapshots()))
            assert manager.can_control and await manager.daily_available()
            assert stat.S_IMODE((root / "worker.lock").stat().st_mode) == 0o600
            contender = PluginRuntimeManager(root, None)
            async with contender.running(enabled=True):
                assert not contender.can_control
                assert "另一工作台" in contender.web.snapshot.last_error
            await manager.control("workflow", "start")
            assert worker_count == hub_count == 1
            fail_worker.set()
            await eventually(lambda: worker_count == 2 and manager.autoloop.worker.snapshot.state == ProcessState.READY)
            assert manager.autoloop.worker.snapshot.restart_count == 1
            assert manager.autoloop.hub.snapshot.restart_count == 0
            assert manager.daily_ready and events.count("web started") == 1
            fail_hub = True
            await eventually(lambda: manager.autoloop.hub.snapshot.state == ProcessState.DEGRADED)
            await eventually(lambda: "hub stopped" in events)
            assert manager.daily_ready and not workflow.ready
            fail_hub = False
            await eventually(lambda: hub_count == 2 and worker_count == 3 and workflow.ready)
            assert manager.daily_ready
        assert events[-4:] == ["worker stopped", "client closed", "hub stopped", "web stopped"]
        assert not manager.can_control
        async with contender.running(enabled=True):
            assert contender.can_control

    asyncio.run(scenario())


def test_runtime_controls_require_same_origin_csrf_and_allow_only_fixed_operations(tmp_path, monkeypatch):
    root = create_app(data_root=tmp_path).state.plugin_directory
    root.mkdir(exist_ok=True)
    (root / "enabled").touch()
    monkeypatch.setattr(daily_plugin, "verify_packages", lambda *_args, **_kwargs: None)

    @asynccontextmanager
    async def launch(command, *, health, **_kwargs):
        yield RunningService(health, lambda: False, pid=42)

    async def web_health(_):
        return True

    monkeypatch.setattr(daily_plugin, "child_process", launch)
    monkeypatch.setattr(daily_plugin, "daily_available", web_health)
    app = create_app(data_root=tmp_path, enable_scheduler=False)
    with TestClient(app, base_url=WORKBENCH_ORIGIN) as client:
        headers = csrf(client)
        path = "/settings/runtime/plugins/daily/stop"
        assert client.post(path).status_code == 403
        assert client.post(path, headers=headers | {"Origin": DAILY_ORIGIN}).status_code == 403
        assert client.post("/settings/runtime/plugins/daily/echo", headers=headers).status_code == 404
        assert client.post("/settings/runtime/plugins/unknown/stop", headers=headers).status_code == 404
        assert client.post(path, headers=headers, follow_redirects=False).status_code == 303
        assert app.state.plugin_runtime.web.snapshot.state == ProcessState.STOPPED
        page = client.get("/settings/runtime")
        assert all(name in page.text for name in ("Super Productivity", "Autoloop Hub", "Autoloop Worker", "Stopped"))
        assert 'class="daily-frame"' not in client.get("/").text
        assert client.post(path.replace("/stop", "/start"), headers=headers, follow_redirects=False).status_code == 303


def test_web_probe_rejects_impersonator_even_with_correct_csp(tmp_path, monkeypatch):
    async def scenario():
        (tmp_path / "index.html").write_text("synthetic index")
        real = web_app(tmp_path, health_secret="real-secret")
        wrong = web_app(tmp_path, health_secret="wrong-secret")
        client = httpx.AsyncClient

        for app, expected in ((real, True), (wrong, False)):
            monkeypatch.setattr(daily_plugin.httpx, "AsyncClient", lambda **kw: client(
                transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 3000)), **kw,
            ))
            assert await daily_plugin.daily_available("real-secret") is expected
        async with client(transport=httpx.ASGITransport(app=real), base_url=DAILY_ORIGIN) as web:
            response = await web.get("/")
            assert response.status_code == 200
            assert "frame-ancestors http://127.0.0.1:8765;" in response.headers["content-security-policy"]
            assert daily_plugin.PROOF not in response.headers

    asyncio.run(scenario())
