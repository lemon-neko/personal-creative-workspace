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
        "margin:0 0 30px;color:#24282d;font-size:27px;line-height:1.45;"
        "font-weight:700;letter-spacing:0.01em;text-align:left;"
    ),
    "h2": (
        "margin:44px 0 22px;padding-top:20px;border-top:1px dotted #cfd5d7;"
        "color:#0794ae;font-size:22px;line-height:1.45;font-weight:750;"
    ),
    "h3": (
        "margin:32px 0 14px;color:#0794ae;font-size:18px;line-height:1.55;"
        "font-weight:720;"
    ),
    "p": (
        "margin:0 0 22px;color:#555d63;font-size:16px;line-height:2;"
        "letter-spacing:0.025em;text-align:justify;"
    ),
    "ul": "margin:0 0 24px;padding-left:24px;color:#555d63;",
    "ol": "margin:0 0 24px;padding-left:24px;color:#555d63;",
    "li": "margin:9px 0;font-size:16px;line-height:1.9;",
    "blockquote": (
        "margin:28px 0;padding:16px 18px;border-left:3px solid #0794ae;"
        "background:#f5fafb;color:#657278;font-size:15px;line-height:1.9;"
    ),
    "pre": (
        "margin:24px 0;padding:18px;overflow-x:auto;border-radius:4px;"
        "background:#f3f4f4;color:#3f494e;font-size:13px;line-height:1.75;"
        "white-space:pre-wrap;word-break:break-word;"
    ),
    "code": (
        "padding:2px 5px;border-radius:3px;background:#eef5f6;color:#087e94;"
        "font-family:Menlo,Consolas,monospace;font-size:0.88em;"
    ),
    "a": "color:#078aa2;text-decoration:underline;text-underline-offset:3px;",
    "strong": "color:#252a2e;font-weight:750;",
    "em": "color:#59656a;",
    "hr": "margin:38px 0;border:0;border-top:1px dotted #cfd5d7;",
    "table": (
        "width:100%;margin:24px 0;border-collapse:collapse;color:#555d63;"
        "font-size:14px;line-height:1.7;"
    ),
    "th": (
        "padding:10px;border:1px solid #dce2e4;background:#f3f8f9;"
        "color:#2e383c;font-weight:700;text-align:left;"
    ),
    "td": "padding:10px;border:1px solid #dce2e4;vertical-align:top;",
    "img": (
        "max-width:100%;height:auto;margin:28px auto 10px;display:block;"
        "border-radius:2px;"
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
        lead = (
            '<p style="margin:0 0 30px;color:#788287;font-size:14px;line-height:1.9;'
            f'text-align:center;">{escape(source.summary)}</p>'
            if source.summary
            else ""
        )
        signature = (
            '<section style="margin:42px 0 0;padding-top:24px;border-top:1px dotted '
            '#cfd5d7;text-align:center;">'
            '<p style="margin:0 0 8px;color:#555d63;font-size:15px;line-height:1.8;">'
            "羽白 | AI Engineer · Builder · Observer</p>"
            '<p style="margin:0;color:#8a9498;font-size:13px;line-height:1.8;'
            'font-style:italic;">用技术观察世界，也记录成长的痕迹。</p></section>'
        )
        article_html = (
            '<section data-platform="wechat" style="max-width:677px;margin:0 auto;'
            "padding:10px 0;color:#555d63;font-family:-apple-system,BlinkMacSystemFont,"
            "'PingFang SC','Microsoft YaHei',sans-serif;\">"
            f'<h1 style="{TAG_STYLES["h1"]}">{escape(source.title)}</h1>'
            f"{lead}{body_html}{signature}</section>"
        )
        warnings: list[str] = []
        if BLOCK_MATH.search(source.markdown) or INLINE_MATH.search(source.markdown):
            warnings.append("包含公式：复制时会尝试转换为 PNG，请粘贴后检查清晰度。")
        if MARKDOWN_IMAGE.search(source.markdown):
            warnings.append("包含图片：请粘贴后确认图片已由公众号重新托管。")
        return RenderedArticle(
            platform=self.platform,
            title=source.title,
            html=article_html,
            plain_text=_plain_text(article_html),
            warnings=tuple(warnings),
        )


WECHAT_RENDERER: PlatformRenderer = WeChatRenderer()
