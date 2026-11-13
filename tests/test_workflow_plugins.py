"""Local trust boundaries and the real pinned Autoloop protocol."""

import asyncio
import json
import os
import re
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import autoloop_plugin, daily_plugin, install_plugins
from app.install_plugins import provision
from app.llm import LLMConfig, OpenAICompatibleClient
from app.main import create_app
from app.plugins import DAILY_ORIGIN, WORKBENCH_ORIGIN, plugin_root
from app.plugin_packages import HUB_ENTRYPOINTS
from app.plugin_paths import HUB_URL
from app.process_supervisor import ProcessState, RunningService
from app.workflow_hub import AutoloopClient
from app.workflow import Workflow
from app.workflow_worker import answer_body


def make_workspace(root, *, live=False):
    class FixtureModel(OpenAICompatibleClient):
        def agent_candidate(self, instruction, material):
            self.calls.append(json.loads(material))
            if "等待停止" in self.calls[-1]["objective"]:
                time.sleep(1)
            if "超时" in self.calls[-1]["objective"]:
                raise httpx.ReadTimeout("synthetic")
            if "decision" in self.calls[-1]:
                return {"draft": "虚构产物：已按蓝色方案起草。"}
            return {"question": "选择颜色", "options": ["蓝色", "绿色"]}

    model = FixtureModel(LLMConfig("http://127.0.0.1:9999/v1", "", "synthetic"))
    model.calls = []
    app = create_app(data_root=root, enable_scheduler=False, enforce_security=True, llm_client=model)
    if not live:
        app.state.workflow = Workflow(root, app.state.model_gateway)
    return app, model


def csrf(client):
    client.get("/tasks")
    return {"X-CSRF-Token": client.cookies["pcw_csrf"], "Origin": WORKBENCH_ORIGIN}


def post_preview(client, headers, item, objective, previous="", choice=None, answer_text=""):
    data = {"objective": objective, "previous_id": previous, "answer_text": answer_text}
    if choice is not None:
        data["choice"] = choice
    response = client.post(f"{item}/preview", headers=headers, data=data)
    assert response.status_code == 200, response.text[:400]
    match = re.search(r'name="fingerprint" value="([a-f0-9]+)"', response.text)
    assert match
    return data | {"fingerprint": match[1]}


def until(fn, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := fn():
            return value
        time.sleep(.1)
    raise AssertionError("Timed out waiting for actual upstream state")


def test_handoff_requires_workspace_origin_and_approval(tmp_path):
    app, model = make_workspace(tmp_path)
    client = TestClient(app, base_url=WORKBENCH_ORIGIN)
    headers = csrf(client)
    task = {"id": "sample-task", "title": "虚构待办"}
    route = "/workflow/handoff"
    assert client.post(route, json=task).status_code == 403
    assert client.post(route, headers=headers | {"Origin": "http://localhost:8767"}, json=task).status_code == 403
    assert client.post(route, headers=headers, json=task | {"notes": "私有材料"}).status_code == 422
    url = client.post(route, headers=headers, json=task).json()["url"]
    assert client.post(route, headers=headers, json=task).json()["url"] == url
    assert client.get("/legacy/planner").status_code == 200
    assert client.get("/legacy/tasks").status_code == 200
    data = post_preview(client, headers, url, "写一段说明")
    assert client.post(f"{url}/approve", headers=headers, data=data | {"objective": "已被改动"}).status_code == 409
    assert not app.state.workflow.store.turns(url.rsplit("/", 1)[-1])
    assert client.post(f"{url}/approve", headers=headers, data=data, follow_redirects=False).status_code == 303
    assert client.post(f"{url}/approve", headers=headers, data=data).status_code == 409
    assert len(app.state.workflow.store.turns(url.rsplit("/", 1)[-1])) == 1
    assert not model.calls


def write_fixture_engine(engine):
    for name in HUB_ENTRYPOINTS:
        path = engine / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")


@pytest.mark.parametrize("broken", ["web", "autoloop", "harness"])
def test_plugin_startup_keeps_the_other_plugin_available(tmp_path, monkeypatch, broken):
    root = plugin_root(tmp_path)
    web = root / "web"
    bridge = web / "assets/bundled-plugins/yubai-workbench/plugin.js"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("// synthetic bridge")
    (web / "index.html").write_text("synthetic daily work")
    write_fixture_engine(root / "autoloop")
    engine = root / "autoloop/bin/agent-autoloop.ts"
    home = root / "autoloop-data"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({
        "url": HUB_URL, "hub": {"listen": HUB_URL.removeprefix("http://")},
        "owner": "test-owner",
    }))
    (home / "workbench-keys.json").write_text(json.dumps({
        "owner": "test-owner", "source": "test-source", "worker": "test-worker",
    }))
    (root / "packages.json").write_text(json.dumps({
        "versions": install_plugins.VERSIONS,
        "sha256": {name: install_plugins.tree_hash(root / name) for name in ("web", "autoloop")},
    }))
    (root / "enabled").touch()
    if broken == "harness":
        (root / "harness.json").write_text("[]")
    else:
        (bridge if broken == "web" else engine).write_text("corrupted after installation")

    started = []

    @asynccontextmanager
    async def spawn_fixture(command, *, health, **_kwargs):
        started.append("web" if "app.plugin_web" in command else "autoloop")
        yield RunningService(health, lambda: False, pid=1234)

    async def idle_worker(self):
        self.workflow.ready = True
        await asyncio.Future()

    async def ready(_):
        return True

    monkeypatch.setattr(autoloop_plugin, "child_process", spawn_fixture)
    monkeypatch.setattr(daily_plugin, "child_process", spawn_fixture)
    monkeypatch.setattr(daily_plugin, "daily_available", ready)
    monkeypatch.setattr(AutoloopClient, "healthy", ready)
    monkeypatch.setattr(autoloop_plugin.WorkflowWorker, "run", idle_worker)
    monkeypatch.setattr(autoloop_plugin.shutil, "which", lambda _: "/fixture/node")
    app = create_app(data_root=tmp_path, enable_scheduler=False)
    with TestClient(app, base_url=WORKBENCH_ORIGIN) as client:
        manager = app.state.plugin_runtime
        until(lambda: all(
            supervisor.snapshot.state in {ProcessState.READY, ProcessState.FAILED}
            for supervisor in manager.controls.values()
        ))
        daily_page = client.get("/")
        assert ('class="daily-frame"' in daily_page.text) is (broken != "web")
        assert (f"frame-src {DAILY_ORIGIN};" in daily_page.headers["content-security-policy"]) is (broken != "web")
        assert client.get("/legacy/planner").status_code == 200
        tasks = client.get("/tasks")
        if broken == "harness":
            assert tasks.status_code == 503 and "执行后端配置无效" in tasks.text
        else:
            assert tasks.status_code == 200
            assert app.state.workflow.autoloop.connected is (broken == "web")
        assert started == (["autoloop"] if broken == "web" else ["web"])


