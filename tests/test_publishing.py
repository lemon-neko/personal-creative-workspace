from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.publishing import (
    PublishingSource,
    WeChatRenderer,
    resolve_publishing_source,
)
from app.workspace import save_fragment


def test_wechat_renderer_handles_rich_markdown_and_formulas() -> None:
    source = PublishingSource(
        source_type="note",
        source_id="rich-note",
        title="富文本转换",
        summary="用于检查公众号格式。",
        markdown="""## 二级标题

正文包含 **强调**、`inline_code` 和 [链接](https://example.com)。

> 一条引用。

1. 第一项
2. 第二项

```python
print("hello")
```

| 名称 | 值 |
|---|---|
| temperature | 0.8 |

行内公式 \\(T < 1\\)。

$$
QK^\\top
$$

![示意图](https://example.com/diagram.png)
""",
    )

    rendered = WeChatRenderer().render(source)

    assert rendered.platform == "wechat"
    assert 'style="margin:38px 0 16px;' in rendered.html
    assert "<pre style=" in rendered.html
    assert "<table style=" in rendered.html
    assert 'data-formula-source="\\(T &lt; 1\\)"' in rendered.html
    assert 'data-formula-display="block"' in rendered.html
    assert "<img" in rendered.html
    assert len(rendered.warnings) == 2
    assert "富文本转换" in rendered.plain_text
    assert "print(\"hello\")" in rendered.plain_text


def test_wechat_renderer_escapes_raw_html_and_dangerous_links() -> None:
    source = PublishingSource(
        source_type="note",
        source_id="safe-note",
        title="<unsafe>",
        summary="<script>alert('summary')</script>",
        markdown="""<script>alert("body")</script>

[危险链接](javascript:alert("bad"))
""",
    )

    rendered = WeChatRenderer().render(source)

    assert "<script>" not in rendered.html
    assert "&lt;unsafe&gt;" in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert 'href="javascript:' not in rendered.html


def test_resolve_note_and_topic_sources_without_path_escape(tmp_path: Path) -> None:
    note = save_fragment(
        tmp_path,
        title="草稿也能转换",
        body="草稿正文。",
        captured_on=date(2026, 7, 31),
    )
    topics = tmp_path / "topics"
    topics.mkdir()
    (topics / "transformer.md").write_text(
        "# Transformer 专题\n\n专题摘要。\n\n## 正文\n\n内容。",
        encoding="utf-8",
    )

    note_source = resolve_publishing_source(tmp_path, "note", note.id)
    topic_source = resolve_publishing_source(tmp_path, "topic", "transformer")

    assert note_source is not None
    assert note_source.title == "草稿也能转换"
    assert topic_source is not None
    assert topic_source.title == "Transformer 专题"
    assert not topic_source.markdown.startswith("# Transformer")
    assert resolve_publishing_source(tmp_path, "topic", "../secret") is None
    assert resolve_publishing_source(tmp_path, "missing", note.id) is None


def test_publish_pages_support_note_draft_and_topic() -> None:
    client = TestClient(create_app(enable_scheduler=False))

    for path, marker in (
        (
            "/workspace/publish/note/attention-temperature",
            "Temperature 如何改变注意力分布",
        ),
        (
            "/workspace/publish/note/next-topic-draft",
            "下一步：从字符级模型走向 tokenizer",
        ),
        (
            "/workspace/publish/topic/transformer",
            "从零理解 Transformer",
        ),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text
        assert 'id="copy-rich-text"' in response.text
        assert 'id="download-html"' in response.text
        assert "/static/publishing.css" in response.text
        assert "/static/publishing.js" in response.text
        assert "https://cdn" not in response.text


def test_publish_page_rejects_unknown_sources() -> None:
    client = TestClient(create_app(enable_scheduler=False))

    missing = client.get("/workspace/publish/note/does-not-exist")
    invalid_type = client.get("/workspace/publish/other/transformer")

    assert missing.status_code == 404
    assert invalid_type.status_code == 404
    assert "这一页还没有被记录" in missing.text


def test_conversion_actions_are_exposed_from_content_pages() -> None:
    client = TestClient(create_app(enable_scheduler=False))

    note = client.get("/notes/attention-temperature")
    topic = client.get("/topics/transformer")

    assert "/workspace/publish/note/attention-temperature" in note.text
    assert "/workspace/publish/topic/transformer" in topic.text
