"""Publishing sources and the WeChat renderer for 羽白的幻想栈."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from app.content import load_items, render_markdown
from app.workspace import items_directory


PLATFORM_WECHAT = "wechat"
BLOCK_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*]\([^)]+\)")


@dataclass(frozen=True)
class PublishingSource:
    """One content item prepared for a platform renderer."""

    source_id: str
    kind: str
    title: str
    summary: str
    markdown: str


@dataclass(frozen=True)
class RenderedArticle:
    """Rendered platform article plus clipboard fallback and warnings."""

    platform: str
    title: str
    html: str
    plain_text: str
    warnings: tuple[str, ...]


class PlatformRenderer(Protocol):
    platform: str

    def render(self, source: PublishingSource) -> RenderedArticle: ...


TAG_STYLES = {
    "h1": (
        "margin:40px 0 18px;color:#263033;font-size:22px;line-height:1.55;"
        "font-weight:750;letter-spacing:0.01em;text-align:left;"
    ),
    "h2": (
        "margin:42px 0 18px;padding-top:17px;border-top:1px dotted #d6e0e2;"
        "color:#159fb5;font-size:20px;line-height:1.55;font-weight:750;"
    ),
    "h3": (
        "margin:30px 0 13px;color:#128ca1;font-size:17px;line-height:1.6;"
        "font-weight:720;"
    ),
    "p": (
        "margin:0 0 20px;color:#41494d;font-size:16px;line-height:1.9;"
        "letter-spacing:0.02em;text-align:justify;text-justify:inter-ideograph;"
    ),
    "ul": "margin:0 0 22px;padding-left:24px;color:#41494d;",
    "ol": "margin:0 0 22px;padding-left:24px;color:#41494d;",
    "li": "margin:8px 0;font-size:16px;line-height:1.9;letter-spacing:0.02em;",
    "blockquote": (
        "margin:26px 0;padding:16px 18px;border-left:3px solid #159fb5;"
        "background:#f2f9fa;color:#59666b;font-size:15px;line-height:1.9;"
    ),
    "pre": (
        "margin:24px 0;padding:17px 18px;overflow-x:auto;border-radius:4px;"
        "background:#f3f5f5;color:#354044;font-size:13px;line-height:1.75;"
        "white-space:pre-wrap;word-break:break-word;"
    ),
    "code": (
        "padding:2px 5px;border-radius:3px;background:#eaf5f6;color:#087e94;"
        "font-family:Menlo,Consolas,monospace;font-size:0.88em;"
    ),
    "a": "color:#128ca1;text-decoration:underline;text-underline-offset:3px;",
    "strong": "color:#263033;font-weight:750;",
    "em": "color:#556166;",
    "hr": "margin:36px 0;border:0;border-top:1px dotted #d6e0e2;",
    "table": (
        "width:100%;margin:24px 0;border-collapse:collapse;table-layout:fixed;"
        "color:#41494d;font-size:14px;line-height:1.7;word-break:break-word;"
    ),
    "th": (
        "box-sizing:border-box;padding:9px 10px;border:1px solid #d9e2e4;"
        "background:#f1f8f9;color:#2e383c;font-weight:700;text-align:left;"
    ),
    "td": (
        "box-sizing:border-box;padding:9px 10px;border:1px solid #d9e2e4;"
        "vertical-align:top;word-break:break-word;"
    ),
    "img": (
        "width:auto;max-width:100%;height:auto;margin:26px auto 12px;"
        "display:block;border-radius:4px;"
    ),
}


def _safe_url(value: str, *, image: bool = False) -> bool:
    if value.startswith("/"):
        return True
    parsed = urlparse(value)
    allowed = {"http", "https"}
    if not image:
        allowed.add("mailto")
    return parsed.scheme.lower() in allowed


class _InlineStyleParser(HTMLParser):
    """Apply stable inline styles to safe Markdown-rendered HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre":
            self._pre_depth += 1
        style = "" if tag == "code" and self._pre_depth else TAG_STYLES.get(tag, "")
        kept: list[tuple[str, str | None]] = []
        for name, value in attrs:
            if name in {"alt", "title", "colspan", "rowspan"}:
                kept.append((name, value))
            elif name == "href" and value and _safe_url(value):
                kept.append((name, value))
            elif name == "src" and value and _safe_url(value, image=True):
                kept.append((name, value))
        if style:
            kept.append(("style", style))
        rendered_attrs = "".join(
            f' {name}="{escape(value or "", quote=True)}"' for name, value in kept
        )
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.parts[-1] = self.parts[-1][:-1] + " />"

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return

    def html(self) -> str:
        return "".join(self.parts)