def prepare_real_hub(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    monkeypatch.setattr(autoloop_plugin, "HUB_URL", origin)
    monkeypatch.setattr(install_plugins, "HUB_URL", origin)

    @asynccontextmanager
    async def web_fixture(*_args, **_kwargs):
        async def unavailable():
            return False
        yield RunningService(unavailable, lambda: False)

    monkeypatch.setattr(daily_plugin, "child_process", web_fixture)
    provision(tmp_path, Path(os.environ["WORKBENCH_E2E_WEB"]), Path(os.environ["WORKBENCH_E2E_ENGINE"]))
    (plugin_root(tmp_path) / "enabled").touch()
    return origin


@pytest.mark.skipif(not os.getenv("WORKBENCH_E2E_WEB"), reason="requires pinned upstream packages")
def test_real_autoloop_decision_resume_restart_and_timeout(tmp_path, monkeypatch):
    prepare_real_hub(tmp_path, monkeypatch)
    app, model = make_workspace(tmp_path, live=True)
    with TestClient(app, base_url=WORKBENCH_ORIGIN) as client:
        workflow = app.state.workflow
        until(lambda: workflow.ready)
        headers = csrf(client)
        route = "/workflow/handoff"
        item = client.post(route, headers=headers, json={"id": "test-task", "title": "虚构待办"}).json()["url"]
        item_id = item.rsplit("/", 1)[-1]
        data = post_preview(client, headers, item, "起草说明")
        assert not model.calls
        assert client.post(f"{item}/approve", headers=headers, data=data).status_code == 200
        decision = until(lambda: "选择颜色" in client.get(item).text and workflow.store.turns(item_id)[0])
        until(lambda: "预览续跑" in client.get(item).text)
        assert len(model.calls) == 1
        control = client.get("/workflow/control/state").json()
        ask = next(card for card in control["cards"] if card["item"] == item_id and card["state"] == "open")
        assert client.post(f"/workflow/cards/{ask['id']}/answer", headers=headers, json={"text": "绕过预览"}).status_code == 409
        continued = post_preview(client, headers, item, "起草说明", decision["id"], answer_text="按蓝色方案处理")
        assert client.post(f"{item}/approve", headers=headers, data=continued | {"answer_text": "改动回答"}).status_code == 409
        assert client.post(f"{item}/approve", headers=headers, data=continued).status_code == 200
        draft = until(lambda: "验收此产物" in client.get(item).text and workflow.store.turns(item_id)[0])
        assert len(model.calls) == 2 and model.calls[-1]["decision"]["answer"] == "按蓝色方案处理"
        assert client.get(f"/workflow/runs/{draft['run']}").status_code == 200
        history = client.get(f"/workflow/control/runs/{decision['run']}").json()
        assert history["following"] == [draft["run"]]
        assert history["nativeFollowing"] == [draft["run"]]
        assert history["frames"] == sorted(history["frames"], key=lambda entry: entry["seq"])
        assert any(frame["run"] and frame["run"]["state"] == "done" for frame in history["frames"])
        matter = client.get("/workflow/control/matter", params={"item": item_id}).json()
        assert {run["id"] for run in matter["runs"]} == {draft["run"], decision["run"]}
        assert {step["runId"] for step in matter["history"] if step["kind"] == "receipt"} == {draft["run"], decision["run"]}
        assert client.get("/tasks/history").status_code == 200
        assert client.get("/tasks/rules").status_code == 200
        session = client.get(f"/tasks/sessions/{draft['run']}")
        assert "最终输出" in session.text and "未上报" in session.text
        assert workflow.store.answer_path(draft["id"]).stat().st_mode & 0o777 == 0o600
        assert answer_body(draft) == {"text": f"workbench-answer:{draft['id']}"}
        assert any(step["kind"] == "followup" and step["run"] == draft["run"] for step in history["timeline"])
        assert any(step["kind"] == "answer" and step["answer"] == "按蓝色方案处理" for step in history["timeline"])
        assert {step["kind"] for step in history["timeline"]} >= {"rule", "matter", "event", "claim", "start", "receipt"}
        assert not any(key in str(history) for key in json.loads((workflow.store.root / 'autoloop-data/workbench-keys.json').read_text()).values())
        assert "已验收" in client.post(f"{item}/accept", headers=headers, data={"turn_id": draft["id"]}).text
        assert "虚构产物" in client.get(f"{item}/artifacts/{draft['id']}").text
        hub = app.state.plugin_runtime.autoloop.hub
        original_pid = hub.snapshot.pid
        assert client.post("/settings/runtime/plugins/workflow/restart", headers=headers, follow_redirects=False).status_code == 303
        until(lambda: workflow.ready and hub.snapshot.pid != original_pid)
        assert len(model.calls) == 2
        assert "已验收" in client.get(item).text

        assert client.post("/workflow/rules/pause", headers=headers, data={"name": "工作台任务"}).status_code == 200
        assert client.get("/workflow/control/state").json()["lines"][0]["paused"]
        blocked = client.post("/workflow/rules/run", headers=headers | {"Accept": "application/json"}, data={"name": "工作台任务"})
        assert blocked.status_code == 409 and "暂停" in blocked.json()["detail"]
        assert client.post("/workflow/rules/resume", headers=headers, data={"name": "工作台任务"}).status_code == 200
        assert client.post("/workflow/rules/run", headers=headers, data={"name": "工作台任务"}).status_code == 200
        until(lambda: any(
            card["title"] == "待确认模型外发" for card in client.get("/workflow/control/state").json()["cards"]
        ))
        assert len(model.calls) == 2
        retry = post_preview(client, headers, item, "模拟超时", draft["id"])
        assert client.post(f"{item}/approve", headers=headers, data=retry).status_code == 200
        until(lambda: "预览并重试" in client.get(item).text)
        assert len(model.calls) == 3
        time.sleep(.6)
        assert len(model.calls) == 3
        cancelled_url = client.post(
            "/workflow/new", headers=headers, data={"title": "虚构停止测试"}, follow_redirects=False,
        ).headers["location"]
        cancelled_id = cancelled_url.rsplit("/", 1)[-1]
        slow = post_preview(client, headers, cancelled_url, "等待停止")
        assert client.post(f"{cancelled_url}/approve", headers=headers, data=slow).status_code == 200
        executing = until(lambda: (rows := workflow.store.turns(cancelled_id)) and rows[0]["run"] and rows[0])
        assert client.post(f"/workflow/runs/{executing['run']}/cancel", headers=headers).status_code == 200
        until(lambda: "已停止" in client.get(cancelled_url).text)
        assert "验收此产物" not in client.get(cancelled_url).text
    with TestClient(app, base_url=WORKBENCH_ORIGIN) as client:
        until(lambda: app.state.workflow.ready)
        assert "预览并重试" in client.get(item).text
        assert "已验收" in client.get(item).text
        assert len(model.calls) in (3, 4)
        assert "已停止" in client.get(cancelled_url).text


def test_refresh_web_preserves_installed_data_and_restores_previous_bundle(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    original = root / "web"
    new = tmp_path / "new"
    for bundle, label in ((original, "English"), (new, "简体中文")):
        bridge = bundle / "assets/bundled-plugins/yubai-workbench"
        bridge.mkdir(parents=True)
        (bridge / "plugin.js").write_text("// fixture")
        (bundle / "index.html").write_text(label)
    engine = root / "autoloop"
    write_fixture_engine(engine)
    data = root / "autoloop-data"
    data.mkdir()
    (data / "test.txt").write_text("persisted")
    (root / "packages.json").write_text(json.dumps({
        "versions": install_plugins.VERSIONS,
        "sha256": {name: install_plugins.tree_hash(root / name) for name in ("web", "autoloop")},
    }))

    def fail(*args):
        raise OSError("synthetic failure")

    with monkeypatch.context() as patch:
        patch.setattr(install_plugins, "atomic_write_text", fail)
        with pytest.raises(OSError, match="synthetic failure"):
            install_plugins.refresh_web(root, new)
    install_plugins.verify_packages(root)
    assert (original / "index.html").read_text() == "English"

    install_plugins.refresh_web(root, new)
    install_plugins.verify_packages(root)
    assert (original / "index.html").read_text() == "简体中文"
    assert (data / "test.txt").read_text() == "persisted"
