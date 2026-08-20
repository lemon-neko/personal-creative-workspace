"""Markdown-backed content model for the personal idea workspace."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import yaml
from markdown_it import MarkdownIt


SHANGHAI = ZoneInfo("Asia/Shanghai")
VALID_STATUSES = {"draft", "published", "archived"}
VALID_KINDS = {"thought", "weekly-review", "article"}
VALID_RELATION_TYPES = {"related", "extends", "supports", "contrasts"}
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
OPTIONAL_FIELDS = {
    "category",
    "parent_id",
    "subjects",
    "concepts",
    "relations",
    "knowledge_updated_at",
    "knowledge_source_revision",
}
RESERVED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
MANAGED_LINKS_START = "<!-- pcw:obsidian-links:start -->"
MANAGED_LINKS_END = "<!-- pcw:obsidian-links:end -->"
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
class KnowledgeRelation:
    """One confirmed relationship to another content item."""

    target_id: str
    relation: str
    note: str = ""


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
    subjects: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    relations: tuple[KnowledgeRelation, ...] = ()
    knowledge_updated_at: datetime | None = None
    knowledge_source_revision: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    managed_links: str = ""

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
                    (
                        item.title,
                        item.summary,
                        item.body,
                        " ".join(item.tags),
                        " ".join(item.subjects),
                        " ".join(item.concepts),
                    ),
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


def split_managed_links(body: str) -> tuple[str, str]:
    """Separate the generated Obsidian relation block from authored Markdown."""

    start = body.rfind(MANAGED_LINKS_START)
    if start < 0:
        return body.strip(), ""
    end = body.find(MANAGED_LINKS_END, start)
    if end < 0 or body[end + len(MANAGED_LINKS_END) :].strip():
        return body.strip(), ""
    managed = body[start : end + len(MANAGED_LINKS_END)].strip()
    return body[:start].strip(), managed


def combine_managed_links(body: str, managed_links: str) -> str:
    authored = body.strip()
    managed = managed_links.strip()
    return f"{authored}\n\n{managed}" if managed else authored


def semantic_revision(item: ContentItem) -> str:
    """Hash only author-controlled semantics, excluding generated projections."""

    payload = {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "kind": item.kind,
        "tags": list(item.tags),
        "category": item.category,
        "parent_id": item.parent_id,
        "subjects": list(item.subjects),
        "concepts": list(item.concepts),
        "relations": [
            {
                "target_id": relation.target_id,
                "type": relation.relation,
                "note": relation.note,
            }
            for relation in item.relations
        ],
        "body": item.body,
        "extra_metadata": item.extra_metadata,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _extra_metadata(metadata: dict) -> dict[str, Any]:
    extras = {str(key): value for key, value in metadata.items() if key not in RESERVED_FIELDS}
    if len(extras) > 50:
        raise ValueError("Obsidian 自定义属性不能超过 50 项")
    try:
        rendered = yaml.safe_dump(extras, allow_unicode=True)
    except yaml.YAMLError as error:
        raise ValueError("Obsidian 自定义属性无法安全保存") from error
    if len(rendered.encode("utf-8")) > 20_000:
        raise ValueError("Obsidian 自定义属性总大小不能超过 20 KB")
    return extras


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


def _optional_datetime(metadata: dict, field: str) -> datetime | None:
    value = metadata.get(field)
    return None if value in (None, "") else _parse_datetime(value, field)


def _optional_text_list(
    metadata: dict,
    field: str,
    *,
    maximum: int,
    item_maximum: int,
) -> tuple[str, ...]:
    if field not in metadata:
        return ()
    values = metadata[field]
    if not isinstance(values, list) or not values:
        raise ValueError(f"`{field}` 必须是非空文本列表")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"`{field}` 必须是非空文本列表")
        item = value.strip()
        if len(item) > item_maximum:
            raise ValueError(f"`{field}` 中的文本不能超过 {item_maximum} 个字符")
        if item not in cleaned:
            cleaned.append(item)
    if len(cleaned) > maximum:
        raise ValueError(f"`{field}` 最多包含 {maximum} 项")
    return tuple(cleaned)


def _optional_relations(metadata: dict) -> tuple[KnowledgeRelation, ...]:
    if "relations" not in metadata:
        return ()
    values = metadata["relations"]
    if not isinstance(values, list):
        raise ValueError("`relations` 必须是关系列表")
    if len(values) > 12:
        raise ValueError("`relations` 最多包含 12 项")
    relations: list[KnowledgeRelation] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("`relations` 中的每一项必须是键值映射")
        target_id = value.get("target_id")
        relation = value.get("type")
        note = value.get("note", "")
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError("关系的 `target_id` 必须是非空文本")
        if relation not in VALID_RELATION_TYPES:
            raise ValueError(
                "关系的 `type` 只能是 `related`、`extends`、`supports` 或 `contrasts`",
            )
        if not isinstance(note, str) or len(note.strip()) > 160:
            raise ValueError("关系的 `note` 必须是不超过 160 个字符的文本")
        relations.append(
            KnowledgeRelation(target_id.strip(), relation, note.strip()),
        )
    return tuple(relations)


def parse_item(path: Path) -> ContentItem:
    """Parse and validate one Markdown content item."""

    front_matter, raw_body = _split_front_matter(path.read_text(encoding="utf-8"))
    body, managed_links = split_managed_links(raw_body)
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

    subjects = _optional_text_list(
        metadata,
        "subjects",
        maximum=3,
        item_maximum=30,
    )
    concepts = _optional_text_list(
        metadata,
        "concepts",
        maximum=8,
        item_maximum=40,
    )

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
        subjects=subjects,
        concepts=concepts,
        relations=_optional_relations(metadata),
        knowledge_updated_at=_optional_datetime(metadata, "knowledge_updated_at"),
        knowledge_source_revision=_optional_text(
            metadata,
            "knowledge_source_revision",
        ),
        extra_metadata=_extra_metadata(metadata),
        managed_links=managed_links,
    )


def load_items(directory: Path) -> ContentCollection:
    """Load authored content across legacy and lifecycle directories.

    Passing the content root loads the stable authored-content locations. Passing
    a leaf directory (for example ``trash``) continues to load only that folder.
    Knowledge cards and maps deliberately use separate parsers.
    """

    items: list[ContentItem] = []
    diagnostics: list[ContentDiagnostic] = []
    seen_ids: dict[str, Path] = {}
    paths: list[Path] = []
    if directory.exists():
        paths.extend(directory.glob("*.md"))
        lifecycle_roots = (
            directory / "items",
            directory / "sources" / "thoughts",
            directory / "outputs" / "articles",
            directory / "outputs" / "reviews",
            directory / "archive",
        )
        paths.extend(
            path
            for root in lifecycle_roots
            if root.exists()
            for path in root.glob("*.md")
        )
    paths = sorted(set(paths))
    for path in paths:
        if path.parent == directory and path.name == "知识首页.md":
            continue
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


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _rewrite_markdown_urls(
    tokens: list,
    *,
    source: Path | None,
    content_root: Path | None,
) -> None:
    for token in tokens:
        children = getattr(token, "children", None)
        if children:
            _rewrite_markdown_urls(children, source=source, content_root=content_root)
        attribute = "src" if token.type == "image" else "href" if token.type == "link_open" else ""
        if not attribute:
            continue
        raw = token.attrGet(attribute) or ""
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc:
            continue
        path_value = unquote(parsed.path)
        asset_match = re.fullmatch(r"/?assets/([^/]+)", path_value)
        if asset_match and Path(asset_match.group(1)).name == asset_match.group(1):
            token.attrSet(attribute, f"/assets/{asset_match.group(1)}")
            continue
        if content_root is None or not path_value.lower().endswith(".md"):
            continue
        candidate = (
            content_root / path_value.lstrip("/")
            if path_value.startswith("/") or not path_value.startswith(".")
            else (source.parent if source else content_root) / path_value
        ).resolve()
        if not _inside(content_root, candidate) or not candidate.is_file():
            continue
        suffix = f"#{parsed.fragment}" if parsed.fragment else ""
        try:
            if candidate.parent == content_root / "knowledge" / "cards":
                from app.knowledge_store import parse_card

                token.attrSet(attribute, f"/knowledge/cards/{parse_card(candidate).id}{suffix}")
            elif candidate.parent == content_root / "knowledge" / "maps":
                from app.knowledge_store import parse_map

                token.attrSet(attribute, f"/knowledge/maps/{parse_map(candidate).id}{suffix}")
            else:
                token.attrSet(attribute, f"/ideas/{parse_item(candidate).id}{suffix}")
        except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError):
            continue


def render_markdown(
    markdown: str,
    *,
    source: Path | None = None,
    content_root: Path | None = None,
) -> str:
    """Render repository-authored Markdown with raw HTML disabled."""

    tokens = MARKDOWN.parse(markdown)
    _rewrite_markdown_urls(tokens, source=source, content_root=content_root)
    return MARKDOWN.renderer.render(tokens, MARKDOWN.options, {})
