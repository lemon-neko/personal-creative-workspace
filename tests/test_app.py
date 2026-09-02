from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.content import load_items, semantic_revision
from app.llm import PolishResult
from app.knowledge_store import (
    create_knowledge_card,
    create_knowledge_map,
    load_knowledge_store,
)
from app.main import REPO_ROOT, create_app
from app.runtime import (
    DESKTOP_LABEL,
    MAX_LOG_BYTES,
    build_launch_agent,
    install_service,
    restart_service,
)
from app.workspace import create_item, items_directory, set_item_status


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_importing_factories_does_not_initialize_private_data(tmp_path: Path) -> None:
    untouched = tmp_path / "must-not-exist"
    environment = os.environ.copy()
    environment["WORKSPACE_DATA_DIR"] = str(untouched)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.main import create_app; "
            "from app.mobile_main import create_mobile_app; "
            "print(create_app.__name__, create_mobile_app.__name__)",
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert not untouched.exists()


def test_launch_agent_contains_only_non_secret_local_configuration(
    tmp_path: Path,
) -> None:
    value = build_launch_agent(
        label=DESKTOP_LABEL,
        module="app",
        python=tmp_path / ".venv" / "bin" / "python",
        repository_root=tmp_path / "repository",
        data_root=tmp_path / "private-data",
    )
    assert value["ProgramArguments"][-2:] == ["-m", "app"]
    environment = value["EnvironmentVariables"]
    assert environment["WORKSPACE_DATA_DIR"] == str(tmp_path / "private-data")
    assert environment["HOME"] == str(Path.home())
    assert environment["USER"]
    assert environment["LOGNAME"] == environment["USER"]
    assert environment["TMPDIR"]
    assert environment["PATH"].startswith("/usr/local/bin:/opt/homebrew/bin:")
    serialized = json.dumps(value).casefold()
    assert "api_key" not in serialized
    assert "llm_api_key" not in serialized


def test_launch_agent_preserves_virtual_environment_python_symlink(
    tmp_path: Path,
) -> None:
    base_python = tmp_path / "python3.11"
    base_python.touch()
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(base_python)

    value = build_launch_agent(
        label=DESKTOP_LABEL,
        module="app",
        python=venv_python,
        repository_root=tmp_path / "repository",
        data_root=tmp_path / "private-data",
    )

    assert value["ProgramArguments"][0] == str(venv_python)


def test_runtime_install_relies_on_run_at_load_without_blocking_kickstart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = tmp_path / "agents" / f"{DESKTOP_LABEL}.plist"
    calls: list[tuple[tuple[str, ...], bool]] = []
    monkeypatch.setattr("app.runtime.agent_path", lambda _label: agent)
    monkeypatch.setattr(
        "app.runtime._launchctl",
        lambda *arguments, check=True: calls.append((arguments, check)),
    )

    install_service(
        "desktop",
        repository_root=tmp_path / "repository",
        data_root=tmp_path / "private-data",
        python=tmp_path / ".venv" / "bin" / "python",
    )

    assert calls == [
        (("bootout", f"gui/{os.getuid()}", str(agent)), False),
        (("bootstrap", f"gui/{os.getuid()}", str(agent)), True),
    ]


def test_runtime_restart_rotates_oversized_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "logs" / f"{DESKTOP_LABEL}.log"
    log.parent.mkdir()
    with log.open("wb") as handle:
        handle.truncate(MAX_LOG_BYTES + 1)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "app.runtime._launchctl",
        lambda *arguments, **_kwargs: calls.append(arguments),
    )

    restart_service("desktop", data_root=tmp_path)

    assert not log.exists()
    assert log.with_suffix(".log.1").stat().st_size == MAX_LOG_BYTES + 1
    assert calls == [("kickstart", "-k", f"gui/{os.getuid()}/{DESKTOP_LABEL}")]


