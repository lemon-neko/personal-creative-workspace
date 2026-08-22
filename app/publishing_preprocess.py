"""Safe Markdown preprocessing and deterministic WeChat diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


BLOCK_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)]\(([^)]+)\)")
MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\]]+)]\(([^)]+)\)")
MARKDOWN_HEADING_LINK = re.compile(r"\[([^\]]+)]\([^)]+\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
EMPTY_HEADING = re.compile(r"^#{1,6}\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
PRIVATE_ROOTS = {"sources", "knowledge", "outputs", "archive", "trash"}


@dataclass(frozen=True)
class FormulaPlaceholder:
    token: str
    source: str
    display: str


@dataclass(frozen=True)
class PreparedMarkdown:
    markdown: str
    formulas: tuple[FormulaPlaceholder, ...]
    removed_duplicate_title: bool
    stripped_private_links: int
    unsafe_links: int
    image_count: int
    long_paragraphs: int
    empty_headings: int
    wide_tables: int


def _comparable_title(value: str) -> str:
    value = MARKDOWN_HEADING_LINK.sub(r"\1", value)
    value = re.sub(r"[`*_~]", "", value)
    return re.sub(r"[\W_]+", "", value.casefold())


def _strip_duplicate_leading_title(
    lines: list[str],
    title: str,
) -> tuple[list[str], bool]:
    first_content = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if first_content is None:
        return lines, False
    match = HEADING.match(lines[first_content])
    if (
        match is None
        or match.group(1) != "#"
        or _comparable_title(match.group(2)) != _comparable_title(title)
    ):
        return lines, False
    updated = lines[:first_content] + lines[first_content + 1 :]
    if first_content < len(updated) and not updated[first_content].strip():
        updated.pop(first_content)
    return updated, True


def _is_private_destination(value: str) -> bool:
    destination = value.strip().strip("<>").split("#", 1)[0]
    parsed = urlparse(destination)
    return not parsed.scheme and (
        destination.lower().endswith(".md")
        or destination.lstrip("/").split("/", 1)[0] in PRIVATE_ROOTS
    )


def _is_safe_destination(value: str, *, image: bool = False) -> bool:
    destination = value.strip().strip("<>").split(maxsplit=1)[0]
    if destination.startswith("/"):
        return not destination.startswith("//")
    if image and destination.startswith("assets/"):
        return ".." not in destination.split("/")
    scheme = urlparse(destination).scheme.lower()
    allowed = {"http", "https"}
    if not image:
        allowed.add("mailto")
    return scheme in allowed


def _sanitize_links(markdown: str) -> tuple[str, int, int]:
    private_count = 0
    unsafe_count = 0

    def replace_link(match: re.Match[str]) -> str:
        nonlocal private_count, unsafe_count
        label, destination = match.group(1), match.group(2)
        if _is_private_destination(destination):
            private_count += 1
            return label
        if not _is_safe_destination(destination):
            unsafe_count += 1
            return label
        return match.group(0)

    def replace_image(match: re.Match[str]) -> str:
        nonlocal unsafe_count
        alt, destination = match.group(1), match.group(2)
        if not _is_safe_destination(destination, image=True):
            unsafe_count += 1
            return alt
        normalized = destination.strip()
        if normalized.startswith("assets/"):
            normalized = f"/{normalized}"
            return f"![{alt}]({normalized})"
        return match.group(0)

    sanitized = MARKDOWN_IMAGE.sub(replace_image, markdown)
    sanitized = MARKDOWN_LINK.sub(replace_link, sanitized)
    return sanitized, private_count, unsafe_count


def _protect_formulas(
    markdown: str,
) -> tuple[str, tuple[FormulaPlaceholder, ...]]:
    formulas: list[FormulaPlaceholder] = []

    def protect(match: re.Match[str], display: str) -> str:
        opening, closing = ("$$", "$$") if display == "block" else ("\\(", "\\)")
        source = f"{opening}{match.group(1).strip()}{closing}"
        token = f"WECHATMATH{len(formulas):04d}TOKEN"
        formulas.append(FormulaPlaceholder(token, source, display))
        return token

    protected = BLOCK_MATH.sub(lambda match: protect(match, "block"), markdown)
    protected = INLINE_MATH.sub(lambda match: protect(match, "inline"), protected)
    return protected, tuple(formulas)


def _layout_metrics(markdown: str) -> tuple[int, int, int]:
    visible_lines: list[str] = []
    in_fence = False
    fence_marker = ""
    empty_headings = 0
    wide_tables = 0

    for line in markdown.splitlines():
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        if EMPTY_HEADING.match(line):
            empty_headings += 1
        if line.strip().startswith("|") and line.count("|") - 1 > 4:
            wide_tables += 1
        visible_lines.append(line)

    long_paragraphs = 0
    for block in re.split(r"\n\s*\n", "\n".join(visible_lines)):
        compact = " ".join(line.strip() for line in block.splitlines()).strip()
        if not compact or re.match(r"^(?:#|>|[-*+] |\d+[.)] |\|)", compact):
            continue
        if len(compact) > 180:
            long_paragraphs += 1
    return long_paragraphs, empty_headings, int(wide_tables > 0)


def prepare_markdown(markdown: str, title: str) -> PreparedMarkdown:
    """Prepare Markdown without imposing article-specific structures."""

    lines, removed_title = _strip_duplicate_leading_title(
        markdown.splitlines(),
        title,
    )
    authored = "\n".join(lines).strip()
    image_count = len(MARKDOWN_IMAGE.findall(authored))
    sanitized, private_count, unsafe_count = _sanitize_links(authored)
    protected, formulas = _protect_formulas(sanitized)
    long_paragraphs, empty_headings, wide_tables = _layout_metrics(sanitized)
    return PreparedMarkdown(
        markdown=protected,
        formulas=formulas,
        removed_duplicate_title=removed_title,
        stripped_private_links=private_count,
        unsafe_links=unsafe_count,
        image_count=image_count,
        long_paragraphs=long_paragraphs,
        empty_headings=empty_headings,
        wide_tables=wide_tables,
    )
