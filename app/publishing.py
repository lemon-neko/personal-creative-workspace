"""Platform-neutral publishing sources and a WeChat rich-text renderer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.content import load_markdown, load_notes, render_markdown


SOURCE_TYPES = {"note", "topic"}
PLATFORM_WECHAT = "wechat"
SAFE_TOPIC_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BLOCK_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*]\([^)]+\)")


@dataclass(frozen=True)
class PublishingSource:
    """One repository content item prepared for a platform renderer."""

    source_type: str
    source_id: str
    title: str
    summary: str
    markdown: str


@dataclass(frozen=True)
class RenderedArticle:
    """A rendered platform article plus fallbacks and compatibility notes."""

    platform: str
    title: str
    html: str
    plain_text: str
    warnings: tuple[str, ...]


class PlatformRenderer(Protocol):
    """Contract implemented by each future platform adapter."""

    platform: str

    def render(self, source: PublishingSource) -> RenderedArticle:
        """Render a publishing source for one target platform."""


TAG_STYLES = {
    "h1": (
        "margin:0 0 24px;color:#1f2329;font-size:28px;line-height:1.35;"
        "font-weight:750;letter-spacing:-0.02em;text-align:left;"
    ),
    "h2": (
        "margin:38px 0 16px;padding-left:12px;border-left:4px solid #b6924e;"
        "color:#1f2329;font-size:22px;line-height:1.45;font-weight:720;"
    ),
    "h3": (
        "margin:28px 0 12px;color:#2f343b;font-size:18px;line-height:1.5;"
        "font-weight:700;"
    ),
    "p": (
        "margin:0 0 18px;color:#3f454d;font-size:16px;line-height:1.9;"
        "letter-spacing:0.02em;text-align:justify;"
    ),
    "ul": "margin:0 0 20px;padding-left:24px;color:#3f454d;",
    "ol": "margin:0 0 20px;padding-left:24px;color:#3f454d;",
    "li": "margin:7px 0;font-size:16px;line-height:1.8;",
    "blockquote": (
        "margin:24px 0;padding:14px 18px;border-left:4px solid #d5b876;"
        "background:#f7f4ed;color:#666056;font-size:15px;line-height:1.8;"
    ),
    "pre": (
        "margin:22px 0;padding:18px;overflow-x:auto;border-radius:6px;"
        "background:#1d2127;color:#e8e5dd;font-size:13px;line-height:1.7;"
        "white-space:pre-wrap;word-break:break-word;"
    ),
    "code": (
        "padding:2px 5px;border-radius:3px;background:#f2efe8;color:#9a6c23;"
        "font-family:Menlo,Consolas,monospace;font-size:0.88em;"
    ),
    "a": "color:#9b772f;text-decoration:underline;text-underline-offset:3px;",
    "strong": "color:#25292f;font-weight:720;",
    "em": "color:#5c626a;",
    "hr": "margin:32px 0;border:0;border-top:1px solid #e6e1d7;",
    "table": (
        "width:100%;margin:22px 0;border-collapse:collapse;color:#3f454d;"
        "font-size:14px;line-height:1.6;"
    ),
    "th": (
        "padding:10px;border:1px solid #d9d4ca;background:#f4f1ea;"
        "color:#2f343b;font-weight:700;text-align:left;"
    ),
    "td": "padding:10px;border:1px solid #d9d4ca;vertical-align:top;",
    "img": "max-width:100%;height:auto;margin:18px auto;display:block;",
}


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
        kept = [
            (name, value)
            for name, value in attrs
            if name in {"href", "src", "alt", "title", "colspan", "rowspan"}
        ]
        existing_style = next((value for name, value in attrs if name == "style"), None)
        if existing_style:
            style = f"{existing_style.rstrip(';')};{style}"
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
        if self.parts:
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
    """Extract a compact plain-text clipboard fallback."""

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
        delimiter = "$$" if display == "block" else "\\("
        closing = "$$" if display == "block" else "\\)"
        source = f"{delimiter}{match.group(1).strip()}{closing}"
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
            "display:block;margin:20px 0;overflow-x:auto;text-align:center;"
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


def _topic_source(content_root: Path, source_id: str) -> PublishingSource | None:
    if not SAFE_TOPIC_ID.fullmatch(source_id):
        return None
    topics_root = (content_root / "topics").resolve()
    path = (topics_root / f"{source_id}.md").resolve()
    if path.parent != topics_root or not path.is_file():
        return None

    markdown = load_markdown(path)
    heading = re.match(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    title = heading.group(1).strip() if heading else source_id
    if heading and heading.start() == 0:
        markdown = markdown[heading.end() :].lstrip()
    first_paragraph = next(
        (
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", markdown)
            if paragraph.strip() and not paragraph.lstrip().startswith(("#", "-", "$$"))
        ),
        "",
    )
    if first_paragraph:
        paragraph_start = markdown.find(first_paragraph)
        markdown = (
            f"{markdown[:paragraph_start]}{markdown[paragraph_start + len(first_paragraph):]}"
        ).strip()
    return PublishingSource(
        source_type="topic",
        source_id=source_id,
        title=title,
        summary=first_paragraph,
        markdown=markdown,
    )


def resolve_publishing_source(
    content_root: Path,
    source_type: str,
    source_id: str,
) -> PublishingSource | None:
    """Resolve only known repository notes or safe topic filenames."""

    if source_type not in SOURCE_TYPES:
        return None
    if source_type == "topic":
        return _topic_source(content_root, source_id)

    collection = load_notes(content_root / "notes")
    note = next((item for item in collection.notes if item.id == source_id), None)
    if note is None:
        return None
    return PublishingSource(
        source_type="note",
        source_id=note.id,
        title=note.title,
        summary=note.summary,
        markdown=note.body,
    )


class WeChatRenderer:
    """Render trusted repository Markdown for WeChat's rich-text editor."""

    platform = PLATFORM_WECHAT

    def render(self, source: PublishingSource) -> RenderedArticle:
        protected_markdown, formulas = _protect_formulas(source.markdown)
        body_html = _restore_formulas(
            _inline_styles(render_markdown(protected_markdown)),
            formulas,
        )
        lead = ""
        if source.summary:
            lead = (
                '<p style="margin:0 0 26px;padding:14px 16px;border-radius:6px;'
                "background:#f7f4ed;color:#6a6255;font-size:15px;line-height:1.8;\">"
                f"{escape(source.summary)}</p>"
            )
        article_html = (
            '<section data-platform="wechat" '
            'style="max-width:677px;margin:0 auto;padding:8px 0;color:#3f454d;'
            'font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\','
            "'Microsoft YaHei',sans-serif;\">"
            f'<h1 style="{TAG_STYLES["h1"]}">{escape(source.title)}</h1>'
            f"{lead}{body_html}"
            '<p style="margin:34px 0 0;padding-top:18px;border-top:1px solid #e6e1d7;'
            'color:#999187;font-size:12px;line-height:1.7;text-align:center;">'
            "持续学习，诚实记录。</p></section>"
        )
        warnings: list[str] = []
        if BLOCK_MATH.search(source.markdown) or INLINE_MATH.search(source.markdown):
            warnings.append("包含公式：复制或下载时会尝试转换为 PNG，请粘贴后检查清晰度。")
        if MARKDOWN_IMAGE.search(source.markdown):
            warnings.append("包含图片：请粘贴后确认图片已由目标平台重新托管。")
        return RenderedArticle(
            platform=self.platform,
            title=source.title,
            html=article_html,
            plain_text=_plain_text(article_html),
            warnings=tuple(warnings),
        )


WECHAT_RENDERER: PlatformRenderer = WeChatRenderer()
