"""File-backed capture, lifecycle, trash, and weekly review workflow."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

from app.atomic import atomic_write_text, content_lock
from app.content import (
    VALID_KINDS,
    VALID_RELATION_TYPES,
    VALID_STATUSES,
    ContentItem,
    KnowledgeRelation,
    combine_managed_links,
    load_items,
    parse_item,
    semantic_revision,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
KIND_LABELS = {
    "thought": "随手想法",
    "weekly-review": "周回顾",
    "article": "文章草稿",
}
STATUS_LABELS = {
    "draft": "草稿",
    "published": "已成稿",
    "archived": "归档",
}
CONTENT_STATUS_LABELS = {
    "thought": {
        "draft": "待整理",
        "published": "已整理",
        "archived": "已归档",
    },
    "article": {
        "draft": "草稿",
        "published": "已成稿",
        "archived": "已归档",
    },
    "weekly-review": {
        "draft": "回顾草稿",
        "published": "已确认",
        "archived": "已归档",
    },
}


def status_labels_for_kind(kind: str) -> dict[str, str]:
    """Return presentation labels without changing persisted status values."""

    return CONTENT_STATUS_LABELS.get(kind, STATUS_LABELS)


class ContentConflictError(ValueError):
    """Raised when another editor changed a note after a form was opened."""

    def __init__(self, current: ContentItem) -> None:
        super().__init__("内容已在 Obsidian 或其他窗口中修改")
        self.current = current


def locked_content_mutation(function):
    """Hold the shared content lock for an entire read-modify-write operation."""

    @wraps(function)
    def wrapped(content_root: Path, *args: Any, **kwargs: Any):
        with content_lock(content_root):
            return function(content_root, *args, **kwargs)

    return wrapped


@dataclass(frozen=True)
class WorkspaceSettings:
    """Local schedule for weekly review drafts."""

    enabled: bool = False
    weekday: int = 6
    hour: int = 20
    minute: int = 0

    @property
    def time_label(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def items_directory(content_root: Path) -> Path:
    """Return the aggregate authored-content root.

    ``load_items(items_directory(root))`` remains the compatibility entrypoint,
    while new writes are routed by content kind below.
    """

    return content_root


def content_directory(content_root: Path, kind: str) -> Path:
    if kind == "thought":
        return content_root / "sources" / "thoughts"
    if kind == "article":
        return content_root / "outputs" / "articles"
    if kind == "weekly-review":
        return content_root / "outputs" / "reviews"
    raise ValueError("内容类型无效")


def trash_directory(content_root: Path) -> Path:
    return content_root / "trash"


def _required_text(value: str, label: str, *, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label}不能为空")
    if len(cleaned) > maximum:
        raise ValueError(f"{label}不能超过 {maximum} 个字符")
    return cleaned


def _normalise_tags(raw_tags: str | Sequence[str]) -> list[str]:
    raw_items = (
        re.split(r"[,，]", raw_tags) if isinstance(raw_tags, str) else raw_tags
    )
    tags: list[str] = []
    for item in raw_items:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:12]


def _plain_text(markdown: str) -> str:
    plain = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", markdown)
    plain = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[#>*_`~|]+", " ", plain)
    return " ".join(plain.split())


def _derive_title(body: str, maximum: int = 46) -> str:
    plain = _plain_text(body)
    first = re.split(r"[。！？!?\n]", plain, maxsplit=1)[0].strip() or "未命名想法"
    return first if len(first) <= maximum else f"{first[:maximum].rstrip()}…"


def _derive_summary(body: str, maximum: int = 110) -> str:
    plain = _plain_text(body)
    return plain if len(plain) <= maximum else f"{plain[: maximum - 1].rstrip()}…"


def _metadata(item: ContentItem) -> dict:
    data = dict(item.extra_metadata)
    data.update({
        "id": item.id,
        "title": item.title,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "status": item.status,
        "kind": item.kind,
        "summary": item.summary,
        "tags": list(item.tags),
    })
    if item.category:
        data["category"] = item.category
    if item.parent_id:
        data["parent_id"] = item.parent_id
    if item.subjects:
        data["subjects"] = list(item.subjects)
    if item.concepts:
        data["concepts"] = list(item.concepts)
    if item.relations:
        data["relations"] = [
            {
                "target_id": relation.target_id,
                "type": relation.relation,
                **({"note": relation.note} if relation.note else {}),
            }
            for relation in item.relations
        ]
    if item.knowledge_updated_at:
        data["knowledge_updated_at"] = item.knowledge_updated_at.isoformat()
    if item.knowledge_source_revision:
        data["knowledge_source_revision"] = item.knowledge_source_revision
    return data


def _write_item(path: Path, item: ContentItem) -> ContentItem:
    front_matter = yaml.safe_dump(
        _metadata(item),
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    body = combine_managed_links(item.body, item.managed_links)
    rendered = f"---\n{front_matter}\n---\n\n{body}\n"
    with content_lock(_content_root_for(path)):
        atomic_write_text(path, rendered)
    return parse_item(path)


def _content_root_for(path: Path) -> Path:
    """Resolve the lifecycle root for an authored Markdown destination."""

    for parent in (path.parent, *path.parents):
        if parent.name == "content":
            return parent
    parent = path.parent
    if parent.name in {"archive", "trash", "items"}:
        return parent.parent
    if parent.name == "thoughts" and parent.parent.name == "sources":
        return parent.parent.parent
    if parent.name in {"articles", "reviews"} and parent.parent.name == "outputs":
        return parent.parent.parent
    return parent


def _new_id(kind: str, created_at: datetime) -> str:
    prefix = {
        "thought": "idea",
        "weekly-review": "weekly-review",
        "article": "article",
    }[kind]
    return f"{prefix}-{created_at:%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"


@locked_content_mutation
def create_item(
    content_root: Path,
    *,
    body: str,
    title: str = "",
    tags: str | Sequence[str] = "",
    category: str = "",
    kind: str = "thought",
    parent_id: str | None = None,
    status: str = "draft",
    now: datetime | None = None,
    item_id: str | None = None,
) -> ContentItem:
    """Create one Markdown item; only body is required for quick capture."""

    if kind not in VALID_KINDS:
        raise ValueError("内容类型无效")
    if status not in VALID_STATUSES:
        raise ValueError("内容状态无效")
    cleaned_body = _required_text(body, "内容", maximum=50_000)
    cleaned_title = title.strip() or _derive_title(cleaned_body)
    if len(cleaned_title) > 120:
        raise ValueError("标题不能超过 120 个字符")
    cleaned_category = category.strip()
    if len(cleaned_category) > 40:
        raise ValueError("分类不能超过 40 个字符")
    created_at = now or datetime.now(SHANGHAI)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=SHANGHAI)
    created_at = created_at.astimezone(SHANGHAI).replace(microsecond=0)
    resolved_item_id = item_id or _new_id(kind, created_at)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", resolved_item_id):
        raise ValueError("内容 ID 无效")
    item = ContentItem(
        id=resolved_item_id,
        title=cleaned_title,
        created_at=created_at,
        updated_at=created_at,
        status=status,
        kind=kind,
        summary=_derive_summary(cleaned_body),
        tags=tuple(_normalise_tags(tags)),
        category=cleaned_category or None,
        parent_id=parent_id,
        body=cleaned_body,
        source=Path(),
    )
    destination = (
        content_root / "archive"
        if status == "archived"
        else content_directory(content_root, kind)
    )
    path = destination / f"{created_at:%Y-%m-%d}-{resolved_item_id}.md"
    if path.exists():
        raise ValueError("内容 ID 已存在")
    return _write_item(path, replace(item, source=path))


@locked_content_mutation
def update_item(
    content_root: Path,
    item_id: str,
    *,
    body: str,
    title: str = "",
    tags: str | Sequence[str] = "",
    category: str = "",
    expected_revision: str = "",
    now: datetime | None = None,
) -> ContentItem:
    """Update editable fields while preserving stable identity and creation time."""

    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    if expected_revision and semantic_revision(item) != expected_revision:
        raise ContentConflictError(item)
    cleaned_body = _required_text(body, "内容", maximum=50_000)
    cleaned_title = title.strip() or _derive_title(cleaned_body)
    if len(cleaned_title) > 120:
        raise ValueError("标题不能超过 120 个字符")
    cleaned_category = category.strip()
    if len(cleaned_category) > 40:
        raise ValueError("分类不能超过 40 个字符")
    updated_at = now or datetime.now(SHANGHAI)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=SHANGHAI)
    updated = replace(
        item,
        title=cleaned_title,
        updated_at=updated_at.astimezone(SHANGHAI).replace(microsecond=0),
        summary=_derive_summary(cleaned_body),
        tags=tuple(_normalise_tags(tags)),
        category=cleaned_category or None,
        body=cleaned_body,
    )
    return _write_item(item.source, updated)


@locked_content_mutation
def reconcile_external_edit(
    content_root: Path,
    item_id: str,
    *,
    expected_revision: str,
    now: datetime | None = None,
) -> ContentItem:
    """Refresh derived metadata after a stable, valid external edit."""

    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    if semantic_revision(item) != expected_revision:
        raise ContentConflictError(item)
    stamp = now or datetime.now(SHANGHAI)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=SHANGHAI)
    updated = replace(
        item,
        summary=_derive_summary(item.body),
        updated_at=stamp.astimezone(SHANGHAI).replace(microsecond=0),
    )
    return _write_item(item.source, updated)


@locked_content_mutation
def set_managed_links(
    content_root: Path,
    item_id: str,
    managed_links: str,
) -> ContentItem:
    """Replace a generated Obsidian block without changing authored timestamps."""

    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    return _write_item(item.source, replace(item, managed_links=managed_links.strip()))


@locked_content_mutation
def set_item_status(content_root: Path, item_id: str, status: str) -> ContentItem:
    if status not in VALID_STATUSES:
        raise ValueError("内容状态无效")
    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    updated = replace(
        item,
        status=status,
        updated_at=datetime.now(SHANGHAI).replace(microsecond=0),
    )
    destination = (
        content_root / "archive" / item.source.name
        if status == "archived"
        else content_directory(content_root, item.kind) / item.source.name
    )
    if destination != item.source and destination.exists():
        raise ValueError("目标生命周期目录中已存在同名内容")
    written = _write_item(destination, replace(updated, source=destination))
    if destination != item.source:
        item.source.unlink()
    return written


@locked_content_mutation
def update_knowledge_metadata(
    content_root: Path,
    item_id: str,
    *,
    subjects: str | Sequence[str],
    concepts: str | Sequence[str],
    relations: Sequence[KnowledgeRelation] = (),
    now: datetime | None = None,
) -> ContentItem:
    """Confirm knowledge metadata without changing authored content timestamps."""

    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    cleaned_subjects = _normalise_tags(subjects)
    cleaned_concepts = _normalise_tags(concepts)
    if not 1 <= len(cleaned_subjects) <= 3:
        raise ValueError("学科必须包含 1 至 3 项")
    if any(len(subject) > 30 for subject in cleaned_subjects):
        raise ValueError("学科名称不能超过 30 个字符")
    if len(cleaned_concepts) > 8:
        raise ValueError("概念最多包含 8 项")
    if any(len(concept) > 40 for concept in cleaned_concepts):
        raise ValueError("概念名称不能超过 40 个字符")
    if len(relations) > 12:
        raise ValueError("关联最多包含 12 项")
    known_ids = {
        candidate.id
        for candidate in load_items(items_directory(content_root)).items
        if candidate.kind != "weekly-review" and candidate.status != "archived"
    }
    cleaned_relations: list[KnowledgeRelation] = []
    for relation in relations:
        if relation.target_id == item_id or relation.target_id not in known_ids:
            raise ValueError("关联目标不存在或无效")
        if relation.relation not in VALID_RELATION_TYPES:
            raise ValueError("关联类型无效")
        note = relation.note.strip()
        if len(note) > 160:
            raise ValueError("关联说明不能超过 160 个字符")
        cleaned_relations.append(
            KnowledgeRelation(relation.target_id, relation.relation, note),
        )
    confirmed_at = now or datetime.now(SHANGHAI)
    if confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=SHANGHAI)
    updated = replace(
        item,
        subjects=tuple(cleaned_subjects[:3]),
        concepts=tuple(cleaned_concepts[:8]),
        relations=tuple(cleaned_relations),
        knowledge_updated_at=confirmed_at.astimezone(SHANGHAI).replace(
            microsecond=0,
        ),
    )
    updated = replace(updated, knowledge_source_revision=semantic_revision(updated))
    return _write_item(item.source, updated)


@locked_content_mutation
def move_to_trash(content_root: Path, item_id: str) -> ContentItem:
    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    destination = trash_directory(content_root) / item.source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    item.source.replace(destination)
    return parse_item(destination)


@locked_content_mutation
def restore_from_trash(content_root: Path, item_id: str) -> ContentItem:
    item = load_items(trash_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    destination_root = (
        content_root / "archive"
        if item.status == "archived"
        else content_directory(content_root, item.kind)
    )
    destination = destination_root / item.source.name
    if destination.exists():
        raise ValueError("想法库中已存在同名内容，无法恢复")
    destination.parent.mkdir(parents=True, exist_ok=True)
    item.source.replace(destination)
    return parse_item(destination)


@locked_content_mutation
def permanently_delete(content_root: Path, item_id: str, confirmation: str) -> None:
    if confirmation.strip() != "永久删除":
        raise ValueError("请输入“永久删除”进行确认")
    item = load_items(trash_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    item.source.unlink()


def current_week_items(
    content_root: Path,
    *,
    as_of: date | None = None,
) -> tuple[ContentItem, ...]:
    current = as_of or datetime.now(SHANGHAI).date()
    week_start = current - timedelta(days=current.weekday())
    week_end = week_start + timedelta(days=6)
    return tuple(
        item
        for item in load_items(items_directory(content_root)).items
        if week_start <= item.created_at.date() <= week_end
        and item.kind != "weekly-review"
    )


def deterministic_weekly_review(items: Sequence[ContentItem]) -> str:
    subjects: dict[str, list[ContentItem]] = {}
    tag_counts: dict[str, int] = {}
    for item in items:
        for subject in item.subjects or ("未分类",):
            subjects.setdefault(subject, []).append(item)
        for tag in item.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    lines = [
        "## 本周概览",
        "",
        f"本周共记录 **{len(items)}** 条内容。以下按学科和原始记录直接汇总。",
        "",
        "## 按学科汇总",
        "",
    ]
    for subject, grouped in sorted(subjects.items()):
        lines.append(f"- **{subject}**：{'、'.join(item.title for item in grouped)}")
    if tag_counts:
        top_tags = sorted(tag_counts, key=lambda tag: (-tag_counts[tag], tag))[:6]
        lines.extend(["", f"高频标签：**{'、'.join(top_tags)}**。"])
    lines.extend(
        [
            "",
            "## 关联与分歧",
            "",
            "- 检查不同记录是否在讨论同一个问题。",
            "- 区分相互支持、延伸和彼此矛盾的判断。",
            "",
            "## 待探索问题",
            "",
            "- 哪条线索值得继续补充材料？",
            "- 哪个判断仍然缺少事实或经历验证？",
            "",
            "## 原始记录",
            "",
        ],
    )
    for item in items:
        lines.extend(
            [
                f"- **{item.title}** · {item.date_label} {item.time_label}",
                f"  {item.summary}",
            ],
        )
    lines.extend(
        [
            "",
            "> 这是系统生成的汇总草稿，仅整理现有记录，不修改原始内容。",
        ],
    )
    return "\n".join(lines)


@locked_content_mutation
def save_weekly_review(
    content_root: Path,
    *,
    as_of: date | None = None,
    summarizer: Callable[[Sequence[ContentItem]], str] | None = None,
) -> tuple[ContentItem, bool, bool]:
    """Create one idempotent weekly review, with safe rule-based fallback."""

    current = as_of or datetime.now(SHANGHAI).date()
    iso_year, iso_week, _ = current.isocalendar()
    stable_prefix = f"weekly-review-{iso_year}-w{iso_week:02d}"
    review_title = f"{iso_year} 年第 {iso_week:02d} 周回顾"
    collection = load_items(items_directory(content_root))
    existing = next(
        (
            item
            for item in collection.items
            if item.kind == "weekly-review" and item.title == review_title
        ),
        None,
    )
    if existing is not None:
        return existing, False, False
    items = current_week_items(content_root, as_of=current)
    if not items:
        raise ValueError("本周还没有可以回顾的记录")

    body = deterministic_weekly_review(items)
    used_ai = False
    if summarizer is not None:
        try:
            candidate = summarizer(items).strip()
            if candidate:
                body = candidate
                used_ai = True
        except Exception:
            used_ai = False

    noon = datetime.combine(current, datetime.min.time(), tzinfo=SHANGHAI).replace(
        hour=12,
    )
    review = create_item(
        content_root,
        title=review_title,
        body=body,
        tags=["周回顾"],
        category="回顾",
        kind="weekly-review",
        now=noon,
    )
    stable_path = review.source.with_name(
        f"{current.isoformat()}-{stable_prefix}-{review.id.rsplit('-', 1)[-1]}.md",
    )
    review.source.replace(stable_path)
    return parse_item(stable_path), True, used_ai


def _settings_path(content_root: Path) -> Path:
    return content_root / "workspace.yaml"


def load_workspace_settings(content_root: Path) -> WorkspaceSettings:
    path = _settings_path(content_root)
    if not path.exists():
        return WorkspaceSettings()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return WorkspaceSettings()
    try:
        enabled = bool(data.get("enabled", False))
        weekday = int(data.get("weekday", 6))
        hour, minute = (
            int(part) for part in str(data.get("time", "20:00")).split(":", 1)
        )
        if weekday not in range(7) or hour not in range(24) or minute not in range(60):
            raise ValueError
    except (TypeError, ValueError):
        return WorkspaceSettings()
    return WorkspaceSettings(enabled, weekday, hour, minute)


def save_workspace_settings(
    content_root: Path,
    *,
    enabled: bool,
    weekday: int,
    time_value: str,
) -> WorkspaceSettings:
    try:
        hour, minute = (int(part) for part in time_value.split(":", 1))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("时间必须使用 HH:MM 格式") from error
    if weekday not in range(7) or hour not in range(24) or minute not in range(60):
        raise ValueError("请选择有效的星期和时间")
    settings = WorkspaceSettings(enabled, weekday, hour, minute)
    path = _settings_path(content_root)
    atomic_write_text(
        path,
        yaml.safe_dump(
            {
                "enabled": enabled,
                "weekday": weekday,
                "time": settings.time_label,
                "timezone": "Asia/Shanghai",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    return settings


def next_summary_run(
    settings: WorkspaceSettings,
    *,
    now: datetime | None = None,
) -> datetime | None:
    if not settings.enabled:
        return None
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    days_ahead = (settings.weekday - current.weekday()) % 7
    candidate = (current + timedelta(days=days_ahead)).replace(
        hour=settings.hour,
        minute=settings.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate


async def run_summary_scheduler(
    content_root: Path,
    *,
    summarizer: Callable[[Sequence[ContentItem]], str] | None = None,
    poll_seconds: float = 60,
) -> None:
    """Generate the current week's draft after the configured local time."""

    while True:
        settings = load_workspace_settings(content_root)
        now = datetime.now(SHANGHAI)
        scheduled = (
            now - timedelta(days=now.weekday()) + timedelta(days=settings.weekday)
        ).replace(
            hour=settings.hour,
            minute=settings.minute,
            second=0,
            microsecond=0,
        )
        if settings.enabled and now >= scheduled:
            try:
                await asyncio.to_thread(
                    save_weekly_review,
                    content_root,
                    as_of=now.date(),
                    summarizer=summarizer,
                )
            except ValueError:
                pass
        await asyncio.sleep(poll_seconds)