class FakeStyleClient:
    enabled = True

    def polish(self, *, title: str, body: str, mode: str) -> PolishResult:
        return PolishResult(
            title=f"如果 {title} 会拐弯",
            markdown="## 写 / Writing\n\n候选正文。\n\n## 写在最后 / Afterword\n\n回来。",
            image_suggestions=("第二段后放一张无语猫咪",),
            mode=mode,
        )

    def summarize(self, items) -> str:
        return "## 本周概览\n\nAI 看见了一条反复出现的线索。"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(content_root=tmp_path, enable_scheduler=False))


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/", "今天想接住什么"),
        ("/assistant", "个人助手"),
        ("/ideas", "想法库"),
        ("/knowledge", "核心知识图"),
        ("/reviews", "周回顾"),
        ("/articles", "文章创作"),
        ("/publish", "公众号发布台"),
        ("/video", "视频创作"),
        ("/career", "求职驾驶舱"),
        ("/career/profile", "候选人档案"),
        ("/career/documents", "私有文档"),
        ("/career/projects", "项目证据库"),
        ("/career/resumes", "简历工作室"),
        ("/career/jobs", "职位跟踪"),
        ("/learning", "Agent 应用开发路线"),
        ("/income", "收入面板"),
        ("/income/entries", "收支记录"),
        ("/settings/backups", "私有备份"),
        ("/settings/runtime", "本机运行状态"),
        ("/trash", "回收站"),
        ("/settings", "本地内容"),
    ],
)
def test_all_workspace_pages_render(
    client: TestClient,
    path: str,
    marker: str,
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert marker in response.text


def test_static_assets_are_local_and_available(client: TestClient) -> None:
    for path, marker in (
        ("/static/styles/base.css", "--cyan"),
        ("/static/styles/knowledge-system.css", ".knowledge"),
        ("/static/styles/assistant.css", ".assistant"),
        ("/static/styles/income.css", ".income-kpis"),
        ("/static/publishing.css", ".publish-layout"),
        ("/static/publishing.js", "ClipboardItem"),
        ("/static/knowledge.js", "forceSimulation"),
        ("/static/vendor/d3.min.js", "https://d3js.org v7.9.0"),
        ("/static/vendor/htmx.min.js", "var htmx="),
        ("/static/vendor/mathjax/tex-svg.js", "MathJax"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text


def test_publishing_script_embeds_images_and_keeps_clipboard_fallback(
    client: TestClient,
) -> None:
    script = client.get("/static/publishing.js")

    assert script.status_code == 200
    assert "blobToDataUrl" in script.text
    assert '"text/html"' in script.text
    assert '"text/plain"' in script.text
    assert "document.execCommand(\"copy\")" in script.text
    assert "张图片需手动上传" in script.text
    assert "normalizeExportNode" in script.text
    assert "cleanInlineStyle" in script.text
    assert "prepared.node.outerHTML" in script.text


def test_private_content_assets_are_not_part_of_static_mount(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "article.png").write_bytes(b"\x89PNG\r\n\x1a\nprivate")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    assert client.get("/assets/article.png").status_code == 200
    assert client.get("/static/images/article.png").status_code == 404
    assert client.get("/static/images/unfinished-model.png").status_code == 404
    assert client.get("/assets/../article.png").status_code == 404


def test_quick_capture_requires_only_body_and_stays_private(
    client: TestClient,
) -> None:
    saved = client.post(
        "/ideas",
        data={"body": "突然觉得，散步是把脑子重新摇匀。"},
        follow_redirects=True,
    )

    assert saved.status_code == 200
    assert "想法已落进本地 Markdown" in saved.text
    assert "突然觉得，散步是把脑子重新摇匀" in saved.text
    assert client.get("/garden").status_code == 404
    assert saved.url.query.decode() == "saved=created&view=pending"


def test_workspace_groups_search_and_partial(tmp_path: Path) -> None:
    create_item(tmp_path, body="待整理的散步灵感。", title="散步灵感")
    create_item(
        tmp_path,
        body="正在长大的文章。",
        title="参数的碎碎念",
        kind="article",
    )
    public = create_item(tmp_path, body="已经公开的月光。", title="公开月光")
    archived = create_item(tmp_path, body="归档的石头。", title="归档石头")
    set_item_status(tmp_path, public.id, "published")
    set_item_status(tmp_path, archived.id, "archived")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    workspace = client.get("/", params={"view": "pending"})
    pending = client.get("/partials/workspace-feed", params={"view": "pending"})
    organized = client.get("/partials/workspace-feed", params={"view": "organized"})
    all_items = client.get("/partials/workspace-feed", params={"view": "all"})
    searched = client.get(
        "/partials/workspace-feed",
        params={"view": "all", "q": "月光"},
    )
    partial = client.get(
        "/partials/workspace-feed",
        params={"view": "all", "q": "参数"},
        headers={"HX-Request": "true"},
    )

    assert "创作流" in workspace.text
    assert "本周回顾" in workspace.text
    assert "文章草稿" in workspace.text
    assert "散步灵感" in pending.text
    assert "参数的碎碎念" not in pending.text
    assert "参数的碎碎念" not in organized.text
    assert "公开月光" in organized.text
    assert "归档石头" not in organized.text
    for title in ("散步灵感", "公开月光", "归档石头"):
        assert title in all_items.text
    assert "参数的碎碎念" not in all_items.text
    assert "公开月光" in searched.text and "归档石头" not in searched.text
    assert '<section id="workspace-feed"' in partial.text
    assert "<!doctype html>" not in partial.text.lower()
    assert partial.headers["HX-Push-Url"] == "/?view=all&q=%E5%8F%82%E6%95%B0"


def test_global_search_is_synced_on_start_and_after_successful_write(
    tmp_path: Path,
) -> None:
    create_item(tmp_path, body="启动前就存在的银河。", title="银河")
    article = create_item(
        tmp_path,
        body="独立文章正文。",
        title="独立文章",
        kind="article",
    )
    review = create_item(
        tmp_path,
        body="中性回顾正文。",
        title="中性回顾",
        kind="weekly-review",
    )
    application = create_app(content_root=tmp_path, enable_scheduler=False)
    with TestClient(application) as browser:
        before = browser.get("/search", params={"q": "银河"})
        created = browser.post(
            "/ideas",
            data={"body": "后来又出现一颗流星。", "title": "流星"},
            follow_redirects=False,
        )
        after = browser.get("/search", params={"q": "流星"})
        article_search = browser.get("/search", params={"q": "独立文章"})
        review_search = browser.get("/search", params={"q": "中性回顾"})
        settings = browser.get("/settings/search")

    assert before.status_code == 200 and "银河" in before.text
    assert created.status_code == 303
    assert after.status_code == 200 and "流星" in after.text
    assert f"/articles/{article.id}" in article_search.text
    assert f"/reviews/{review.id}" in review_search.text
    assert "检索索引" in settings.text


def test_workspace_status_actions_support_htmx_and_plain_forms(tmp_path: Path) -> None:
    target = create_item(tmp_path, body="要改变状态的想法。", title="目标想法")
    untouched = create_item(tmp_path, body="不应该被影响。", title="对照想法")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    htmx = client.post(
        f"/ideas/{target.id}/status",
        data={
            "status": "published",
            "return_to": "workspace",
            "view": "pending",
            "q": "",
        },
        headers={"HX-Request": "true"},
    )
    plain = client.post(
        f"/ideas/{target.id}/status",
        data={
            "status": "archived",
            "return_to": "workspace",
            "view": "all",
            "q": "",
        },
        follow_redirects=True,
    )
    collection = load_items(items_directory(tmp_path))

    assert htmx.status_code == 200
    assert "内容状态已更新" in htmx.text
    assert "目标想法" not in htmx.text
    assert "<!doctype html>" not in htmx.text.lower()
    assert "内容状态已更新" in plain.text
    assert plain.url.query.decode() == "saved=status&view=all&q="
    assert collection.get(target.id).status == "archived"
    assert collection.get(untouched.id).status == "draft"


def test_knowledge_page_is_private_local_and_uses_local_assets(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="只有工作台可以看到的草稿。", title="私人草稿")
    dangerous = create_item(
        tmp_path,
        body="危险标题仍然只能作为文本。",
        title="</script><script>alert('x')</script>",
    )
    subject = create_knowledge_map(
        tmp_path,
        title="技术",
        kind="subject",
        summary="实现机制",
    )
    topic = create_knowledge_map(
        tmp_path,
        title="本地安全",
        kind="topic",
        summary="私人服务的安全边界",
        parent_ids=(subject.id,),
    )
    create_knowledge_card(
        tmp_path,
        title="本地服务需要阻断危险输入",
        body="所有不可信输入都需要转义。",
        card_type="claim",
        subjects=("技术",),
        concepts=("安全",),
        source_ids=(item.id, dangerous.id),
        map_ids=(topic.id,),
    )
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    page = client.get("/knowledge")

    assert page.status_code == 200
    assert client.get("/garden").status_code == 404
    assert "/static/vendor/d3.min.js" in page.text
    assert "/static/knowledge.js" in page.text
    assert "cdn.jsdelivr" not in page.text
    assert f"/ideas/{item.id}" in page.text
    assert "</script><script>alert('x')</script>" not in page.text
    assert "\\u003c/script\\u003e" in page.text
    assert '"type": "concept"' not in page.text


def test_legacy_source_knowledge_writes_are_retired(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="关于选择的一条记录。", title="选择")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    rejected = client.post("/knowledge/analyze")
    saved = client.post(
        f"/ideas/{item.id}/knowledge",
        data={
            "subjects": "哲学，心理学",
            "concepts": "选择，决策",
            "relations": "",
        },
    )
    updated = load_items(items_directory(tmp_path)).get(item.id)

    assert rejected.status_code == 410
    assert "旧版学科元数据分析已经停用" in rejected.text
    assert saved.status_code == 410
    assert "旧版知识字段已停止写入" in saved.text
    assert updated.subjects == ()
    assert updated.body == item.body


def test_desktop_idea_distill_creates_revision_linked_card_without_editing_source(
    tmp_path: Path,
) -> None:
    item = create_item(tmp_path, body="一段仍需保留的原始随想。", title="原始随想")
    subject = create_knowledge_map(
        tmp_path,
        title="哲学",
        kind="subject",
        summary="关于判断与理解。",
    )
    topic = create_knowledge_map(
        tmp_path,
        title="认知与选择",
        kind="topic",
        summary="个体如何形成判断。",
        parent_ids=(subject.id,),
    )
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    page = client.get(f"/ideas/{item.id}/distill")
    created = client.post(
        f"/ideas/{item.id}/distill/cards",
        data={
            "title": "判断来自既有经验",
            "body": "当下判断会被过去经验塑形。",
            "card_type": "claim",
            "map_ids": [topic.id],
            "concepts": "判断,经验",
        },
        follow_redirects=True,
    )

    assert page.status_code == 200 and "把随想整理成可追溯的知识" in page.text
    assert created.status_code == 200 and "知识卡已创建" in created.text
    source = load_items(items_directory(tmp_path)).get(item.id)
    card = next(
        card
        for card in load_knowledge_store(tmp_path).cards
        if card.title == "判断来自既有经验"
    )
    assert source.body == item.body and source.title == item.title
    assert card.source_ids == (item.id,)
    assert card.source_revisions[item.id] == semantic_revision(source)


def test_idea_filters_partial_edit_and_finished_status(
    tmp_path: Path,
) -> None:
    first = create_item(
        tmp_path,
        body="今天去散步。",
        title="散步",
        tags="生活",
        category="路上",
    )
    create_item(tmp_path, body="写一点代码。", title="代码", tags="技术")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    filtered = client.get("/ideas", params={"tag": "生活", "category": "路上"})
    partial = client.get(
        "/partials/ideas",
        params={"q": "散步"},
        headers={"HX-Request": "true"},
    )
    edited = client.post(
        f"/ideas/{first.id}",
        data={
            "title": "散步以后",
            "body": "今天去散步，回来以后脑子清楚了。",
            "tags": "生活，观察",
            "category": "路上",
        },
        follow_redirects=True,
    )
    published = client.post(
        f"/ideas/{first.id}/status",
        data={"status": "published"},
        follow_redirects=True,
    )

    assert "散步" in filtered.text and "代码" not in filtered.text
    assert '<section id="ideas-results"' in partial.text
    assert "<!doctype html>" not in partial.text.lower()
    assert partial.headers["HX-Push-Url"].startswith("/ideas?q=")
    assert "修改已保存" in edited.text
    assert "内容状态已更新" in published.text
    finished = client.get("/partials/workspace-feed", params={"view": "organized"})
    assert "散步以后" in finished.text
    assert "已整理" in finished.text


def test_garden_routes_are_removed(tmp_path: Path) -> None:
    draft = create_item(tmp_path, body="草稿正文", title="草稿")
    archived = create_item(tmp_path, body="归档正文", title="归档")
    set_item_status(tmp_path, archived.id, "archived")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    assert client.get("/garden").status_code == 404
    assert client.get(f"/garden/{draft.id}").status_code == 404
    assert client.get(f"/garden/{archived.id}").status_code == 404


def test_trash_restore_and_confirmed_delete(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="准备被回收。", title="回收测试")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    moved = client.post(f"/ideas/{item.id}/trash", follow_redirects=True)
    rejected = client.post(
        f"/trash/{item.id}/delete",
        data={"confirmation": "删除"},
    )
    restored = client.post(
        f"/trash/{item.id}/restore",
        follow_redirects=True,
    )
    client.post(f"/ideas/{item.id}/trash")
    deleted = client.post(
        f"/trash/{item.id}/delete",
        data={"confirmation": "永久删除"},
        follow_redirects=True,
    )

    assert "内容已移入回收站" in moved.text
    assert rejected.status_code == 422
    assert "请输入“永久删除”" in rejected.text
    assert "内容已恢复到想法库" in restored.text
    assert "内容已永久删除" in deleted.text


def test_review_uses_rule_fallback_and_is_idempotent(tmp_path: Path) -> None:
    create_item(
        tmp_path,
        body="本周的一条记录。",
        now=datetime.now(SHANGHAI),
    )
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    first = client.post("/reviews/generate", follow_redirects=True)
    second = client.post("/reviews/generate", follow_redirects=True)
    schedule = client.post(
        "/reviews/schedule",
        data={"enabled": "on", "weekday": "4", "time": "21:15"},
        follow_redirects=True,
    )

    assert "规则回顾草稿" in first.text
    assert "已经存在" in second.text
    assert "本地定时设置已保存" in schedule.text


def test_review_can_be_generated_from_workspace(tmp_path: Path) -> None:
    create_item(
        tmp_path,
        body="本周工作台里的一条记录。",
        now=datetime.now(SHANGHAI),
    )
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    response = client.post(
        "/reviews/generate",
        data={"return_to": "workspace"},
        follow_redirects=True,
    )

    assert response.url.query.decode() == "saved=fallback&view=pending"
    assert "规则回顾草稿" in response.text
    assert "本周回顾" in response.text


def test_content_types_have_separate_pages_and_publish_boundary(tmp_path: Path) -> None:
    thought = create_item(tmp_path, body="一个普通随想。", title="普通随想")
    article = create_item(
        tmp_path,
        body="一篇独立文章。",
        title="独立文章",
        kind="article",
    )
    review = create_item(
        tmp_path,
        body="一份中性回顾。",
        title="中性回顾",
        kind="weekly-review",
    )
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    ideas = client.get("/ideas")
    articles = client.get("/articles")
    reviews = client.get("/reviews")
    publish = client.get("/publish")

    assert "普通随想" in ideas.text
    assert "独立文章" not in ideas.text and "中性回顾" not in ideas.text
    assert "独立文章" in articles.text and "普通随想" not in articles.text
    assert "中性回顾" in reviews.text and "公众号预览" not in reviews.text
    assert "独立文章" in publish.text
    assert "普通随想" not in publish.text and "中性回顾" not in publish.text
    assert "公众号" not in client.get(f"/ideas/{thought.id}").text

    legacy_article = client.get(f"/ideas/{article.id}", follow_redirects=False)
    legacy_review = client.get(f"/ideas/{review.id}", follow_redirects=False)
    thought_publish = client.get(f"/publish/{thought.id}", follow_redirects=False)
    review_publish = client.get(f"/publish/{review.id}", follow_redirects=False)
    assert legacy_article.headers["location"].endswith(f"/articles/{article.id}")
    assert legacy_review.headers["location"].endswith(f"/reviews/{review.id}")
    assert "article-required" in thought_publish.headers["location"]
    assert "article-required" in review_publish.headers["location"]
    assert client.post(f"/publish/{thought.id}/polish").status_code == 404
    assert client.post(f"/publish/{review.id}/save", data={"title": "x", "markdown": "y"}).status_code == 404


def test_independent_article_crud_and_status(tmp_path: Path) -> None:
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    created = client.post(
        "/articles",
        data={
            "title": "独立写作",
            "body": "## 提纲\n\n只是一份文章提纲。",
            "tags": "创作",
            "category": "文章",
        },
        follow_redirects=True,
    )
    article = next(item for item in load_items(items_directory(tmp_path)).items if item.kind == "article")
    edited = client.post(
        f"/articles/{article.id}",
        data={
            "title": "独立写作完成版",
            "body": "## 正文\n\n已经写完。",
            "tags": "创作，成稿",
            "category": "文章",
            "source_revision": semantic_revision(article),
        },
        follow_redirects=True,
    )
    finished = client.post(
        f"/articles/{article.id}/status",
        data={"status": "published"},
        follow_redirects=True,
    )

    assert created.status_code == 200 and "文章草稿已保存" in created.text
    assert "独立写作完成版" in edited.text
    assert "已成稿" in finished.text
    assert "公众号排版" in finished.text and "创建视频项目" in finished.text
    assert "独立写作完成版" not in client.get("/ideas").text


def test_publish_faithful_polish_and_save_child_article(tmp_path: Path) -> None:
    source = create_item(
        tmp_path,
        body="一段原始文章。",
        title="原始文章",
        kind="article",
    )
    client = TestClient(
        create_app(
            content_root=tmp_path,
            enable_scheduler=False,
            llm_client=FakeStyleClient(),
        ),
    )

    faithful = client.get(f"/publish/{source.id}")
    disclosure = client.post(
        f"/publish/{source.id}/polish",
        data={"mode": "essay"},
    )
    polished = client.post(
        f"/publish/{source.id}/polish",
        data={
            "mode": "essay",
            "outbound_text": json.dumps(
                {"title": source.title, "body": source.body},
                ensure_ascii=False,
            ),
        },
    )
    saved = client.post(
        f"/publish/{source.id}/save",
        data={
            "title": "如果原始文章会拐弯",
            "markdown": "## 写 / Writing\n\n候选正文。",
        },
        follow_redirects=True,
    )

    assert faithful.status_code == 200
    assert 'id="copy-rich-text"' in faithful.text
    assert "一键复制公众号正文" in faithful.text
    assert "标题与摘要请在公众号后台单独填写" in faithful.text
    assert "仅复制当前预览正文与固定署名" in faithful.text
    assert "羽白 · doocs 标准" in faithful.text
    assert "排版设置" in faithful.text
    assert 'name="primary_color"' in faithful.text
    assert ">羽白</p>" in faithful.text
    assert "格式检查" in faithful.text
    assert 'data-preview-width="mobile"' in faithful.text
    assert 'data-preview-width="editor"' in faithful.text
    assert "确认模型外发内容" in disclosure.text
    assert polished.status_code == 200
    assert "第二段后放一张无语猫咪" in polished.text
    assert "保存为文章草稿" in polished.text
    assert "候选稿已保存为新的文章版本" in saved.text
    assert saved.url.path.startswith("/articles/article-")
    assert "一段原始文章" in client.get(f"/articles/{source.id}").text
    assert "如果原始文章会拐弯" in client.get("/articles").text
    assert "如果原始文章会拐弯" not in client.get("/ideas").text


def test_publish_theme_query_is_validated_and_does_not_edit_source(
    tmp_path: Path,
) -> None:
    source = create_item(
        tmp_path,
        body="## 章节\n\n正文。",
        title="主题参数",
        kind="article",
    )
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    customized = client.get(
        f"/publish/{source.id}",
        params={
            "primary_color": "#123456",
            "font_size": "18",
            "font_family": "serif",
            "indent": "1",
            "justify": "0",
        },
    )
    rejected = client.get(
        f"/publish/{source.id}",
        params={"primary_color": "red;position:fixed", "font_size": "99"},
    )

    assert customized.status_code == 200
    assert "background:#123456" in customized.text
    assert "text-indent:2em" in customized.text
    assert "font-size:18px;line-height:1.75" in customized.text
    assert 'value="#1597A8"' in rejected.text
    assert "position:fixed" not in rejected.text
    assert client.get(f"/articles/{source.id}").text.count("正文。") >= 1


def test_polish_is_hidden_when_model_is_not_configured(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="原文。", kind="article")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    response = client.get(f"/publish/{item.id}")
    rejected = client.post(f"/publish/{item.id}/polish", data={"mode": "auto"})

    assert "尚未配置模型" in response.text
    assert rejected.status_code == 422
    assert "忠实排版仍可正常使用" in rejected.text


def test_missing_pages_use_html_404(client: TestClient) -> None:
    for path in (
        "/does-not-exist",
        "/ideas/missing",
        "/publish/missing",
        "/garden/missing",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert "这条念头" in response.text


def test_default_app_uses_private_data_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(tmp_path))
    app = create_app(enable_scheduler=False)
    assert app.state.data_root == tmp_path
    assert app.state.content_root == tmp_path / "content"
    assert app.state.content_root != REPO_ROOT / "content"


def test_local_security_rejects_bad_hosts_proxy_headers_and_missing_csrf(
    tmp_path: Path,
) -> None:
    app = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=True,
    )
    client = TestClient(app)
    remote_client = TestClient(app, client=("198.51.100.10", 50000))

    bad_host = client.get("/", headers={"host": "attacker.example"})
    proxied = client.get("/", headers={"x-forwarded-for": "127.0.0.1"})
    remote = remote_client.get("/", headers={"host": "127.0.0.1:8765"})
    page = client.get("/")
    missing = client.post("/ideas", data={"body": "不能跨站写入"})
    token = client.cookies.get("pcw_csrf")
    accepted = client.post(
        "/ideas",
        data={"body": "经过本地确认", "csrf_token": token},
        follow_redirects=False,
    )

    assert bad_host.status_code == 403
    assert proxied.status_code == 403
    assert remote.status_code == 403
    assert page.headers["Cache-Control"] == "no-store"
    assert page.headers["X-Frame-Options"] == "DENY"
    assert missing.status_code == 403
    assert accepted.status_code == 303
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_local_security_accepts_chrome_opaque_origin_but_rejects_remote_origin(
    tmp_path: Path,
) -> None:
    app = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=True,
    )
    client = TestClient(app)
    client.get("/")
    token = client.cookies.get("pcw_csrf")
    form = {"body": "Chrome 本地表单", "csrf_token": token}

    local = client.post(
        "/ideas",
        data=form,
        headers={"origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    opaque = client.post(
        "/ideas",
        data={**form, "body": "Chrome 不透明来源表单"},
        headers={"origin": "null"},
        follow_redirects=False,
    )
    remote = client.post(
        "/ideas",
        data={**form, "body": "远程跨站表单"},
        headers={"origin": "https://attacker.example"},
        follow_redirects=False,
    )

    assert local.status_code == 303
    assert opaque.status_code == 303
    assert remote.status_code == 403
    assert remote.json() == {"detail": "拒绝跨站请求"}
