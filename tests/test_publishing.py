from __future__ import annotations

from pathlib import Path

from app.publishing import (
    PublishingSource,
    WeChatRenderer,
    resolve_publishing_source,
)
from app.publishing_theme import DEFAULT_PRIMARY_COLOR, WechatThemeConfig
from app.workspace import create_item


def test_wechat_renderer_uses_doocs_standard_theme_and_rich_markdown() -> None:
    source = PublishingSource(
        source_id="rich-item",
        kind="article",
        title="有趣，但先别急着抽象",
        summary="用于检查公众号格式。",
        markdown="""## 写 / Writing

正文包含 **判断**、`inline_code` 和 [链接](https://example.com)。

**这一整句是需要停下来看的判断。**

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
    assert "background:#1597A8;color:#FFFFFF" in rendered.html
    assert "font-size:16px;line-height:1.75" in rendered.html
    assert "border-left:4px solid #1597A8" in rendered.html
    assert "background:#F7F7F7" in rendered.html
    assert "<aside" not in rendered.html
    assert "<p style=" in rendered.html
    assert "<pre style=" in rendered.html
    assert "<table style=" in rendered.html
    assert "table-layout:fixed" in rendered.html
    assert "word-break:break-word" in rendered.html
    assert 'data-formula-source="\\(T &lt; 1\\)"' in rendered.html
    assert "<img" in rendered.html
    assert ">示意图</small>" in rendered.html
    assert "有趣，但先别急着抽象" not in rendered.html
    assert "用于检查公众号格式" not in rendered.html
    assert "有趣，但先别急着抽象" not in rendered.plain_text
    assert "用于检查公众号格式" not in rendered.plain_text
    assert ">羽白</p>" in rendered.html
    assert "AI Engineer · Builder · Observer" in rendered.html
    assert "用技术观察世界，也记录成长的痕迹" in rendered.html
    assert len(rendered.warnings) == 2
    assert rendered.diagnostics[0].code == "standard-theme"
    assert rendered.semantic_html.startswith("<h2>")
    assert rendered.export_html == rendered.html
    assert "print(\"hello\")" in rendered.plain_text


def test_renderer_removes_duplicate_title_without_rewriting_article_structure() -> None:
    source = PublishingSource(
        source_id="structured",
        kind="article",
        title="如果模型也会忘记",
        summary="",
        markdown="""# 如果模型也会忘记

---

## 01

### 记忆并不是仓库

正文从这里开始。
""",
    )

    rendered = WeChatRenderer().render(source)

    assert "如果模型也会忘记" not in rendered.html
    assert "<mark" not in rendered.html
    assert "<header" not in rendered.html
    assert "<h2>01</h2>" in rendered.semantic_html
    assert "<h3>记忆并不是仓库</h3>" in rendered.semantic_html
    assert "01" in rendered.plain_text
    assert "记忆并不是仓库" in rendered.plain_text
    assert {value.code for value in rendered.diagnostics} == {
        "standard-theme",
        "duplicate-title",
    }


def test_renderer_keeps_non_duplicate_leading_h1_as_opening_heading() -> None:
    source = PublishingSource(
        source_id="opening",
        kind="thought",
        title="后台标题",
        summary="",
        markdown="# 正文里的引题\n\n短正文。",
    )

    rendered = WeChatRenderer().render(source)

    assert "正文里的引题" in rendered.html
    assert "border-bottom:2px solid #1597A8" in rendered.html
    assert "text-align:center" in rendered.html
    assert all(value.code != "duplicate-title" for value in rendered.diagnostics)


def test_renderer_reports_long_paragraphs_empty_headings_and_wide_tables() -> None:
    long_text = "这是一个需要人工检查的长段落。" * 20
    source = PublishingSource(
        source_id="diagnostics",
        kind="article",
        title="格式检查",
        summary="",
        markdown=(
            f"{long_text}\n\n##\n\n"
            "| 一 | 二 | 三 | 四 | 五 |\n"
            "|---|---|---|---|---|\n"
            "| 1 | 2 | 3 | 4 | 5 |"
        ),
    )

    rendered = WeChatRenderer().render(source)
    codes = {value.code for value in rendered.diagnostics}

    assert {"long-paragraphs", "empty-headings", "wide-table"} <= codes
    warnings = [value for value in rendered.diagnostics if value.code != "standard-theme"]
    assert all(value.tone == "warning" for value in warnings)


def test_theme_controls_only_change_export_presentation() -> None:
    source = PublishingSource(
        source_id="theme",
        kind="article",
        title="主题测试",
        summary="",
        markdown="## 章节\n\n正文。",
    )
    custom = WechatThemeConfig.from_mapping(
        {
            "primary_color": "#123456",
            "font_family": "serif",
            "font_size": "18",
            "indent": "1",
            "justify": "0",
        },
    )

    default_rendered = WeChatRenderer().render(source)
    custom_rendered = WeChatRenderer().render(source, custom)

    assert default_rendered.semantic_html == custom_rendered.semantic_html
    assert default_rendered.export_html != custom_rendered.export_html
    assert "background:#123456" in custom_rendered.export_html
    assert "font-size:18px;line-height:1.75" in custom_rendered.export_html
    assert "text-indent:2em" in custom_rendered.export_html
    assert "text-align:left" in custom_rendered.export_html
    assert source.markdown == "## 章节\n\n正文。"


def test_theme_controls_reject_unapproved_values() -> None:
    config = WechatThemeConfig.from_mapping(
        {
            "primary_color": "red;position:fixed",
            "font_family": "remote-font",
            "font_size": "99",
        },
    )

    assert config.primary_color == DEFAULT_PRIMARY_COLOR
    assert config.font_family == "sans"
    assert config.font_size == 16


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
    assert "&lt;unsafe&gt;" not in rendered.html
    assert "alert('summary')" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert 'href="javascript:' not in rendered.html
    assert "unsafe-links" in {value.code for value in rendered.diagnostics}


def test_renderer_maps_portable_obsidian_assets_to_protected_route() -> None:
    source = PublishingSource(
        source_id="asset",
        kind="thought",
        title="本地图片",
        summary="",
        markdown="![配图](assets/local-image.png)",
    )

    rendered = WeChatRenderer().render(source)

    assert 'src="/assets/local-image.png"' in rendered.export_html
    assert "配图" in rendered.export_html


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
