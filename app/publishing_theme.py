"""The restrained doocs-inspired WeChat theme used by 羽白工作台."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from typing import Mapping
from urllib.parse import urlencode, urlparse

from app.publishing_preprocess import FormulaPlaceholder


DEFAULT_PRIMARY_COLOR = "#1597A8"
PRIMARY_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
FONT_FAMILIES = {
    "sans": (
        "-apple-system,BlinkMacSystemFont,'Helvetica Neue','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif"
    ),
    "serif": (
        "Optima-Regular,Optima,'PingFang SC',Cambria,Cochin,Georgia,"
        "'Times New Roman',serif"
    ),
}
FONT_LABELS = {"sans": "无衬线", "serif": "衬线"}
FONT_SIZES = (15, 16, 17, 18)


@dataclass(frozen=True)
class WechatThemeConfig:
    """Validated presentation-only controls for the standard WeChat theme."""

    primary_color: str = DEFAULT_PRIMARY_COLOR
    font_family: str = "sans"
    font_size: int = 16
    indent: bool = False
    justify: bool = True

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> WechatThemeConfig:
        color = values.get("primary_color", DEFAULT_PRIMARY_COLOR).strip()
        if not PRIMARY_COLOR.fullmatch(color):
            color = DEFAULT_PRIMARY_COLOR
        family = values.get("font_family", "sans")
        if family not in FONT_FAMILIES:
            family = "sans"
        try:
            size = int(values.get("font_size", "16"))
        except ValueError:
            size = 16
        if size not in FONT_SIZES:
            size = 16
        return cls(
            primary_color=color.upper(),
            font_family=family,
            font_size=size,
            indent=values.get("indent") == "1",
            justify=values.get("justify", "1") == "1",
        )

    @property
    def font_stack(self) -> str:
        return FONT_FAMILIES[self.font_family]

    @property
    def query_string(self) -> str:
        return urlencode(self.query_params)

    @property
    def query_params(self) -> dict[str, str]:
        return {
            "primary_color": self.primary_color,
            "font_family": self.font_family,
            "font_size": str(self.font_size),
            "indent": "1" if self.indent else "0",
            "justify": "1" if self.justify else "0",
        }


def _safe_url(value: str, *, image: bool = False) -> bool:
    if value.startswith("/") and not value.startswith("//"):
        return True
    parsed = urlparse(value)
    allowed = {"http", "https"}
    if not image:
        allowed.add("mailto")
    return parsed.scheme.lower() in allowed


def _styles(config: WechatThemeConfig) -> dict[str, str]:
    size = config.font_size
    primary = config.primary_color
    paragraph_layout = "text-align:justify;text-justify:inter-ideograph;" if config.justify else "text-align:left;"
    indent = "text-indent:2em;" if config.indent else ""
    return {
        "h1": (
            f"display:table;margin:2.2em auto 1.5em;padding:0 1em 0.35em;"
            f"border-bottom:2px solid {primary};color:#2F3437;font-size:{round(size * 1.25)}px;"
            "line-height:1.5;font-weight:700;text-align:center;"
        ),
        "h2": (
            f"display:table;margin:3.2em auto 1.6em;padding:0.28em 0.85em;"
            f"border-radius:2px;background:{primary};color:#FFFFFF;font-size:{round(size * 1.2)}px;"
            "line-height:1.55;font-weight:700;text-align:center;"
        ),
        "h3": (
            f"margin:2.1em 0 0.9em;padding-left:9px;border-left:3px solid {primary};"
            f"color:#2F3437;font-size:{round(size * 1.1)}px;line-height:1.45;font-weight:700;"
        ),
        "h4": (
            f"margin:1.8em 0 0.75em;color:{primary};font-size:{size}px;"
            "line-height:1.55;font-weight:700;"
        ),
        "h5": (
            f"margin:1.6em 0 0.7em;color:{primary};font-size:{size}px;"
            "line-height:1.55;font-weight:700;"
        ),
        "h6": (
            f"margin:1.6em 0 0.7em;color:#60666A;font-size:{size}px;"
            "line-height:1.55;font-weight:700;"
        ),
        "p": (
            f"margin:1.35em 8px;color:#3F3F3F;font-size:{size}px;line-height:1.75;"
            f"letter-spacing:0.06em;{indent}{paragraph_layout}"
        ),
        "ul": "margin:1.1em 8px 1.4em;padding-left:1.55em;color:#3F3F3F;",
        "ol": "margin:1.1em 8px 1.4em;padding-left:1.55em;color:#3F3F3F;",
        "li": (
            f"margin:0.55em 0;color:#3F3F3F;font-size:{size}px;line-height:1.75;"
            "letter-spacing:0.04em;"
        ),
        "blockquote": (
            f"margin:1.8em 8px;padding:1em 1.1em;border-left:4px solid {primary};"
            "border-radius:5px;background:#F7F7F7;color:#555B5E;"
        ),
        "pre": (
            "box-sizing:border-box;margin:1.7em 8px;padding:16px 17px;max-width:100%;"
            "overflow:visible;border:1px solid #E6E8E8;border-radius:5px;background:#F6F7F7;"
            "color:#30363A;font-size:13px;line-height:1.7;white-space:pre-wrap;"
            "word-break:break-all;overflow-wrap:anywhere;"
        ),
        "code": (
            f"padding:2px 5px;border-radius:3px;background:#EEF6F7;color:{primary};"
            "font-family:Menlo,Monaco,Consolas,'Courier New',monospace;font-size:0.9em;"
        ),
        "a": "color:#576B95;text-decoration:none;word-break:break-all;",
        "strong": "color:#2F3437;font-weight:700;",
        "em": "color:#5F6669;font-style:italic;",
        "s": "color:#8A8F91;",
        "hr": (
            "height:1px;margin:2.2em 8px;border:0;background:#E4E7E7;"
        ),
        "table": (
            f"box-sizing:border-box;width:100%;max-width:100%;margin:1.6em 0;"
            f"border-collapse:collapse;table-layout:fixed;color:#3F3F3F;font-size:{max(13, size - 2)}px;"
            "line-height:1.65;word-break:break-word;overflow-wrap:anywhere;"
        ),
        "th": (
            f"box-sizing:border-box;padding:9px 8px;border:1px solid #DDE3E3;"
            f"background:{primary};color:#FFFFFF;font-weight:700;text-align:left;"
            "word-break:break-word;overflow-wrap:anywhere;"
        ),
        "td": (
            "box-sizing:border-box;padding:9px 8px;border:1px solid #DDE3E3;"
            "vertical-align:top;word-break:break-word;overflow-wrap:anywhere;"
        ),
        "img": (
            "display:block;width:auto;max-width:100%;height:auto;margin:1.8em auto 0.55em;"
            "border-radius:4px;"
        ),
    }


IMAGE_CAPTION_STYLE = (
    "display:block;margin:0 auto 1.8em;color:#888E90;font-size:12px;"
    "line-height:1.6;letter-spacing:0.03em;text-align:center;"
)


class InlineThemeParser(HTMLParser):
    """Apply resolved, safe inline styles to semantic Markdown HTML."""

    def __init__(self, config: WechatThemeConfig) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.config = config
        self.styles = _styles(config)
        self.pre_depth = 0
        self.blockquote_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre":
            self.pre_depth += 1
        if tag == "blockquote":
            self.blockquote_depth += 1
        style = "" if tag == "code" and self.pre_depth else self.styles.get(tag, "")
        if tag == "p" and self.blockquote_depth:
            style = (
                f"margin:0;color:#555B5E;font-size:{self.config.font_size}px;"
                "line-height:1.75;letter-spacing:0.04em;text-align:left;"
            )
        kept: list[tuple[str, str | None]] = []
        alt_text = ""
        for name, value in attrs:
            if name in {"alt", "title", "colspan", "rowspan"}:
                kept.append((name, value))
                if name == "alt" and value:
                    alt_text = value.strip()
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
        if tag == "img" and alt_text:
            self.parts.append(
                f'<small style="{IMAGE_CAPTION_STYLE}">{escape(alt_text)}</small>',
            )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        before = len(self.parts)
        self.handle_starttag(tag, attrs)
        self.parts[before] = self.parts[before][:-1] + " />"

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")
        if tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
        if tag == "blockquote":
            self.blockquote_depth = max(0, self.blockquote_depth - 1)

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


def apply_theme(html: str, config: WechatThemeConfig) -> str:
    parser = InlineThemeParser(config)
    parser.feed(html)
    parser.close()
    return parser.html()


def restore_formulas(
    html: str,
    formulas: tuple[FormulaPlaceholder, ...],
) -> str:
    for formula in formulas:
        style = (
            "display:block;margin:1.6em 0;overflow-x:auto;text-align:center;"
            if formula.display == "block"
            else "display:inline-block;vertical-align:middle;"
        )
        wrapper = (
            f'<span data-formula-source="{escape(formula.source, quote=True)}" '
            f'data-formula-display="{formula.display}" style="{style}">'
            f"{escape(formula.source)}</span>"
        )
        html = html.replace(formula.token, wrapper)
    return html


def wrap_article(body_html: str, config: WechatThemeConfig) -> str:
    signature = (
        '<section style="margin:3em 8px 0;padding-top:1.25em;border-top:1px solid #E4E7E7;'
        'text-align:left;">'
        f'<p style="margin:0 0 0.45em;color:{config.primary_color};font-size:12px;line-height:1.6;'
        'font-weight:700;letter-spacing:0.12em;">羽白</p>'
        '<p style="margin:0 0 0.25em;color:#4A5053;font-size:13px;line-height:1.7;">'
        'AI Engineer · Builder · Observer</p>'
        '<p style="margin:0;color:#8A8F91;font-size:12px;line-height:1.7;">'
        '用技术观察世界，也记录成长的痕迹。</p></section>'
    )
    return (
        '<section data-platform="wechat" style="box-sizing:border-box;width:100%;max-width:100%;'
        f'margin:0;padding:0;color:#3F3F3F;font-family:{config.font_stack};'
        f'font-size:{config.font_size}px;line-height:1.75;word-break:normal;overflow-wrap:break-word;">'
        f"{body_html}{signature}</section>"
    )
