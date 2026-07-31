"""File-backed capture and weekly-review workflow for the local workspace."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

from app.content import StudyNote, load_notes, parse_note


SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
SUMMARY_TOPIC = "weekly-review"
FRAGMENT_TAG = "碎片"


@dataclass(frozen=True)
class WorkspaceSettings:
    """Local schedule for the weekly draft generator."""

    enabled: bool = False
    weekday: int = 6
    hour: int = 20
    minute: int = 0

    @property
    def time_label(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def _required_text(value: str, label: str, *, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label}不能为空")
    if len(cleaned) > maximum:
        raise ValueError(f"{label}不能超过 {maximum} 个字符")
    return cleaned


def _normalise_tags(raw_tags: str) -> list[str]:
    tags: list[str] = []
    for item in re.split(r"[,，]", raw_tags):
        tag = item.strip()
        if tag and tag not in tags:
            tags.append(tag)
    if FRAGMENT_TAG not in tags:
        tags.append(FRAGMENT_TAG)
    return tags[:8]


def _plain_summary(body: str, *, maximum: int = 96) -> str:
    plain = re.sub(r"[#>*_`~\[\]()!-]+", " ", body)
    plain = " ".join(plain.split())
    if len(plain) <= maximum:
        return plain
    return f"{plain[: maximum - 1].rstrip()}…"


def _write_note(path: Path, metadata: dict, body: str) -> StudyNote:
    front_matter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front_matter}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return parse_note(path)


def save_fragment(
    content_root: Path,
    *,
    title: str,
    body: str,
    tags: str = "",
    topic: str = "inbox",
    captured_on: date | None = None,
) -> StudyNote:
    """Save one browser-captured fragment as a draft Markdown note."""

    cleaned_title = _required_text(title, "标题", maximum=120)
    cleaned_body = _required_text(body, "内容", maximum=20_000)
    cleaned_topic = topic.strip() or "inbox"
    if len(cleaned_topic) > 80:
        raise ValueError("专题标识不能超过 80 个字符")

    note_date = captured_on or datetime.now(SHANGHAI).date()
    note_id = f"fragment-{note_date:%Y%m%d}-{uuid4().hex[:8]}"
    path = content_root / "notes" / f"{note_date.isoformat()}-{note_id}.md"
    return _write_note(
        path,
        {
            "id": note_id,
            "title": cleaned_title,
            "date": note_date.isoformat(),
            "status": "draft",
            "summary": _plain_summary(cleaned_body),
            "tags": _normalise_tags(tags),
            "topic": cleaned_topic,
        },
        cleaned_body,
    )


def current_week_notes(
    content_root: Path,
    *,
    as_of: date | None = None,
) -> tuple[StudyNote, ...]:
    """Return this week's notes, excluding generated weekly summaries."""

    current = as_of or datetime.now(SHANGHAI).date()
    week_start = current - timedelta(days=current.weekday())
    week_end = week_start + timedelta(days=6)
    collection = load_notes(content_root / "notes")
    return tuple(
        note
        for note in collection.notes
        if week_start <= note.date <= week_end and note.topic != SUMMARY_TOPIC
    )


def _weekly_summary_body(notes: tuple[StudyNote, ...]) -> str:
    topics: dict[str, list[StudyNote]] = {}
    tag_counts: dict[str, int] = {}
    for note in notes:
        topics.setdefault(note.topic, []).append(note)
        for tag in note.tags:
            if tag != FRAGMENT_TAG:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    lines = [
        "## 本周概览",
        "",
        f"本周共记录 **{len(notes)}** 条学习内容，覆盖 **{len(topics)}** 个专题方向。",
        "",
        "## 记录清单",
        "",
    ]
    for note in notes:
        lines.extend(
            [
                f"- **{note.title}** · {note.date.isoformat()} · `{note.status}`",
                f"  {note.summary}",
            ],
        )

    lines.extend(["", "## 专题线索", ""])
    for topic, topic_notes in sorted(topics.items()):
        titles = "、".join(note.title for note in topic_notes)
        lines.append(f"- **{topic}**：{titles}")

    top_tags = sorted(tag_counts, key=lambda tag: (-tag_counts[tag], tag))[:5]
    lines.extend(["", "## 下次整理提示", ""])
    if top_tags:
        lines.append(f"- 反复出现的标签：{'、'.join(top_tags)}。哪些内容已经可以形成稳定结论？")
    lines.extend(
        [
            "- 哪一条记录还停留在直觉，需要代码或资料进一步验证？",
            "- 哪些碎片可以合并进已有专题，哪些应该继续保留为开放问题？",
            "",
            "> 这是系统生成的结构化草稿。检查、补充观点后，再将 `status` 改为 `published`。",
        ],
    )
    return "\n".join(lines)


