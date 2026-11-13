"""Real packaged Web, supervised in a temporary workspace on isolated ports."""

import os
import sys
import threading
from pathlib import Path

import pytest
import uvicorn

from app import autoloop_plugin, daily_plugin, install_plugins, privacy
from app.main import create_app
from app.plugin_paths import plugin_root
from app.process_supervisor import child_process
from app.routers import daily
from tests.browser.test_browser_acceptance import _free_port, _launch_browser, _wait_for, expect, sync_playwright
from tests.test_workflow_plugins import until


@pytest.mark.skipif(not all(os.getenv(key) for key in ("WORKBENCH_E2E_WEB", "WORKBENCH_E2E_ENGINE")),
                    reason="requires pinned upstream Web and Autoloop packages")
def test_real_web_and_workflow_have_independent_runtime_and_persist_browser_data(tmp_path, monkeypatch):
    desktop_port, web_port, hub_port = _free_port(), _free_port(), _free_port()
    base, web, hub = f"http://127.0.0.1:{desktop_port}", f"http://localhost:{web_port}", f"http://127.0.0.1:{hub_port}"
    for module in (daily_plugin, daily, privacy):
        monkeypatch.setattr(module, "DAILY_ORIGIN", web)
    for module in (daily_plugin, daily):
        monkeypatch.setattr(module, "WORKBENCH_ORIGIN", base)
    for module in (autoloop_plugin, install_plugins):
        monkeypatch.setattr(module, "HUB_URL", hub)

    # Only change the fixture's bind addresses. The child still serves the real upstream assets.
    def spawn(command, **kwargs):
        code = (
            "import os, sys, uvicorn; from pathlib import Path; from app import plugin_web as web; "
            "web.DAILY_PORT = int(sys.argv[2]); web.WORKBENCH_ORIGIN = sys.argv[3]; "
            "uvicorn.run(web.web_app(Path(sys.argv[1]), health_secret=os.environ[web.HEALTH_ENV]), "
            "host='127.0.0.1', port=web.DAILY_PORT, proxy_headers=False, access_log=False, lifespan='off')"
        )
        return child_process((sys.executable, "-c", code, command[-1], str(web_port), base), **kwargs)

    monkeypatch.setattr(daily_plugin, "child_process", spawn)
    install_plugins.provision(tmp_path, Path(os.environ["WORKBENCH_E2E_WEB"]), Path(os.environ["WORKBENCH_E2E_ENGINE"]))
    (plugin_root(tmp_path) / "enabled").touch()
    app = create_app(data_root=tmp_path, enable_scheduler=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=desktop_port, ws="none",
                                           access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_for(base + "/settings/runtime")
        runtime = app.state.plugin_runtime
        until(lambda: all(row[2].last_health_ok for row in runtime.snapshots()))
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page()
            response = page.goto(base)
            assert f"frame-src {web};" in response.headers["content-security-policy"]
            iframe = page.frame_locator("iframe.daily-frame")
            expect(iframe.get_by_role("button", name="Switch to English")).to_be_visible(timeout=15000)
            frame = page.frame(url=lambda url: url.startswith(web))
            assert frame.evaluate("window.location.origin") == web
            databases = frame.evaluate("async () => (await indexedDB.databases()).map(db => db.name)")
            assert databases
            marker = "workbench-test-isolated-origin"
            frame.evaluate("""name => new Promise((resolve, reject) => {
                const request = indexedDB.open(name, 1);
                request.onerror = () => reject(request.error);
                request.onupgradeneeded = () => request.result.createObjectStore('check').put('retained', 'value');
                request.onsuccess = () => { request.result.close(); resolve(); };
            })""", marker)
            page.goto(base + "/settings/runtime")
            for name in ("Super Productivity", "Autoloop Hub", "Autoloop Worker"):
                expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
            assert page.get_by_text("Ready", exact=True).count() == 3
            section = page.locator("section.paper-panel").filter(has=page.get_by_role("heading", name="Super Productivity"))
            web_pid = runtime.web.snapshot.pid
            with page.expect_response(lambda response: response.url.endswith("/daily/restart")) as result:
                section.get_by_role("button", name="重启").click()
            assert result.value.status == 303, result.value.text()
            until(lambda: runtime.daily_ready and runtime.web.snapshot.pid != web_pid)
            page.goto(base)
            expect(iframe.get_by_role("button", name="Switch to English")).to_be_visible(timeout=15000)
            frame = page.frame(url=lambda url: url.startswith(web))
            assert frame.evaluate("""name => new Promise((resolve, reject) => {
                const request = indexedDB.open(name);
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    const value = request.result.transaction('check').objectStore('check').get('value');
                    value.onsuccess = () => { request.result.close(); resolve(value.result); };
                };
            })""", marker) == "retained"
            assert runtime.autoloop.worker.snapshot.restart_count == 0
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive()
