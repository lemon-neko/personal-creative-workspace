from __future__ import annotations

from pathlib import Path

from app.publishing import (
    PublishingSource,
    WeChatRenderer,
    resolve_publishing_source,
)
from app.workspace import create_item


def test_wechat_renderer_uses_fantasy_stack_theme_and_rich_markdown() -> None:
    source = PublishingSource(
        source_id="rich-item",
        kind="article",
        title="有趣，但先别急着抽象",
        summary="用于检查公众号格式。",
        markdown="""## 写 / Writing

正文包含 **判断**、`inline_code` 和 [链接](https://example.com)。

> 一条引用。

1. 第一项
2. 第二项

```python
print("hello")
```

| 名称 | 值 |
|---|---|
| mood | abstract |

行内公式 \\(T < 1\\)。

$$
QK^\\top
$$

![示意图](https://example.com/image.png)
""",
    )

    rendered = WeChatRenderer().render(source)

    assert rendered.platform == "wechat"
    assert "border-top:1px dotted" in rendered.html
    assert "color:#0794ae" in rendered.html
    assert "<pre style=" in rendered.html
    assert "<table style=" in rendered.html
    assert 'data-formula-source="\\(T &lt; 1\\)"' in rendered.html
    assert "<img" in rendered.html
    assert "羽白 | AI Engineer · Builder · Observer" in rendered.html
    assert "用技术观察世界，也记录成长的痕迹" in rendered.html
    assert len(rendered.warnings) == 2
    assert "print(\"hello\")" in rendered.plain_text


def test_renderer_escapes_html_and_removes_dangerous_links() -> None:
    source = PublishingSource(
        source_id="safe",
        kind="thought",
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


def test_resolve_source_supports_every_item_kind(tmp_path: Path) -> None:
    thought = create_item(tmp_path, body="草稿正文。", title="草稿也能转换")
    article = create_item(
        tmp_path,
        body="文章正文。",
        title="文章",
        kind="article",
        parent_id=thought.id,
    )

    thought_source = resolve_publishing_source(tmp_path, thought.id)
    article_source = resolve_publishing_source(tmp_path, article.id)

    assert thought_source is not None
    assert thought_source.title == "草稿也能转换"
    assert article_source is not None
    assert article_source.kind == "article"
    assert resolve_publishing_source(tmp_path, "../secret") is None
