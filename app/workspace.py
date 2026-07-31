"""File-backed capture, lifecycle, trash, and weekly review workflow."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

from app.content import (
    VALID_KINDS,
    VALID_STATUSES,
    ContentItem,
    load_items,
    parse_item,
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
    "published": "公开",
    "archived": "归档",
}


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
    return content_root / "items"


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
    data = {
        "id": item.id,
        "title": item.title,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "status": item.status,
        "kind": item.kind,
        "summary": item.summary,
        "tags": list(item.tags),
    }
    if item.category:
        data["category"] = item.category
    if item.parent_id:
        data["parent_id"] = item.parent_id
    return data


def _write_item(path: Path, item: ContentItem) -> ContentItem:
    front_matter = yaml.safe_dump(
        _metadata(item),
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n{front_matter}\n---\n\n{item.body.strip()}\n",
        encoding="utf-8",
    )
    return parse_item(path)


def _new_id(kind: str, created_at: datetime) -> str:
    prefix = {
        "thought": "idea",
        "weekly-review": "weekly-review",
        "article": "article",
    }[kind]
    return f"{prefix}-{created_at:%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"


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
    item_id = _new_id(kind, created_at)
    item = ContentItem(
        id=item_id,
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
    path = items_directory(content_root) / f"{created_at:%Y-%m-%d}-{item_id}.md"
    return _write_item(path, replace(item, source=path))


def update_item(
    content_root: Path,
    item_id: str,
    *,
    body: str,
    title: str = "",
    tags: str | Sequence[str] = "",
    category: str = "",
    now: datetime | None = None,
) -> ContentItem:
    """Update editable fields while preserving stable identity and creation time."""

    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
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
    return _write_item(item.source, updated)


def move_to_trash(content_root: Path, item_id: str) -> ContentItem:
    item = load_items(items_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    destination = trash_directory(content_root) / item.source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    item.source.replace(destination)
    return parse_item(destination)


def restore_from_trash(content_root: Path, item_id: str) -> ContentItem:
    item = load_items(trash_directory(content_root)).get(item_id)
    if item is None:
        raise KeyError(item_id)
    destination = items_directory(content_root) / item.source.name
    if destination.exists():
        raise ValueError("想法库中已存在同名内容，无法恢复")
    destination.parent.mkdir(parents=True, exist_ok=True)
    item.source.replace(destination)
    return parse_item(destination)


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
    categories: dict[str, list[ContentItem]] = {}
    tag_counts: dict[str, int] = {}
    for item in items:
        categories.setdefault(item.category or "未分类", []).append(item)
        for tag in item.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    lines = [
        "## 本周 / This Week",
        "",
        f"这一周留下了 **{len(items)}** 条记录。先不急着下结论，看看它们在说什么。",
        "",
        "## 线索 / Threads",
        "",
    ]
    for category, grouped in sorted(categories.items()):
        lines.append(f"- **{category}**：{'、'.join(item.title for item in grouped)}")
    if tag_counts:
        top_tags = sorted(tag_counts, key=lambda tag: (-tag_counts[tag], tag))[:6]
        lines.extend(["", f"反复出现的词：**{'、'.join(top_tags)}**。"])
    lines.extend(["", "## 原始记录 / Notes", ""])
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
            "## 写在最后 / Afterword",
            "",
            "- 哪几条想法其实在谈同一件事？",
            "- 哪个判断只是当时的情绪，哪个值得继续验证？",
            "- 下周最想沿着哪条线索多走一步？",
            "",
            "> 这是系统生成的回顾草稿。原始想法没有被改动。",
        ],
    )
    return "\n".join(lines)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
        encoding="utf-8",
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