class _PlainTextParser(HTMLParser):
    BREAK_TAGS = {"h1", "h2", "h3", "p", "li", "blockquote", "pre", "tr"}

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


def _inline_styles(html: str) -> str:
    parser = _InlineStyleParser()
    parser.feed(html)
    parser.close()
    return parser.html()


def _plain_text(html: str) -> str:
    parser = _PlainTextParser()
    parser.feed(html)
    parser.close()
    return parser.text()


def _protect_formulas(markdown: str) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    formulas: list[tuple[str, str, str]] = []

    def protect(match: re.Match[str], display: str) -> str:
        opening, closing = ("$$", "$$") if display == "block" else ("\\(", "\\)")
        source = f"{opening}{match.group(1).strip()}{closing}"
        placeholder = f"WECHATMATH{len(formulas):04d}TOKEN"
        formulas.append((placeholder, source, display))
        return placeholder

    protected = BLOCK_MATH.sub(lambda match: protect(match, "block"), markdown)
    protected = INLINE_MATH.sub(lambda match: protect(match, "inline"), protected)
    return protected, tuple(formulas)


def _restore_formulas(
    html: str,
    formulas: tuple[tuple[str, str, str], ...],
) -> str:
    for placeholder, source, display in formulas:
        style = (
            "display:block;margin:22px 0;overflow-x:auto;text-align:center;"
            if display == "block"
            else "display:inline-block;vertical-align:middle;"
        )
        wrapper = (
            f'<span data-formula-source="{escape(source, quote=True)}" '
            f'data-formula-display="{display}" style="{style}">'
            f"{escape(source)}</span>"
        )
        html = html.replace(placeholder, wrapper)
    return html


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
    """Render Markdown in the derived 羽白的幻想栈 visual language."""

    platform = PLATFORM_WECHAT

    def render(self, source: PublishingSource) -> RenderedArticle:
        protected_markdown, formulas = _protect_formulas(source.markdown)
        body_html = _restore_formulas(
            _inline_styles(render_markdown(protected_markdown)),
            formulas,
        )
        signature = (
            '<section style="margin:42px 0 0;padding-top:24px;border-top:1px dotted '
            '#d6e0e2;text-align:center;">'
            '<p style="margin:0 0 8px;color:#41494d;font-size:15px;line-height:1.8;">'
            "羽白 | AI Engineer · Builder · Observer</p>"
            '<p style="margin:0;color:#8a9498;font-size:13px;line-height:1.8;'
            'font-style:italic;">用技术观察世界，也记录成长的痕迹。</p></section>'
        )
        article_html = (
            '<section data-platform="wechat" style="box-sizing:border-box;width:100%;'
            "margin:0;padding:0 4px;color:#41494d;font-family:-apple-system,"
            "BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
            f'word-break:normal;">{body_html}{signature}</section>'
        )
        warnings: list[str] = []
        if BLOCK_MATH.search(source.markdown) or INLINE_MATH.search(source.markdown):
            warnings.append("包含公式：复制时会尝试转换为 PNG，请粘贴后检查清晰度。")
        if MARKDOWN_IMAGE.search(source.markdown):
            warnings.append(
                "包含图片：复制时会尝试内嵌，请粘贴后确认公众号已重新托管。",
            )
        return RenderedArticle(
            platform=self.platform,
            title=source.title,
            html=article_html,
            plain_text=_plain_text(article_html),
            warnings=tuple(warnings),
        )


WECHAT_RENDERER: PlatformRenderer = WeChatRenderer()
