"""Markdown-backed content model for the personal idea workspace."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from markdown_it import MarkdownIt


SHANGHAI = ZoneInfo("Asia/Shanghai")
VALID_STATUSES = {"draft", "published", "archived"}
VALID_KINDS = {"thought", "weekly-review", "article"}
REQUIRED_FIELDS = {
    "id",
    "title",
    "created_at",
    "updated_at",
    "status",
    "kind",
    "summary",
    "tags",
}
MARKDOWN = (
    MarkdownIt(
        "commonmark",
        {
            "html": False,
            "linkify": True,
            "typographer": True,
        },
    )
    .enable("table")
    .enable("strikethrough")
)


@dataclass(frozen=True)
class ContentItem:
    """One validated thought, weekly review, or article."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str
    kind: str
    summary: str
    tags: tuple[str, ...]
    category: str | None
    parent_id: str | None
    body: str
    source: Path

    @property
    def date_label(self) -> str:
        return self.created_at.astimezone(SHANGHAI).strftime("%Y-%m-%d")

    @property
    def time_label(self) -> str:
        return self.created_at.astimezone(SHANGHAI).strftime("%H:%M")


@dataclass(frozen=True)
class ContentDiagnostic:
    """A content error that should not block other files."""

    source: Path
    message: str


@dataclass(frozen=True)
class ContentCollection:
    """Loaded content plus non-fatal diagnostics."""

    items: tuple[ContentItem, ...]
    diagnostics: tuple[ContentDiagnostic, ...]

    @property
    def published(self) -> tuple[ContentItem, ...]:
        return tuple(item for item in self.items if item.status == "published")

    def get(self, item_id: str) -> ContentItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def filter(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        tag: str | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[ContentItem, ...]:
        items: Iterable[ContentItem] = self.items
        if query:
            needle = query.casefold().strip()
            items = (
                item
                for item in items
                if needle
                in " ".join(
                    (item.title, item.summary, item.body, " ".join(item.tags)),
                ).casefold()
            )
        if status:
            items = (item for item in items if item.status == status)
        if kind:
            items = (item for item in items if item.kind == kind)
        if tag:
            items = (item for item in items if tag in item.tags)
        if category:
            items = (item for item in items if item.category == category)
        if date_from:
            items = (item for item in items if item.date_label >= date_from)
        if date_to:
            items = (item for item in items if item.date_label <= date_to)
        return tuple(items)


def _split_front_matter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("缺少 YAML front matter 起始标记 `---`")
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as error:
        raise ValueError("缺少 YAML front matter 结束标记 `---`") from error
    return "\n".join(lines[1:end]), "\n".join(lines[end + 1 :]).strip()


def _required_text(metadata: dict, field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{field}` 必须是非空文本")
    return value.strip()


def _optional_text(metadata: dict, field: str) -> str | None:
    value = metadata.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{field}` 必须是文本")
    return value.strip() or None


def _parse_datetime(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"`{field}` 必须使用 ISO 8601 时间格式") from error
    else:
        raise TypeError(f"`{field}` 必须使用 ISO 8601 时间格式")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def parse_item(path: Path) -> ContentItem:
    """Parse and validate one Markdown content item."""

    front_matter, body = _split_front_matter(path.read_text(encoding="utf-8"))
    metadata = yaml.safe_load(front_matter)
    if not isinstance(metadata, dict):
        raise TypeError("front matter 必须是键值映射")

    missing = sorted(REQUIRED_FIELDS - metadata.keys())
    if missing:
        raise ValueError(f"缺少必填字段：{', '.join(missing)}")

    status = metadata["status"]
    if status not in VALID_STATUSES:
        raise ValueError("`status` 只能是 `draft`、`published` 或 `archived`")
    kind = metadata["kind"]
    if kind not in VALID_KINDS:
        raise ValueError("`kind` 只能是 `thought`、`weekly-review` 或 `article`")

    raw_tags = metadata["tags"]
    if not isinstance(raw_tags, list) or not all(
        isinstance(tag, str) and tag.strip() for tag in raw_tags
    ):
        raise ValueError("`tags` 必须是文本列表")
    if not body:
        raise ValueError("Markdown 正文不能为空")

    return ContentItem(
        id=_required_text(metadata, "id"),
        title=_required_text(metadata, "title"),
        created_at=_parse_datetime(metadata["created_at"], "created_at"),
        updated_at=_parse_datetime(metadata["updated_at"], "updated_at"),
        status=status,
        kind=kind,
        summary=_required_text(metadata, "summary"),
        tags=tuple(tag.strip() for tag in raw_tags),
        category=_optional_text(metadata, "category"),
        parent_id=_optional_text(metadata, "parent_id"),
        body=body,
        source=path,
    )


def load_items(directory: Path) -> ContentCollection:
    """Load content files while isolating invalid files as diagnostics."""

    items: list[ContentItem] = []
    diagnostics: list[ContentDiagnostic] = []
    seen_ids: dict[str, Path] = {}
    paths = sorted(directory.glob("*.md")) if directory.exists() else []
    for path in paths:
        try:
            item = parse_item(path)
            if item.id in seen_ids:
                raise ValueError(f"`id` 与 {seen_ids[item.id].name} 重复：{item.id}")
            seen_ids[item.id] = path
            items.append(item)
        except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
            diagnostics.append(ContentDiagnostic(path, str(error)))

    items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    return ContentCollection(tuple(items), tuple(diagnostics))


def render_markdown(markdown: str) -> str:
    """Render repository-authored Markdown with raw HTML disabled."""

    return MARKDOWN.render(markdown)
