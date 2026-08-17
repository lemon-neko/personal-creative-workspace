from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.content import load_items
from app.llm import PolishResult
from app.knowledge_store import create_knowledge_card, create_knowledge_map
from app.main import REPO_ROOT, create_app
from app.workspace import create_item, items_directory, set_item_status


SHANGHAI = ZoneInfo("Asia/Shanghai")


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
        ("/ideas", "想法库"),
        ("/knowledge", "核心知识图"),
        ("/reviews", "周回顾"),
        ("/publish", "发布适配"),
        ("/video", "视频创作"),
        ("/career", "求职驾驶舱"),
        ("/career/profile", "候选人档案"),
        ("/career/documents", "私有文档"),
        ("/career/projects", "项目证据库"),
        ("/career/resumes", "简历版本"),
        ("/career/jobs", "职位跟踪"),
        ("/learning", "技能与学习任务"),
        ("/learning/campaigns/agent-reliability-arena", "30-DAY PROJECT CAMPAIGN"),
        ("/settings/backups", "私有备份"),
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
        ("/static/styles.css", "--cyan"),
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
    articles = client.get("/partials/workspace-feed", params={"view": "articles"})
    published = client.get("/partials/workspace-feed", params={"view": "published"})
    all_items = client.get("/partials/workspace-feed", params={"view": "all"})
    searched = client.get(
        "/partials/workspace-feed",
        params={"view": "all", "q": "月光"},
    )
    partial = client.get(
        "/partials/workspace-feed",
        params={"view": "articles", "q": "参数"},
        headers={"HX-Request": "true"},
    )

    assert "创作流" in workspace.text
    assert "本周回顾" in workspace.text
    assert "文章草稿" in workspace.text
    assert "散步灵感" in pending.text
    assert "参数的碎碎念" not in pending.text
    assert "参数的碎碎念" in articles.text
    assert "散步灵感" not in articles.text
    assert "公开月光" in published.text
    assert "归档石头" not in published.text
    for title in ("散步灵感", "参数的碎碎念", "公开月光", "归档石头"):
        assert title in all_items.text
    assert "公开月光" in searched.text and "归档石头" not in searched.text
    assert '<section id="workspace-feed"' in partial.text
    assert "<!doctype html>" not in partial.text.lower()
    assert partial.headers["HX-Push-Url"] == "/?view=articles&q=%E5%8F%82%E6%95%B0"


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
    finished = client.get("/partials/workspace-feed", params={"view": "published"})
    assert "散步以后" in finished.text
    assert "已成稿" in finished.text


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


def test_publish_faithful_polish_and_save_child_article(tmp_path: Path) -> None:
    source = create_item(tmp_path, body="一段原始想法。", title="原始想法")
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
            "title": "如果原始想法会拐弯",
            "markdown": "## 写 / Writing\n\n候选正文。",
        },
        follow_redirects=True,
    )

    assert faithful.status_code == 200
    assert 'id="copy-rich-text"' in faithful.text
    assert "一键复制公众号正文" in faithful.text
    assert "标题与摘要请在公众号后台单独填写" in faithful.text
    assert "复制正文与固定署名，不包含标题和摘要" in faithful.text
    assert "羽白标准版" in faithful.text
    assert "羽白 | AI Engineer" in faithful.text
    assert "确认模型外发内容" in disclosure.text
    assert polished.status_code == 200
    assert "第二段后放一张无语猫咪" in polished.text
    assert "保存为文章草稿" in polished.text
    assert "候选稿已保存为新的文章草稿" in saved.text
    assert "view=articles" in saved.url.query.decode()
    assert "一段原始想法" in client.get(f"/ideas/{source.id}").text
    assert "如果原始想法会拐弯" in client.get("/ideas").text


def test_polish_is_hidden_when_model_is_not_configured(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="原文。")
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
