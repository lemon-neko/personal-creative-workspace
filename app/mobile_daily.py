"""The paired phone's read-only projection of today's desktop schedule."""

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.atomic import atomic_write_text, content_lock
from app.database import SHANGHAI


class DailyTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    when: str = Field(default="", pattern=r"^(?:[0-9]{2}:[0-9]{2}|[0-9]{4}-[0-9]{2}-[0-9]{2})?$")


class DailySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    today: list[DailyTask] = Field(max_length=40)
    overdue: list[DailyTask] = Field(max_length=40)
    unplanned: list[DailyTask] = Field(max_length=40)
    done: list[DailyTask] = Field(max_length=40)


class SavedDailySnapshot(DailySnapshot):
    synced_at: datetime


def save_daily_snapshot(data_root: Path, snapshot: DailySnapshot, now: datetime) -> None:
    saved = SavedDailySnapshot(**snapshot.model_dump(), synced_at=now)
    with content_lock(data_root / "working"):
        atomic_write_text(data_root / "working" / "mobile-daily.json", saved.model_dump_json())


def read_daily_snapshot(data_root: Path, today: date) -> SavedDailySnapshot | None:
    try:
        saved = SavedDailySnapshot.model_validate_json((data_root / "working" / "mobile-daily.json").read_text())
    except (OSError, ValueError):
        return None
    return saved if saved.day == today else None


def daily_now() -> datetime:
    return datetime.now(SHANGHAI)
