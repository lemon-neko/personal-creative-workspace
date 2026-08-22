"""Publishing sources and the doocs-inspired WeChat conversion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.content import load_items, render_markdown
from app.publishing_preprocess import (
    BLOCK_MATH,
    INLINE_MATH,
    PreparedMarkdown,
    prepare_markdown,
)
from app.publishing_theme import (
    WechatThemeConfig,
    apply_theme,
    restore_formulas,
    wrap_article,
)
from app.workspace import items_directory


PLATFORM_WECHAT = "wechat"


@dataclass(frozen=True)
class PublishingSource:
    """One content item prepared for a platform renderer."""

    source_id: str
    kind: str
    title: str
    summary: str
    markdown: str


@dataclass(frozen=True)
class LayoutDiagnostic:
    """One deterministic observation about the article layout."""

    code: str
    message: str
    tone: str = "info"


@dataclass(frozen=True)
class RenderedArticle:
    """Semantic and final WeChat HTML from one conversion run."""

    platform: str
    title: str
    semantic_html: str
    export_html: str
    plain_text: str
    warnings: tuple[str, ...]
    diagnostics: tuple[LayoutDiagnostic, ...]
    theme: WechatThemeConfig

    @property
    def html(self) -> str:
        """Backward-compatible name for the final preview/export body."""

        return self.export_html


class PlatformRenderer(Protocol):
    platform: str

    def render(
        self,
        source: PublishingSource,
        theme: WechatThemeConfig | None = None,
    ) -> RenderedArticle: ...


class _PlainTextParser(HTMLParser):
    BREAK_TAGS = {
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line).strip()


def _plain_text(html: str) -> str:
    parser = _PlainTextParser()
    parser.feed(html)
    parser.close()
    return parser.text()


def _layout_diagnostics(
    prepared: PreparedMarkdown,
) -> tuple[LayoutDiagnostic, ...]:
    diagnostics = [
        LayoutDiagnostic(
            "standard-theme",
            "已应用 doocs/md 经典结构与羽白青标准主题。",
        ),
    ]
    if prepared.removed_duplicate_title:
        diagnostics.append(
            LayoutDiagnostic(
                "duplicate-title",
                "已移除与公众号标题重复的正文一级标题。",
            ),
        )
    if prepared.image_count:
        diagnostics.append(
            LayoutDiagnostic(
                "images",
                f"包含 {prepared.image_count} 张图片，复制时将尝试内嵌。",
            ),
        )
    if prepared.formulas:
        diagnostics.append(
            LayoutDiagnostic(
                "formulas",
                f"包含 {len(prepared.formulas)} 个公式，复制时将转换为 PNG。",
            ),
        )
    if prepared.stripped_private_links:
        diagnostics.append(
            LayoutDiagnostic(
                "private-links",
                f"已移除 {prepared.stripped_private_links} 个私人 Vault 路径。",
            ),
        )
    if prepared.unsafe_links:
        diagnostics.append(
            LayoutDiagnostic(
                "unsafe-links",
                f"已移除 {prepared.unsafe_links} 个不安全或不受支持的链接。",
                "warning",
            ),
        )
    if prepared.long_paragraphs:
        diagnostics.append(
            LayoutDiagnostic(
                "long-paragraphs",
                f"发现 {prepared.long_paragraphs} 个超长段落，建议发布前人工分段。",
                "warning",
            ),
        )
    if prepared.empty_headings:
        diagnostics.append(
            LayoutDiagnostic(
                "empty-headings",
                f"发现 {prepared.empty_headings} 个空标题，请回到原文补充或删除。",
                "warning",
            ),
        )
    if prepared.wide_tables:
        diagnostics.append(
            LayoutDiagnostic(
                "wide-table",
                "存在超过四列的表格，已强制换行但仍建议在手机预览检查。",
                "warning",
            ),
        )
    return tuple(diagnostics)


def resolve_publishing_source(
    content_root: Path,
    source_id: str,
) -> PublishingSource | None:
    item = load_items(items_directory(content_root)).get(source_id)
    if item is None:
        return None
    return PublishingSource(
        source_id=item.id,
        kind=item.kind,
        title=item.title,
        summary=item.summary,
        markdown=item.body,
    )


class WeChatRenderer:
    """Render safe Markdown through semantic, theme and export stages."""

    platform = PLATFORM_WECHAT

    def render(
        self,
        source: PublishingSource,
        theme: WechatThemeConfig | None = None,
    ) -> RenderedArticle:
        config = theme or WechatThemeConfig()
        prepared = prepare_markdown(source.markdown, source.title)

        semantic_base = render_markdown(prepared.markdown)
        semantic_html = restore_formulas(semantic_base, prepared.formulas)

        themed_body = apply_theme(semantic_base, config)
        themed_body = restore_formulas(themed_body, prepared.formulas)
        export_html = wrap_article(themed_body, config)

        warnings: list[str] = []
        if BLOCK_MATH.search(source.markdown) or INLINE_MATH.search(source.markdown):
            warnings.append("包含公式：复制时会尝试转换为 PNG，请粘贴后检查清晰度。")
        if prepared.image_count:
            warnings.append(
                "包含图片：复制时会尝试内嵌，请粘贴后确认公众号已重新托管。",
            )
        if prepared.stripped_private_links:
            warnings.append("已移除仅在私人 Obsidian Vault 内可用的笔记链接。")
        if prepared.unsafe_links:
            warnings.append("已移除不安全或不受微信公众号支持的链接。")

        return RenderedArticle(
            platform=self.platform,
            title=source.title,
            semantic_html=semantic_html,
            export_html=export_html,
            plain_text=_plain_text(export_html),
            warnings=tuple(warnings),
            diagnostics=_layout_diagnostics(prepared),
            theme=config,
        )


WECHAT_RENDERER: PlatformRenderer = WeChatRenderer()
