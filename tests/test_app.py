from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import REPO_ROOT, create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/", "把学过的东西"),
        ("/notes", "学习记录"),
        ("/notes/attention-temperature", "Temperature 如何改变注意力分布"),
        ("/topics/transformer", "从零理解 Transformer"),
        ("/about", "为什么做这本学习手记"),
    ],
)
def test_public_pages_render(client: TestClient, path: str, marker: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert marker in response.text


def test_static_assets_are_local_and_available(client: TestClient) -> None:
    styles = client.get("/static/styles.css")
    htmx = client.get("/static/vendor/htmx.min.js")
    mathjax = client.get("/static/vendor/mathjax/tex-svg.js")
    assert styles.status_code == 200
    assert "--accent" in styles.text
    assert htmx.status_code == 200
    assert "var htmx=" in htmx.text
    assert mathjax.status_code == 200
    assert "MathJax" in mathjax.text


def test_home_and_notes_hide_drafts(client: TestClient) -> None:
    for path in ("/", "/notes"):
        response = client.get(path)
        assert "next-topic-draft" not in response.text
        assert "下一步：从字符级模型走向 tokenizer" not in response.text

    draft = client.get("/notes/next-topic-draft")
    assert draft.status_code == 404
    assert "这一页还没有被记录" in draft.text


def test_regular_get_filters_notes_without_javascript(client: TestClient) -> None:
    response = client.get("/notes", params={"tag": "梯度"})
    assert response.status_code == 200
    assert "残差连接不只是" in response.text
    assert "Temperature 如何改变" not in response.text
    assert '<option value="梯度" selected>' in response.text


def test_topic_filter_and_empty_result(client: TestClient) -> None:
    topic = client.get("/notes", params={"topic": "transformer"})
    empty = client.get("/notes", params={"topic": "missing"})
    assert "共 2 条已发布记录" in topic.text
    assert "没有匹配的记录" in empty.text


def test_htmx_partial_returns_list_and_push_url(client: TestClient) -> None:
    response = client.get(
        "/partials/notes",
        params={"tag": "Self-Attention"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert '<section id="notes-results"' in response.text
    assert "<!doctype html>" not in response.text.lower()
    assert "Temperature 如何改变" in response.text
    assert "残差连接不只是" not in response.text
    assert response.headers["HX-Push-Url"].startswith("/notes?tag=")


def test_missing_page_uses_html_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "这一页还没有被记录" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_diagnostics_do_not_block_valid_content(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "good.md").write_text(
        """---
id: good
title: 正常记录
date: 2026-07-30
status: published
summary: 正常摘要
tags: [测试]
topic: test
---

正常正文。
""",
        encoding="utf-8",
    )
    (notes_dir / "bad.md").write_text("---\nid: bad\n---\n", encoding="utf-8")

    response = TestClient(create_app(content_root=tmp_path)).get("/notes")
    assert response.status_code == 200
    assert "正常记录" in response.text
    assert "内容诊断 · 1 个文件未加载" in response.text
    assert "缺少必填字段" in response.text


def test_default_app_uses_repository_content() -> None:
    app = create_app()
    assert app.state.content_root == REPO_ROOT / "content"