def save_weekly_summary(
    content_root: Path,
    *,
    as_of: date | None = None,
) -> tuple[StudyNote, bool]:
    """Create an idempotent weekly summary draft."""

    current = as_of or datetime.now(SHANGHAI).date()
    iso_year, iso_week, _ = current.isocalendar()
    note_id = f"weekly-summary-{iso_year}-w{iso_week:02d}"
    collection = load_notes(content_root / "notes")
    existing = next((note for note in collection.notes if note.id == note_id), None)
    if existing is not None:
        return existing, False

    notes = current_week_notes(content_root, as_of=current)
    if not notes:
        raise ValueError("本周还没有可汇总的学习记录")

    tags = sorted({tag for note in notes for tag in note.tags if tag != FRAGMENT_TAG})
    path = content_root / "notes" / f"{current.isoformat()}-{note_id}.md"
    note = _write_note(
        path,
        {
            "id": note_id,
            "title": f"{iso_year} 年第 {iso_week:02d} 周学习汇总",
            "date": current.isoformat(),
            "status": "draft",
            "summary": f"自动整理本周 {len(notes)} 条记录，形成专题线索和后续复盘提示。",
            "tags": ["周总结", *tags[:5]],
            "topic": SUMMARY_TOPIC,
        },
        _weekly_summary_body(notes),
    )
    return note, True


def _settings_path(content_root: Path) -> Path:
    return content_root / "workspace.yaml"


def load_workspace_settings(content_root: Path) -> WorkspaceSettings:
    """Load schedule settings, falling back safely when no file exists."""

    path = _settings_path(content_root)
    if not path.exists():
        return WorkspaceSettings()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return WorkspaceSettings()
    try:
        enabled = bool(data.get("enabled", False))
        weekday = int(data.get("weekday", 6))
        hour, minute = (int(part) for part in str(data.get("time", "20:00")).split(":", 1))
        if weekday not in range(7) or hour not in range(24) or minute not in range(60):
            raise ValueError
    except (TypeError, ValueError):
        return WorkspaceSettings()
    return WorkspaceSettings(enabled=enabled, weekday=weekday, hour=hour, minute=minute)


def save_workspace_settings(
    content_root: Path,
    *,
    enabled: bool,
    weekday: int,
    time_value: str,
) -> WorkspaceSettings:
    """Validate and persist the local weekly schedule."""

    try:
        hour, minute = (int(part) for part in time_value.split(":", 1))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("时间必须使用 HH:MM 格式") from error
    if weekday not in range(7):
        raise ValueError("请选择有效的星期")
    if hour not in range(24) or minute not in range(60):
        raise ValueError("请选择有效的时间")

    settings = WorkspaceSettings(enabled=enabled, weekday=weekday, hour=hour, minute=minute)
    path = _settings_path(content_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "enabled": settings.enabled,
                "weekday": settings.weekday,
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
    """Calculate the next scheduled run in Asia/Shanghai."""

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
    poll_seconds: float = 60,
) -> None:
    """Generate the week's draft after its configured local run time."""

    while True:
        settings = load_workspace_settings(content_root)
        now = datetime.now(SHANGHAI)
        scheduled_this_week = (
            now - timedelta(days=now.weekday()) + timedelta(days=settings.weekday)
        ).replace(
            hour=settings.hour,
            minute=settings.minute,
            second=0,
            microsecond=0,
        )
        if settings.enabled and now >= scheduled_this_week:
            try:
                save_weekly_summary(content_root, as_of=now.date())
            except ValueError:
                pass
        await asyncio.sleep(poll_seconds)
