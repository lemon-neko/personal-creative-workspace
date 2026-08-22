"""High-value desktop and Android-PWA browser flows."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from app.knowledge_store import (
    create_knowledge_card,
    create_knowledge_map,
    load_knowledge_store,
)
from app.mobile import MOBILE_SESSION_COOKIE, MobileStore
from app.workspace import create_item, items_directory, load_items, update_item

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
    card = create_knowledge_card(
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
            "card_id": card.id,
            "source_id": source.id,
            "topic_id": topic.id,
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
        expect(page.get_by_role("button", name="知识卡：可靠性来自可追溯过程")).to_be_visible()

        page.goto(
            f"{browser_workspace['desktop_url']}/publish/"
            f"{browser_workspace['article_id']}"
        )
        expect(page.get_by_role("button", name="一键复制公众号正文")).to_be_visible()
        browser.close()


def test_desktop_assistant_preview_answer_and_confirmed_action(
    browser_workspace,
) -> None:
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page()
        page.goto(browser_workspace["desktop_url"])
        page.locator(".assistant-quick-form textarea").fill(
            "基于我现在的情况，应该先做什么？"
        )
        page.locator(".assistant-quick-form").get_by_role(
            "button", name="检查上下文"
        ).click()
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


def test_mobile_offline_queue_and_online_knowledge(browser_workspace) -> None:
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        context = browser.new_context()
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
        page.goto(browser_workspace["mobile_url"])
        expect(page.get_by_role("link", name="知识库")).to_be_visible()
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

        page.get_by_text("整理为知识卡").click()
        page.locator('#mobile-distill-form input[name="title"]').fill(
            "合并需要显式确认"
        )
        page.locator('#mobile-distill-form textarea[name="body"]').fill(
            "并发修改不能静默覆盖，必须由作者确认最终版本。"
        )
        page.locator(
            f'#mobile-distill-form input[value="{browser_workspace["topic_id"]}"]'
        ).check()
        page.locator("#mobile-distill-form").get_by_role(
            "button", name="创建知识卡"
        ).click()
        expect(page.locator("#distill-message")).to_contain_text("已创建知识卡")
        assert any(
            card.title == "合并需要显式确认"
            for card in load_knowledge_store(browser_workspace["content_root"]).cards
        )

        page.goto(f"{browser_workspace['mobile_url']}/knowledge")
        expect(page.get_by_text("Agent 可靠性")).to_be_visible()
        expect(page.locator("#knowledge-cache-status")).to_contain_text("已缓存")
        page.goto(
            f"{browser_workspace['mobile_url']}/knowledge/cards/"
            f"{browser_workspace['card_id']}"
        )
        expect(page.get_by_text("每次关键动作都需要留下可验证的轨迹。")).to_be_visible()
        context.set_offline(True)
        page.goto(f"{browser_workspace['mobile_url']}/knowledge")
        expect(page.get_by_text("Agent 可靠性")).to_be_visible()
        page.goto(
            f"{browser_workspace['mobile_url']}/knowledge/cards/"
            f"{browser_workspace['card_id']}"
        )
        expect(page.get_by_text("每次关键动作都需要留下可验证的轨迹。")).to_be_visible()
        browser.close()
