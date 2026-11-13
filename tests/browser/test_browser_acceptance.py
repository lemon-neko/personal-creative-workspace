"""High-value desktop and Android-PWA browser flows."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.knowledge_store import (
    create_knowledge_card,
    create_knowledge_map,
)
from app.mobile import MOBILE_SESSION_COOKIE, MobileStore
from app.focus import FocusRepository
from app.mobile_daily import DailySnapshot, daily_now, save_daily_snapshot
from app.workspace import SHANGHAI, create_item, items_directory, load_items, update_item

playwright_module = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


def _launch_browser(playwright):
    bundled = Path(playwright.chromium.executable_path)
    if bundled.exists():
        return playwright.chromium.launch()
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if chrome.exists():
        return playwright.chromium.launch(executable_path=str(chrome))
    return playwright.chromium.launch()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for(url: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"测试服务未能启动：{url}")


@pytest.fixture(scope="module")
def browser_workspace(tmp_path_factory: pytest.TempPathFactory):
    data_root = tmp_path_factory.mktemp("browser-workspace")
    content_root = data_root / "content"
    source = create_item(content_root, body="知识来源：可靠系统需要可追溯。")
    article = create_item(
        content_root,
        body="## 正文\n\n这是一篇用于公众号预览的虚构文章。",
        title="虚构的可靠性文章",
        kind="article",
    )
    subject = create_knowledge_map(
        content_root,
        title="技术",
        kind="subject",
        summary="软件与人工智能系统。",
    )
    topic = create_knowledge_map(
        content_root,
        title="Agent 可靠性",
        kind="topic",
        summary="工具调用、安全与恢复。",
        parent_ids=(subject.id,),
    )
    create_knowledge_card(
        content_root,
        title="可靠性来自可追溯过程",
        body="每次关键动作都需要留下可验证的轨迹。",
        card_type="claim",
        subjects=("技术",),
        source_ids=(source.id,),
        map_ids=(topic.id,),
        concepts=("可追溯",),
    )
    mobile = MobileStore(data_root)
    mobile.save_config(enabled=True, tailnet_host="workbench.example.ts.net")
    code, _ = mobile.create_pairing_code()
    _, mobile_token = mobile.pair(code, "浏览器验收设备")

    desktop_port = _free_port()
    mobile_port = _free_port()
    while mobile_port == desktop_port:
        mobile_port = _free_port()
    environment = os.environ | {
        "E2E_DATA_ROOT": str(data_root),
        "WORKSPACE_DATA_DIR": str(data_root),
    }
    commands = (
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.browser.e2e_server:desktop_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(desktop_port),
        ],
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.browser.e2e_server:mobile_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(mobile_port),
        ],
    )
    desktop_url = f"http://127.0.0.1:{desktop_port}"
    mobile_url = f"http://127.0.0.1:{mobile_port}"
    processes = []
    try:
        for command, url in zip(commands, (desktop_url, mobile_url), strict=True):
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=Path(__file__).resolve().parents[2],
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            _wait_for(url)
        yield {
            "data_root": data_root,
            "content_root": content_root,
            "desktop_url": desktop_url,
            "mobile_url": mobile_url,
            "article_id": article.id,
            "source_id": source.id,
            "mobile_token": mobile_token,
        }
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)


def test_desktop_creation_knowledge_and_publish(browser_workspace) -> None:
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page()
        page.goto(browser_workspace["desktop_url"])
        page.get_by_text("记一条想法", exact=True).click()
        page.locator("#quick-body").fill("浏览器验收生成的想法")
        page.get_by_role("button", name="接住这个念头").click()
        expect(page).to_have_url(re.compile(r"saved=created"))

        items = load_items(items_directory(browser_workspace["content_root"]))
        created = next(item for item in items.items if item.title == "浏览器验收生成的想法")
        page.goto(f"{browser_workspace['desktop_url']}/ideas/{created.id}")
        page.locator('textarea[name="body"]').fill("浏览器验收修改后的想法")
        page.get_by_role("button", name="保存修改").click()
        page.locator(".status-actions").get_by_role("button", name="已整理").click()
        expect(page.locator(".status-actions button.active")).to_have_text("已整理")

        page.goto(f"{browser_workspace['desktop_url']}/knowledge")
        expect(page.get_by_role("heading", name="知识库", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="学科目录")).to_be_visible()
        expect(page.get_by_role("button", name="知识卡：可靠性来自可追溯过程")).not_to_be_visible()
        page.locator("summary").filter(has_text="核心知识图").click()
        expect(page.get_by_role("button", name="知识卡：可靠性来自可追溯过程")).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.goto(f"{browser_workspace['desktop_url']}/articles")
        expect(page.get_by_role("heading", name="文章创作")).to_be_visible()
        expect(page.locator(".quiet-rows li").first).to_be_visible()
        page.get_by_text("新建文章草稿", exact=True).click()
        expect(page.get_by_label("正文或写作提纲")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        page.goto(
            f"{browser_workspace['desktop_url']}/publish/"
            f"{browser_workspace['article_id']}"
        )
        expect(page.get_by_role("button", name="一键复制公众号正文")).to_be_visible()
        browser.close()


def test_focus_dashboard_desktop_and_narrow_viewport(browser_workspace, tmp_path: Path) -> None:
    repository = FocusRepository(browser_workspace["data_root"])
    cycle = repository.import_plan(
        key="browser-focus-sample", title="虚构交付期",
        starts_on="2026-10-12", ends_on="2099-11-30",
        goals=(
            {"title": "完成服务演示", "area": "venture", "priority": "P0",
             "summary": "验证一个完整场景。", "deliverables": ({"title": "演示可运行"},)},
            {"title": "获得岗位反馈", "area": "career", "priority": "P0",
             "summary": "记录真实推进阶段。", "deliverables": ({"title": "整理面试反馈"},)},
            {"title": "私人事项", "area": "life", "priority": "P0",
             "visibility": "detail_only", "deliverables": ({"title": "PRIVATE_BROWSER_DETAIL"},)},
        ),
        decisions=({"title": "阶段判断", "due_on": "2026-11-12"},),
    )
    venture, career = repository.goals(cycle.id)[:2]
    venture_delivery = repository.deliverables(venture.id)[0]
    career_delivery = repository.deliverables(career.id)[0]
    today = datetime.now(SHANGHAI).date()
    repository.set_week_focus(venture_delivery.id, selected=True, on=today)
    repository.set_week_focus(career_delivery.id, selected=True, on=today)
    for delivery, title in (
        (venture_delivery, "核对演示路径"),
        (career_delivery, "整理岗位反馈"),
    ):
        action = repository.create_action(deliverable_id=delivery.id, title=title)
        repository.set_day_focus(action.id, selected=True, on=today)
    repository.create_action(deliverable_id=venture_delivery.id, title="待安排的演示彩排")
    repository.create_daily_event("补交昨日记录", today, due_on=(today - timedelta(days=1)).isoformat())
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(browser_workspace["desktop_url"] + "/?board=list")
        expect(page.locator(".board-event")).to_have_count(3)
        expect(page.locator(".home-track-row")).to_have_count(2)
        expect(page.locator(".desk-row-meta a")).to_have_count(2)
        expect(page.locator("#workspace-feed")).to_have_count(0)
        expect(page.get_by_role("heading", name="今日", exact=True)).to_be_visible()
        search = page.get_by_role("link", name="搜索工作台", exact=True)
        search.click()
        expect(page.locator("#palette-query")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#search-palette")).not_to_be_visible()
        expect(search).to_be_focused()
        expect(page.get_by_role("region", name=re.compile("逾期")).get_by_text("补交昨日记录")).to_be_visible()
        assert page.locator(".home-today").bounding_box()["x"] < page.locator(".home-tracks").bounding_box()["x"]
        first_check = page.get_by_role("checkbox").first
        first_check.focus()
        page.keyboard.press("ArrowDown")
        expect(page.get_by_role("checkbox").nth(1)).to_be_focused()
        first_action = page.locator(".desk-row-meta a").first
        first_action.click()
        expect(page).to_have_url(re.compile(r"/focus/goals/"))
        expect(page).to_have_url(re.compile(r"#action-"))
        page.goto(browser_workspace["desktop_url"] + "/?board=list")
        page.locator(".board-event").filter(has_text="整理岗位反馈").get_by_role("button", name="交给 AI").click()
        expect(page).to_have_url(re.compile(r"/runs/"))
        run_path = page.url
        page.get_by_role("button", name="运行本地计划", exact=True).click()
        expect(page.get_by_text("等待人工确认", exact=True)).to_be_visible()
        page.goto(browser_workspace["desktop_url"] + "/?board=list")
        expect(page.get_by_role("region", name="待我确认").get_by_text("待验收", exact=True)).to_be_visible()
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(350)
        page.screenshot(path=str(tmp_path / "focus-desktop.png"))
        assert "PRIVATE_BROWSER_DETAIL" not in page.content()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        for width, height, label in ((1024, 768, "tablet"), (390, 844, "narrow"), (320, 720, "minimum")):
            page.set_viewport_size({"width": width, "height": height})
            page.reload()
            expect(page.get_by_role("heading", name="今日")).to_be_visible()
            if width <= 760:
                assert page.locator(".home-today").bounding_box()["y"] < page.locator(".home-tracks").bounding_box()["y"]
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(350)
            page.screenshot(path=str(tmp_path / f"focus-{label}.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.keyboard.press("Alt+n")
        add = page.get_by_role("textbox", name="新增待办")
        expect(add).to_be_focused()
        add_request = re.compile(r"/today/events(?:\?.*)?$")
        page.route(add_request, lambda route: route.abort())
        add.fill("核对虚构预约")
        add.press("Enter")
        expect(page.get_by_role("alert")).to_contain_text("未能确认保存")
        expect(add).to_have_value("核对虚构预约")
        page.unroute(add_request)
        add.press("Enter")
        event = page.locator(".board-event").filter(has_text="核对虚构预约")
        expect(event).to_be_visible()
        expect(add).to_be_focused()
        expect(add).to_have_value("")
        event.locator("summary").click()
        event.get_by_label("状态").select_option("active")
        event.get_by_role("button", name="保存").click()
        expect(event.locator(".desk-status")).to_have_text("进行中")
        event.get_by_role("checkbox").press("Space")
        expect(page.get_by_role("button", name="撤销")).to_be_visible()
        expect(event).not_to_be_visible()
        page.get_by_role("button", name="撤销").click()
        expect(event.locator(".desk-status")).to_have_text("进行中")
        event.get_by_role("checkbox").click()
        expect(page.get_by_role("button", name="撤销")).to_be_visible()
        page.reload()
        page.locator(".desk-done > summary").click()
        expect(event.get_by_role("checkbox")).to_be_checked()
        page.get_by_role("navigation", name="待办视图").get_by_role("link", name=re.compile("待安排")).click()
        upcoming = page.locator(".board-event").filter(has_text="待安排的演示彩排")
        upcoming.get_by_role("button", name="放到今日").click()
        expect(upcoming).to_have_count(0)
        page.screenshot(path=str(tmp_path / "desk-upcoming-minimum.png"))
        page.get_by_role("navigation", name="待办视图").get_by_role("link", name="今日", exact=True).click()
        expect(page.get_by_text("待安排的演示彩排", exact=True)).to_be_visible()
        page.goto(f"{browser_workspace['desktop_url']}/focus")
        expect(page.get_by_role("heading", name="主线与分支")).to_be_visible()
        assert "PRIVATE_BROWSER_DETAIL" not in page.content()
        page.goto(run_path)
        page.get_by_role("button", name="接受产物并完成", exact=True).click()
        page.get_by_role("link", name="回到原行动", exact=True).click()
        expect(page).to_have_url(re.compile(r"/focus/goals/.+#action-"))
        expect(page.get_by_label("行动状态", exact=True)).to_have_value("planned")
        browser.close()


def test_daily_calendar_drag_and_workflow_windows(browser_workspace, tmp_path):
    today = datetime.now(SHANGHAI).date()
    root = browser_workspace["desktop_url"]
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{root}/?day=2028-02-15")
        expect(page.locator(".planner-month-nav")).to_contain_text("2028年2月")
        expect(page.locator('.planner-month [data-drop-day="2028-02-29"]')).to_be_visible()
        page.get_by_role("link", name="下个月").click()
        expect(page.locator(".planner-month-nav")).to_contain_text("2028年3月")
        page.get_by_role("link", name="上个月").click()
        expect(page.locator(".planner-month-nav")).to_contain_text("2028年2月")
        page.goto(root)
        nav = page.get_by_role("navigation", name="工作台主导航")
        expect(nav.get_by_role("link")).to_have_count(2)
        add = page.get_by_role("textbox", name="新增待办")
        add.fill("拖动验证事项")
        add.press("Enter")
        card = page.locator(".board-event").filter(has_text="拖动验证事项")
        expect(card.locator("[data-countdown]")).to_contain_text("截止")
        card.locator("[data-planner-grip]").drag_to(page.locator(".planner-hour[data-drop-time='09:00']"))
        expect(page.locator(".planner-hour[data-drop-time='09:00']").get_by_text("拖动验证事项")).to_be_visible()
        other = page.locator(".planner-month a:not([aria-current])").first
        destination = other.get_attribute("data-drop-day")
        card.locator("[data-planner-grip]").drag_to(other)
        expect(card).to_have_count(0)
        page.locator(f".planner-month [data-drop-day='{destination}']").click()
        expect(page.locator(".planner-hour[data-drop-time='09:00']").get_by_text("拖动验证事项")).to_be_visible()
        page.reload()
        expect(card).to_be_visible()
        page.screenshot(path=str(tmp_path / "planner-desktop.png"))
        page.set_viewport_size({"width": 320, "height": 780})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / "planner-narrow.png"))
        card.locator("[data-planner-grip]").press("Enter")
        expect(card.get_by_label("安排到")).to_be_focused()
        card.get_by_label("开始时间").select_option("09:30")
        card.get_by_role("button", name="保存安排").click()
        expect(page.locator(".planner-hour[data-drop-time='09:30']").get_by_text("拖动验证事项")).to_be_visible()
        card.get_by_role("button", name="交给 AI").click()
        expect(page).to_have_url(re.compile("/runs/"))
        nav.get_by_role("link", name="AI 工作流").click()
        expect(page.get_by_role("heading", name="AI 工作流")).to_be_visible()
        expect(page.get_by_role("region", name=re.compile("待执行")).get_by_text("拖动验证事项")).to_be_visible()
        page.screenshot(path=str(tmp_path / "workflow-narrow.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.goto(f"{root}/?day={today.isoformat()}")
        expect(page.get_by_role("heading", name="活动记录")).to_be_visible()
        browser.close()


def test_desktop_assistant_preview_answer_and_confirmed_action(
    browser_workspace,
) -> None:
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page()
        page.goto(browser_workspace["desktop_url"])
        page.get_by_text("更多工具", exact=True).click()
        page.get_by_role("link", name="助手", exact=True).click()
        page.locator('textarea[name="question"]').fill(
            "基于我现在的情况，应该先做什么？"
        )
        page.get_by_role("button", name="检查上下文").click()
        expect(page.get_by_role("heading", name="先看清楚，再发送")).to_be_visible()
        expect(page.get_by_text("不包含联系方式、简历全文")).to_be_visible()

        page.get_by_role("button", name="我已检查，调用模型").click()
        expect(page.get_by_role("heading", name="完成最小可靠性闭环")).to_be_visible()
        expect(page.get_by_text("形成一个测试通过且可以复盘的提交。")).to_be_visible()
        expect(page.get_by_role("heading", name="候选操作")).to_be_visible()

        before = len(
            load_items(items_directory(browser_workspace["content_root"])).items
        )
        page.locator(".assistant-action-card").get_by_role(
            "button", name="确认创建"
        ).click()
        expect(page.get_by_text("已执行你确认的操作。")).to_be_visible()
        after = len(
            load_items(items_directory(browser_workspace["content_root"])).items
        )
        assert after == before + 1
        browser.close()


def test_mobile_board_and_offline_capture(browser_workspace) -> None:
    now = daily_now()
    save_daily_snapshot(browser_workspace["data_root"], DailySnapshot(
        day=now.date(), today=[{"title": "虚构的手机日程", "when": "09:30"}],
        overdue=[], unplanned=[], done=[],
    ), now)
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        context.add_cookies(
            [
                {
                    "name": MOBILE_SESSION_COOKIE,
                    "value": browser_workspace["mobile_token"],
                    "url": browser_workspace["mobile_url"],
                    "sameSite": "Strict",
                }
            ]
        )
        page = context.new_page()
        mobile = browser_workspace["mobile_url"]
        page.goto(f"{mobile}/manifest.webmanifest")
        page.evaluate("""async () => {
            await caches.open("yubai-mobile-knowledge-v1");
            await new Promise((resolve, reject) => {
                const request = indexedDB.open("yubai-mobile-captures", 2);
                request.onupgradeneeded = () => {
                    request.result.createObjectStore("meta");
                    request.result.createObjectStore("ideas", {keyPath: "id"}).put({id: "old-local-note"});
                };
                request.onsuccess = () => { request.result.close(); resolve(); };
                request.onerror = () => reject(request.error);
            });
        }""")
        page.goto(mobile)
        tabs = page.get_by_role("navigation", name="手机工作台").get_by_role("link")
        expect(tabs).to_have_text(["日常工作", "随手记"])
        expect(page.get_by_text("虚构的手机日程")).to_be_visible()
        expect(page.get_by_text("09:30")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")
        page.wait_for_function(
            "async () => navigator.serviceWorker.controller && "
            "!(await caches.keys()).includes('yubai-mobile-knowledge-v1')"
        )
        capture = page.get_by_role("link", name="随手记", exact=True)
        capture.focus()
        with page.expect_response(f"{mobile}/api/session"):
            capture.press("Enter")
        expect(page.locator("#capture-form")).to_be_visible()
        assert page.evaluate("""() => new Promise((resolve, reject) => {
            const request = indexedDB.open("yubai-mobile-captures", 3);
            request.onsuccess = () => {
                const db = request.result;
                const note = db.transaction("ideas").objectStore("ideas").get("old-local-note");
                note.onsuccess = () => resolve(Boolean(note.result) && !db.objectStoreNames.contains("meta"));
                db.close();
            };
            request.onerror = () => reject(request.error);
        })""")
        page.evaluate(
            """async () => {
                const registration = await navigator.serviceWorker.ready;
                Object.defineProperty(registration, "sync", {value: null});
            }"""
        )

        context.set_offline(True)
        page.locator('textarea[name="body"]').fill("离线排队的虚构想法")
        page.get_by_role("button", name="保存到羽白工作台").click()
        expect(page.locator("#queue-count")).to_have_text("1")

        context.set_offline(False)
        page.locator("#sync-now").click()
        expect(page.locator("#queue-count")).to_have_text("0")

        page.goto(f"{browser_workspace['mobile_url']}/ideas")
        source_link = page.locator(
            f'a[href="/ideas/{browser_workspace["source_id"]}"]'
        )
        expect(source_link).to_be_visible()
        source_link.click()
        expect(page.locator("#idea-edit-form")).to_be_visible()
        context.set_offline(True)
        page.locator('#idea-edit-form textarea[name="body"]').fill(
            "手机离线编辑的可靠性想法。"
        )
        page.get_by_role("button", name="保存修改").click()
        expect(page.locator("#idea-edit-message")).to_contain_text("保存在手机")

        update_item(
            browser_workspace["content_root"],
            browser_workspace["source_id"],
            body="Obsidian 同时补充了可追溯边界。",
        )
        context.set_offline(False)
        expect(page.locator("#idea-conflict")).to_be_visible()
        page.locator("#conflict-local-body").fill("人工合并后的可靠性想法。")
        page.get_by_role("button", name="保存合并稿").click()
        expect(page.locator("#idea-conflict")).to_be_hidden()
        assert (
            load_items(items_directory(browser_workspace["content_root"]))
            .get(browser_workspace["source_id"])
            .body
            == "人工合并后的可靠性想法。"
        )

        assert page.goto(f"{mobile}/knowledge").status == 404
        context.set_offline(True)
        page.goto(mobile)
        expect(page.get_by_role("heading", name="离线随手记")).to_be_visible()
        expect(page.get_by_text("虚构的手机日程")).to_have_count(0)
        browser.close()


def test_career_workspace_autosave_snapshot_and_narrow_viewport(browser_workspace, tmp_path: Path) -> None:
    from app.career import CareerRepository
    from app.resume_studio import normalize_structured_resume

    repository = CareerRepository(browser_workspace["data_root"])
    primary = repository.primary_resume() or repository.add_structured_resume(
        title="虚构工程师主简历", resume_kind="master", is_primary=True,
        structured=normalize_structured_resume({
            "personal_info": {"name": "测试候选人", "title": "AI 应用工程师"},
            "summary": "完成可验证的本地工程项目。", "skills": ["Python", "FastAPI"],
        }),
    )
    job = repository.add_job(company="青禾自动保存验收", title="Agent 应用工程师", next_action="准备项目介绍")
    base = browser_workspace["desktop_url"]
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{base}/career?q=青禾自动保存验收#applications")
        expect(page.get_by_role("heading", name="简历工作室", exact=True)).to_be_visible()
        expect(page.locator("#supporting-materials")).not_to_have_attribute("open", "")
        row = page.locator(f"#job-{job.id}")
        expect(row.get_by_label("当前进度", exact=True)).to_have_value("saved")
        expect(row.get_by_role("link", name="编辑", exact=True)).to_have_count(0)
        row.get_by_label("当前进度", exact=True).select_option("interview_2")
        row.get_by_label("投递日期", exact=True).fill("2026-10-20")
        row.get_by_label("备注", exact=True).fill("二面重点：项目设计")
        row.get_by_label("备注", exact=True).press("Tab")
        expect(row.locator("[data-save-state]")).to_have_text("已保存")
        assert repository.job(job.id).notes == "二面重点：项目设计"
        assert repository.job(job.id).status == "interview_2"
        assert repository.job(job.id).applied_on == "2026-10-20"
        row.get_by_label("选择投递简历", exact=True).select_option(primary.id)
        row.get_by_role("button", name="记录", exact=True).click()
        expect(row.locator("[data-snapshot-link]")).to_contain_text("只读快照")
        row.get_by_role("link", name="虚构工程师主简历", exact=True).click()
        expect(page.get_by_role("heading", name="投递简历快照", exact=True)).to_be_visible()
        expect(page.locator(".career-snapshot")).to_contain_text("完成可验证的本地工程项目。")
        page.goto(f"{base}/career?q=青禾自动保存验收")
        page.screenshot(path=str(tmp_path / "career-autosave-desktop.png"), full_page=True, animations="disabled")
        # A partially typed new row is not created; completing both required fields creates once.
        blank = page.locator("#new-application")
        blank.get_by_label("公司", exact=True).fill("新增自动保存公司")
        blank.get_by_label("公司", exact=True).press("Tab")
        assert not any(value.company == "新增自动保存公司" for value in repository.jobs())
        blank.get_by_label("岗位", exact=True).fill("新平台岗位")
        blank.get_by_label("岗位", exact=True).press("Tab")
        expect(page.locator('[data-career-row][data-job-id^="job-inline-"] [data-save-state]')).to_have_text("已保存")
        created = [value for value in repository.jobs() if value.company == "新增自动保存公司"]
        assert len(created) == 1
        expect(page.locator("#new-application").get_by_label("公司", exact=True)).to_have_value("")
        expect(page.locator(f"#job-{created[0].id}").get_by_role("link", name="详情", exact=True)).to_be_visible()
        for width in (390, 320):
            page.set_viewport_size({"width": width, "height": 844})
            page.goto(f"{base}/career?q=青禾自动保存验收")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            narrow = page.locator(f"#job-{job.id}")
            narrow.get_by_label("备注", exact=True).fill(f"窄屏保存 {width}")
            narrow.get_by_label("备注", exact=True).press("Tab")
            expect(narrow.locator("[data-save-state]")).to_have_text("已保存")
            assert repository.job(job.id).notes == f"窄屏保存 {width}"
            page.screenshot(path=str(tmp_path / f"career-autosave-{width}.png"), full_page=True, animations="disabled")
        page.reload()
        expect(page.locator(f"#job-{job.id}").get_by_label("备注", exact=True)).to_have_value("窄屏保存 320")
        browser.close()


def test_career_autosave_queue_failure_retry_and_creation_replay(browser_workspace) -> None:
    from app.career import CareerRepository

    repository = CareerRepository(browser_workspace["data_root"])
    job = repository.add_job(company="串行请求验收", title="平台开发", jd_text="必须保留 JD", tier="A")
    base = browser_workspace["desktop_url"]
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{base}/career?q=串行请求验收")
        requests = []
        fail = [False]

        def patch_request(route):
            if route.request.method != "PATCH":
                route.continue_()
                return
            requests.append(route.request.post_data_json)
            if fail[0]:
                fail[0] = False
                route.fulfill(status=503, json={"error": "模拟暂时断线"})
            else:
                route.continue_()

        page.route(f"**/career/jobs/{job.id}", patch_request)
        # Changes in one event-loop turn must queue behind the first write and coalesce.
        page.locator(f"#job-{job.id}").evaluate("""row => {
            const stage = row.querySelector('[name="status"]');
            stage.value = 'interview_1'; stage.dispatchEvent(new Event('change', { bubbles: true }));
            const next = row.querySelector('[name="next_action"]');
            next.value = '旧动作'; next.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
            next.value = '最终动作'; next.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
            stage.value = 'interview_2'; stage.dispatchEvent(new Event('change', { bubbles: true }));
        }""")
        row = page.locator(f"#job-{job.id}")
        expect(row.locator("[data-save-state]")).to_have_text("已保存")
        assert len(requests) == 2 and requests[0] == {"status": "interview_1"}
        assert requests[1] == {"next_action": "最终动作", "status": "interview_2"}
        assert repository.job(job.id).status == "interview_2"
        assert repository.job(job.id).next_action == "最终动作"
        assert repository.job(job.id).jd_text == "必须保留 JD" and repository.job(job.id).tier == "A"
        assert repository.job_submissions(job.id) == ()
        fail[0] = True
        row.get_by_label("备注", exact=True).fill("断线时仍保留的输入")
        row.get_by_label("备注", exact=True).press("Tab")
        expect(row.locator("[data-save-state]")).to_contain_text("保存失败")
        old_url = page.url
        page.get_by_role("button", name="筛选", exact=True).click()
        expect(page).to_have_url(old_url)
        expect(row.get_by_label("备注", exact=True)).to_have_value("断线时仍保留的输入")
        row.get_by_role("button", name="重试", exact=True).click()
        expect(row.locator("[data-save-state]")).to_have_text("已保存")
        assert repository.job(job.id).notes == "断线时仍保留的输入"
        # Navigating through the filter flushes the active text field first.
        row.get_by_label("备注", exact=True).fill("筛选前的最后改动")
        page.get_by_role("button", name="筛选", exact=True).click()
        expect(page).to_have_url(re.compile(r"#applications$"))
        assert repository.job(job.id).notes == "筛选前的最后改动"
        # The server creates the row but the first response is lost: retry must not duplicate.
        lost = [False]

        def create_request(route):
            if route.request.method == "POST" and not lost[0]:
                route.fetch()
                lost[0] = True
                route.abort("failed")
            else:
                route.continue_()

        page.route("**/career/jobs", create_request)
        blank = page.locator("#new-application")
        blank.get_by_label("公司", exact=True).fill("重试不重复公司")
        blank.get_by_label("岗位", exact=True).fill("重试岗位")
        blank.get_by_label("岗位", exact=True).press("Tab")
        expect(blank.locator("[data-save-state]")).to_contain_text("保存失败")
        assert len([item for item in repository.jobs() if item.company == "重试不重复公司"]) == 1
        blank.get_by_role("button", name="重试", exact=True).click()
        expect(page.locator('[data-career-row][data-job-id^="job-inline-"] [data-save-state]')).to_have_text("已保存")
        assert len([item for item in repository.jobs() if item.company == "重试不重复公司"]) == 1
        expect(page.locator("#new-application").get_by_label("公司", exact=True)).to_have_value("")
        browser.close()
