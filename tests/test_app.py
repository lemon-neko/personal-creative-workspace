from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.llm import PolishResult
from app.main import REPO_ROOT, create_app
from app.workspace import create_item, set_item_status


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
        return "## 本周 / This Week\n\nAI 看见了一条反复出现的线索。"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(content_root=tmp_path, enable_scheduler=False))


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/", "脑子里刚刚"),
        ("/ideas", "想法库"),
        ("/reviews", "周回顾"),
        ("/publish", "发布适配"),
        ("/garden", "愿意被看见的念头"),
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
        ("/static/vendor/htmx.min.js", "var htmx="),
        ("/static/vendor/mathjax/tex-svg.js", "MathJax"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text


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
    assert "突然觉得，散步是把脑子重新摇匀" not in client.get("/garden").text


def test_idea_filters_partial_edit_status_and_public_visibility(
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
    assert "散步以后" in client.get("/garden").text
    assert client.get(f"/garden/{first.id}").status_code == 200


def test_draft_and_archived_items_never_leak_to_garden(tmp_path: Path) -> None:
    draft = create_item(tmp_path, body="草稿正文", title="草稿")
    archived = create_item(tmp_path, body="归档正文", title="归档")
    set_item_status(tmp_path, archived.id, "archived")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    garden = client.get("/garden")

    assert "草稿正文" not in garden.text
    assert "归档正文" not in garden.text
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
    polished = client.post(
        f"/publish/{source.id}/polish",
        data={"mode": "essay"},
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
    assert "羽白 | AI Engineer" in faithful.text
    assert polished.status_code == 200
    assert "第二段后放一张无语猫咪" in polished.text
    assert "保存为文章草稿" in polished.text
    assert "候选稿已保存为新的文章草稿" in saved.text
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


def test_default_app_uses_repository_content() -> None:
    app = create_app(enable_scheduler=False)
    assert app.state.content_root == REPO_ROOT / "content"
