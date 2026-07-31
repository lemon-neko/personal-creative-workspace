from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.content import load_items
from app.workspace import (
    WorkspaceSettings,
    create_item,
    items_directory,
    load_workspace_settings,
    move_to_trash,
    next_summary_run,
    permanently_delete,
    restore_from_trash,
    save_weekly_review,
    save_workspace_settings,
    set_item_status,
    trash_directory,
    update_item,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_body_only_capture_derives_title_summary_and_draft(tmp_path: Path) -> None:
    item = create_item(
        tmp_path,
        body="今天忽然觉得，很多效率问题其实是方向问题。\n\n还需要继续想。",
        tags="观察，工作, 观察",
        now=datetime(2026, 7, 31, 9, 12, tzinfo=SHANGHAI),
    )

    assert item.title == "今天忽然觉得，很多效率问题其实是方向问题"
    assert item.status == "draft"
    assert item.kind == "thought"
    assert item.tags == ("观察", "工作")
    assert item.created_at.isoformat() == "2026-07-31T09:12:00+08:00"
    assert load_items(items_directory(tmp_path)).get(item.id) == item


def test_create_rejects_empty_body_and_invalid_metadata(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="内容不能为空"):
        create_item(tmp_path, body=" ")
    with pytest.raises(ValueError, match="内容类型无效"):
        create_item(tmp_path, body="正文", kind="topic")


def test_edit_status_trash_restore_and_permanent_delete(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="原始正文。", title="原始标题")
    edited = update_item(
        tmp_path,
        item.id,
        body="修改后的正文。",
        title="修改后的标题",
        tags="成长",
        category="写作",
    )
    published = set_item_status(tmp_path, item.id, "published")

    assert edited.title == "修改后的标题"
    assert published.status == "published"

    trashed = move_to_trash(tmp_path, item.id)
    assert load_items(items_directory(tmp_path)).get(item.id) is None
    assert load_items(trash_directory(tmp_path)).get(item.id) == trashed

    restored = restore_from_trash(tmp_path, item.id)
    assert restored.id == item.id
    move_to_trash(tmp_path, item.id)
    with pytest.raises(ValueError, match="永久删除"):
        permanently_delete(tmp_path, item.id, "删除")
    permanently_delete(tmp_path, item.id, "永久删除")
    assert load_items(trash_directory(tmp_path)).get(item.id) is None


def test_weekly_review_ai_success_fallback_and_idempotency(tmp_path: Path) -> None:
    for hour, body in ((9, "想到写作。"), (16, "想到散步。")):
        create_item(
            tmp_path,
            body=body,
            now=datetime(2026, 7, 30, hour, 0, tzinfo=SHANGHAI),
        )

    def broken(_items):
        raise RuntimeError("offline")

    review, created, used_ai = save_weekly_review(
        tmp_path,
        as_of=date(2026, 7, 31),
        summarizer=broken,
    )
    duplicate, created_again, _ = save_weekly_review(
        tmp_path,
        as_of=date(2026, 7, 31),
        summarizer=lambda _items: "# 不应运行",
    )

    assert created is True
    assert used_ai is False
    assert review.kind == "weekly-review"
    assert review.status == "draft"
    assert "本周 / This Week" in review.body
    assert "想到写作" in review.body
    assert created_again is False
    assert duplicate.id == review.id


def test_weekly_review_uses_ai_candidate(tmp_path: Path) -> None:
    create_item(
        tmp_path,
        body="一条记录。",
        now=datetime(2026, 7, 31, 10, 0, tzinfo=SHANGHAI),
    )

    review, _, used_ai = save_weekly_review(
        tmp_path,
        as_of=date(2026, 7, 31),
        summarizer=lambda _items: "## 本周 / This Week\n\nAI 整理。",
    )

    assert used_ai is True
    assert "AI 整理" in review.body


def test_empty_week_cannot_generate_review(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="本周还没有"):
        save_weekly_review(tmp_path, as_of=date(2026, 7, 31))


def test_workspace_settings_and_next_run(tmp_path: Path) -> None:
    settings = save_workspace_settings(
        tmp_path,
        enabled=True,
        weekday=6,
        time_value="20:30",
    )
    loaded = load_workspace_settings(tmp_path)
    next_run = next_summary_run(
        settings,
        now=datetime(2026, 7, 30, 10, 0, tzinfo=SHANGHAI),
    )

    assert loaded == settings
    assert next_run == datetime(2026, 8, 2, 20, 30, tzinfo=SHANGHAI)
    assert next_summary_run(WorkspaceSettings()) is None
