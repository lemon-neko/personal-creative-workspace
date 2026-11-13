"""Real v1.8.1 facts and real local Harness SDK, with a synthetic loopback model response."""

import json
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.deepseek_harness import MODEL, DeepSeekHarnessClient
from app.llm import LLMConfig
from app.main import create_app
from app.model_gateway import ModelGateway
from app.plugins import plugin_root
from app.workflow_hub import plugin_environment
from tests.browser.test_browser_acceptance import _free_port, _launch_browser, _wait_for, expect, sync_playwright
from tests.test_deepseek_harness import harness_provider
from tests.test_workflow_plugins import post_preview, prepare_real_hub, until

pytestmark = pytest.mark.skipif(
    not all(os.getenv(key) for key in ("WORKBENCH_E2E_WEB", "WORKBENCH_E2E_ENGINE", "WORKBENCH_E2E_DSH")),
    reason="requires pinned Autoloop, Web package, and installed Harness",
)


def test_v3_observes_real_hub_and_harness(tmp_path, monkeypatch):
    hub_url = prepare_real_hub(tmp_path, monkeypatch)
    root = plugin_root(tmp_path)
    home = root / "autoloop-data"
    rules_path = home / "rules.json"
    rules = json.loads(rules_path.read_text())
    rules["agents"]["native"] = {
        "name": "原生验收 Worker", "worker": "native-fixture", "use": "command", "command": ["false"],
    }
    rules["rules"].append({
        "name": "交付复查", "when": {"source": "workbench", "types": ["fixture.review"]},
        "to": "native", "cwd": str(home), "parallel": 2, "resume": True,
        "emits": {"source": "workbench", "types": ["fixture.reported"]},
    })
    rules_path.write_text(json.dumps(rules))
    native = subprocess.check_output(
        ["node", str(root / "autoloop/bin/agent-autoloop.ts"), "key", "new", "worker", "native-fixture"],
        env=plugin_environment(home), text=True,
    ).strip()
    keys = json.loads((home / "workbench-keys.json").read_text())
    responses = iter([
        {"question": "交付说明使用哪个受众版本？", "options": ["读者版", "维护者版"]},
        {"draft": "验收产物：为维护者编写可复现的同步验证说明。"},
    ])
    artifacts = os.getenv("WORKBENCH_E2E_SCREENSHOTS")
    folder = Path(artifacts) if artifacts else None
    if folder:
        folder.mkdir(parents=True, exist_ok=True)

    with harness_provider(lambda _: next(responses)) as (provider, calls):
        app = create_app(data_root=tmp_path, enable_scheduler=False, enforce_security=False)
        workflow = app.state.workflow
        adapter = DeepSeekHarnessClient(LLMConfig(provider, "fixture", MODEL), Path(os.environ["WORKBENCH_E2E_DSH"]))
        workflow.gateway = ModelGateway(tmp_path, adapter)
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, ws="none", access_log=False, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            _wait_for(base + "/tasks")
            until(lambda: workflow.ready)
            with httpx.Client(base_url=base, trust_env=False, timeout=10) as client:
                item = client.post("/workflow/new", data={"title": "同步验证交付说明"}, follow_redirects=False).headers["location"]
                item_id = item.rsplit("/", 1)[-1]
                preview = post_preview(client, {}, item, "起草一份虚构的同步验证说明")
                client.post(f"{item}/approve", data=preview, follow_redirects=True).raise_for_status()
                first = until(lambda: "预览续跑" in client.get(item).text and workflow.store.turns(item_id)[0])
                with httpx.Client(base_url=hub_url, trust_env=False, timeout=8) as hub:
                    def native_call(path, *, method="GET", token=native, body=None, params=None):
                        response = hub.request(method, path, headers={"Authorization": f"Bearer {token}"}, json=body, params=params)
                        assert response.is_success, response.text[:350]
                        return response.json()

                    native_call("/v1/events", method="POST", token=keys["source"], body={
                        "id": "fixture-review", "type": "fixture.review", "subject": "release-checklist", "summary": "发布清单待复查",
                    })
                    job = native_call("/v1/work", params={"claim": "fixture-first", "wait": 1})["job"]
                    native_run = job["run"]
                    native_call(f"/v1/runs/{native_run}/started", method="POST", token=job["token"],
                                body={"session": "fixture-review-session"})
                    next_check = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                    native_call(f"/v1/runs/{native_run}/result", method="POST", token=job["token"], body={
                        "outcome": "done", "summary": "已核对发布清单",
                        "ask": [{"title": "确认发布范围", "text": "请选择本轮复查范围。", "options": ["小范围", "全量"]}],
                        "notice": [{"title": "清单核对完成", "text": "仅告知。", "fyi": True}],
                        "later": [{"key": "review", "at": next_check, "about": "检查发布回执"}],
                        "events": [{"id": "fixture-reported", "type": "fixture.reported", "subject": "release-checklist"}],
                    })
                    trace = client.get(f"/workflow/control/runs/{native_run}").json()
                    assert {step["kind"] for step in trace["timeline"]} >= {"event", "queue", "start", "receipt", "later", "emit", "card"}
                    assert any(card["fyi"] for card in trace["cards"])

                    with sync_playwright() as playwright:
                        browser = _launch_browser(playwright)
                        page = browser.new_page(viewport={"width": 1510, "height": 1080})
                        page.on("dialog", lambda dialog: dialog.accept())
                        page.goto(base + "/tasks")
                        expect(page.locator("#control-flow button")).to_have_count(12)
                        expect(page.locator("#control-branches")).to_contain_text("1 当前定时器")
                        expect(page.locator("#control-health")).to_contain_text("正常在线")
                        if folder:
                            page.screenshot(path=folder / "01-workflow-overview.png", full_page=True)
                        node = page.get_by_role("button", name="03 清洗与去重", exact=False)
                        node.focus()
                        node.press("Enter")
                        expect(page.get_by_role("dialog")).to_contain_text("不可单独观测")
                        page.keyboard.press("Escape")

                        workbench_ask = page.locator("#control-cards article").filter(has_text="待你决定")
                        expect(workbench_ask).to_be_visible()
                        page.context.set_offline(True)
                        expect(page.locator("#control-health")).to_contain_text("数据已过期", timeout=10000)
                        continued = post_preview(client, {}, item, "起草虚构同步验证说明", first["id"], answer_text="使用维护者版")
                        client.post(f"{item}/approve", data=continued, follow_redirects=True).raise_for_status()
                        last = until(lambda: "验收此产物" in client.get(item).text and workflow.store.turns(item_id)[0])
                        client.post(f"{item}/accept", data={"turn_id": last["id"]}, follow_redirects=True).raise_for_status()
                        page.context.set_offline(False)
                        expect(page.locator("#control-health")).to_contain_text("正常在线", timeout=10000)
                        expect(workbench_ask).to_have_count(0, timeout=10000)
                        assert len(calls) == 2

                        card = page.locator("#control-cards article").filter(has_text="确认发布范围")
                        card.get_by_role("button", name="查看决策上下文").click()
                        panel = page.get_by_role("dialog")
                        expect(panel).to_contain_text("已核对发布清单")
                        panel.get_by_role("combobox").select_option(index=1)
                        panel.get_by_role("button", name="确认回答").click()
                        expect(panel).to_contain_text("已关联续跑", timeout=10000)
                        native_followup = native_call("/v1/work", params={"claim": "fixture-next", "wait": 1})["job"]
                        assert native_followup["run"] != native_run
                        native_call(f"/v1/runs/{native_followup['run']}/result", method="POST",
                                    token=native_followup["token"], body={"outcome": "nothing"})
                        page.keyboard.press("Escape")

                        page.goto(f"{base}/tasks/matters?item={item_id}")
                        page.get_by_role("button", name="执行轮次").click()
                        expect(page.locator("#control-matter-page")).to_contain_text(f"Run #{first['run']}")
                        expect(page.locator("#control-matter-page")).to_contain_text(f"Run #{last['run']}")
                        if folder:
                            page.screenshot(path=folder / "02-matter-rounds.png", full_page=True)
                        page.get_by_role("button", name="完整历史").click()
                        expect(page.locator("#control-matter-page")).to_contain_text("人工回答")
                        expect(page.locator("#control-matter-page")).to_contain_text("产物待人工验收")
                        page.goto(f"{base}/workflow/runs/{first['run']}")
                        initial = page.locator("#replay-current").text_content()
                        page.get_by_role("button", name="下一步").click()
                        assert page.locator("#replay-current").text_content() != initial
                        page.get_by_role("button", name="上一步").click()
                        assert page.locator("#replay-current").text_content() == initial
                        page.locator("#replay-position").focus()
                        page.keyboard.press("End")
                        expect(page.locator("#replay-current")).to_contain_text("本轮已结束")
                        if folder:
                            page.screenshot(path=folder / "03-trace-replay.png", full_page=True)

                        page.goto(f"{base}/tasks/sessions/{last['run']}")
                        expect(page.get_by_text("SDK 会话初始化", exact=True)).to_be_visible()
                        expect(page.get_by_text("SDK 轮次结束", exact=True)).to_be_visible()
                        page.get_by_text("展开输出", exact=True).click()
                        expect(page.locator("#execution-output")).to_contain_text("可复现")
                        if folder:
                            page.screenshot(path=folder / "04-agent-execution.png", full_page=True)
                        page.get_by_label("类型").select_option("sdk")
                        expect(page.locator("#execution-output")).to_be_hidden()
                        assert len(calls) == 2

                        page.set_viewport_size({"width": 390, "height": 844})
                        page.goto(base + "/tasks")
                        expect(page.locator("#control-flow button")).to_have_count(12)
                        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
                        if folder:
                            page.screenshot(path=folder / "05-mobile-overview.png", full_page=True)
                        browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
