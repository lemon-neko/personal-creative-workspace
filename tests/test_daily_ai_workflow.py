from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.agent_core import AgentCoreRepository
from app.llm import LLMConfig, OpenAICompatibleClient
from app.main import create_app
from app.workspace import SHANGHAI


def _fingerprint(response):
    return re.search(r'name="preview_fingerprint" value="([a-f0-9]+)"', response.text)[1]


def test_daily_event_model_decision_resume_and_acceptance(tmp_path, monkeypatch):
    responses = iter((
        {"question": "用哪种形式？", "options": ["清单", "短文"]},
        {"draft": "## 验收清单\n\n- 核对虚构示例"},
    ))
    sent = []
    model = OpenAICompatibleClient(LLMConfig("http://127.0.0.1:9999/v1", "", "test-model"))

    def fake_chat(system, user, **_):
        sent.append((system, json.loads(user)))
        return json.dumps(next(responses), ensure_ascii=False)

    monkeypatch.setattr(model, "_chat", fake_chat)
    app = create_app(data_root=tmp_path, llm_client=model)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    home = client.get("/")
    token = re.search(r'name="csrf-token" content="([^"]+)"', home.text)[1]

    def post(path, **fields):
        return client.post(path, data={"csrf_token": token, **fields}, follow_redirects=False)

    assert client.post("/today/events", data={"title": "未经授权"}).status_code == 403
    assert post("/today/events", title=" ").status_code == 422
    assert post("/today/events", title="整理虚构验收说明").status_code == 303
    focus = app.state.focus
    today = datetime.now(SHANGHAI).date()
    event, = focus.daily_events(today)
    source = f"/today/events/{event.id}"
    run_url = post(source + "/agent").headers["location"]
    assert post(source + "/agent").headers["location"] == run_url
    run_id = run_url.rsplit("/", 1)[1]
    initial = _fingerprint(client.get(run_url))
    assert post(run_url + "/ai", preview_fingerprint="stale").status_code == 409
    assert post(run_url + "/objective", objective="写一份虚构的演示验收清单").status_code == 303
    assert post(run_url + "/ai", preview_fingerprint=initial).status_code == 409
    assert not sent
    initial = _fingerprint(client.get(run_url))
    assert post(run_url + "/ai", preview_fingerprint=initial, background="true").status_code == 303
    assert sent[0][1] == {"title": event.title, "objective": "写一份虚构的演示验收清单", "role": "research"}
    assert post(run_url + "/objective", objective="决策期间不能换材料").status_code == 422
    assert "待你决定" in client.get("/tasks").text
    assert not app.state.agent_core.artifacts(run_id=run_id)
    assert post(run_url + "/execute").status_code == 409
    assert post(run_url + "/decision", answer="未提供的选择").status_code == 409
    assert post(run_url + "/approve").status_code == 409

    # A new repository instance continues from the saved state.
    app.state.agent_core = AgentCoreRepository(tmp_path)
    assert "用哪种形式？" in client.get(run_url).text
    assert post(run_url + "/decision", answer="清单").status_code == 303
    assert post(run_url + "/ai", preview_fingerprint=initial).status_code == 409
    assert len(sent) == 1
    confirmed = _fingerprint(client.get(run_url))
    assert post(run_url + "/ai", preview_fingerprint=confirmed).status_code == 303
    assert sent[1][1]["decision"]["answer"] == "清单"
    assert post(run_url + "/ai", preview_fingerprint=confirmed).status_code == 409
    assert len(sent) == 2
    assert "待验收" in client.get("/tasks").text
    artifact, = app.state.agent_core.artifacts(run_id=run_id)
    assert "核对虚构示例" in app.state.agent_core.artifact_content(artifact.id)
    assert not app.state.agent_core.tool_calls(run_id)
    assert post(run_url + "/approve").status_code == 303
    assert focus.daily_events(today)[0].status == "planned"
    assert post(source + "/status", status="done").status_code == 303
    assert focus.daily_events(today)[0].status == "done"
    assert not focus.daily_events(today + timedelta(days=1))


def test_model_rejects_unapproved_actions_and_can_replan(tmp_path, monkeypatch):
    model = OpenAICompatibleClient(LLMConfig("http://127.0.0.1:9999/v1", "", "test-model"))
    monkeypatch.setattr(model, "_chat", lambda *_args, **_kwargs: '{"draft":"草稿","tool":"write"}')
    app = create_app(data_root=tmp_path, llm_client=model, enforce_security=False)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    client.post("/today/events", data={"title": "整理测试任务"})
    event, = app.state.focus.daily_events(datetime.now(SHANGHAI).date())
    run_url = client.post(f"/today/events/{event.id}/agent", follow_redirects=False).headers["location"]
    response = client.post(run_url + "/ai", data={"preview_fingerprint": _fingerprint(client.get(run_url))})
    assert response.status_code == 409
    assert "重新规划" in response.text
    run_id = run_url.rsplit("/", 1)[1]
    runtime = app.state.agent_core
    assert runtime.run(run_id).status == "failed"
    assert not runtime.artifacts(run_id=run_id)
    assert runtime.plan_task(runtime.run(run_id).task_id).id != run_id


def test_same_run_cannot_dispatch_model_twice(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import pytest

    runtime = AgentCoreRepository(tmp_path)
    task = runtime.create_task(
        title="核对演示稿", objective="整理虚构演示稿",
        task_type="research", project_id=runtime.projects()[0].id,
    )
    run = runtime.plan_task(task.id)
    entered, release = Event(), Event()

    def model():
        entered.set()
        assert release.wait(5)
        return {"draft": "候选内容"}

    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(runtime.execute_run, run.id, (), model=model)
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError):
                runtime.execute_run(run.id, (), model=lambda: pytest.fail("同一运行不能再次派发"))
            with pytest.raises(ValueError):
                runtime.cancel_run(run.id)
        finally:
            release.set()
        assert result.result().status == "review"
    assert len(runtime.artifacts(run_id=run.id)) == 1



def test_accepted_background_dispatch_can_be_recovered_after_interrupt(tmp_path):
    runtime = AgentCoreRepository(tmp_path)
    task = runtime.create_task(
        title="测试中断", objective="验证后台任务在重启后可处理",
        task_type="research", project_id=runtime.projects()[0].id,
    )
    run = runtime.plan_task(task.id)
    dispatched = []
    runtime.execute_run(run.id, (), model=lambda: {"draft": "候选"}, dispatch=dispatched.append)
    assert len(dispatched) == 1
    assert runtime.run(run.id).status == "running"
    runtime.recover_interrupted_runs()
    assert runtime.run(run.id).error_code == "interrupted"
    assert runtime.task(task.id).status == "failed"
    assert runtime.plan_task(task.id).id != run.id
