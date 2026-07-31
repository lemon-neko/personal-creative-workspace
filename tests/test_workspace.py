from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.content import load_notes
from app.main import create_app
from app.workspace import (
    WorkspaceSettings,
    load_workspace_settings,
    next_summary_run,
    save_fragment,
    save_weekly_summary,
    save_workspace_settings,
)


def test_save_fragment_creates_valid_draft_markdown(tmp_path: Path) -> None:
    note = save_fragment(
        tmp_path,
        title="理解 KV Cache",
        body="KV Cache 保存已经计算过的键和值，避免生成时重复计算。",
        tags="Transformer，推理",
        topic="transformer",
        captured_on=date(2026, 7, 30),
    )

    assert note.status == "draft"
    assert note.topic == "transformer"
    assert note.tags == ("Transformer", "推理", "碎片")
    assert note.source.exists()
    assert load_notes(tmp_path / "notes").notes == (note,)


def test_weekly_summary_is_structured_and_idempotent(tmp_path: Path) -> None:
    for title in ("注意力温度", "残差路径"):
        save_fragment(
            tmp_path,
            title=title,
            body=f"{title}的学习记录。",
            tags="Transformer",
            topic="transformer",
            captured_on=date(2026, 7, 30),
        )

    summary, created = save_weekly_summary(tmp_path, as_of=date(2026, 7, 31))
    duplicate, created_again = save_weekly_summary(tmp_path, as_of=date(2026, 7, 31))

    assert created is True
    assert created_again is False
    assert duplicate.source == summary.source
    assert summary.status == "draft"
    assert summary.topic == "weekly-review"
    assert "本周共记录 **2** 条" in summary.body
    assert "注意力温度" in summary.body


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
        now=datetime(2026, 7, 30, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert loaded == settings
    assert next_run == datetime(
        2026,
        8,
        2,
        20,
        30,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )


def test_disabled_schedule_has_no_next_run() -> None:
    assert next_summary_run(WorkspaceSettings()) is None


def test_workspace_page_captures_fragment_and_keeps_it_private(tmp_path: Path) -> None:
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    page = client.get("/workspace")
    saved = client.post(
        "/workspace/fragments",
        data={
            "title": "浏览器记录的碎片",
            "body": "这条内容由工作台写入 Markdown。",
            "tags": "FastAPI, 工作流",
            "topic": "platform",
        },
        follow_redirects=True,
    )

    assert page.status_code == 200
    assert "碎片工作台" in page.text
    assert saved.status_code == 200
    assert "碎片已保存为 Markdown 草稿" in saved.text
    assert "浏览器记录的碎片" in saved.text
    assert "浏览器记录的碎片" not in client.get("/notes").text


def test_workspace_can_generate_summary_and_save_schedule(tmp_path: Path) -> None:
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    client.post(
        "/workspace/fragments",
        data={
            "title": "一条本周记录",
            "body": "准备进入本周汇总。",
            "tags": "复盘",
            "topic": "workflow",
        },
    )

    summary = client.post("/workspace/summary", follow_redirects=True)
    schedule = client.post(
        "/workspace/schedule",
        data={"enabled": "on", "weekday": "4", "time": "21:15"},
        follow_redirects=True,
    )

    assert summary.status_code == 200
    assert "本周汇总草稿已生成" in summary.text
    assert "本周概览" in summary.text
    assert schedule.status_code == 200
    assert "定时汇总设置已保存" in schedule.text
    assert "运行中" in schedule.text


def test_workspace_rejects_empty_capture_and_empty_summary(tmp_path: Path) -> None:
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    capture = client.post(
        "/workspace/fragments",
        data={"title": " ", "body": " ", "tags": "", "topic": ""},
    )
    summary = client.post("/workspace/summary")

    assert capture.status_code == 422
    assert "标题不能为空" in capture.text
    assert summary.status_code == 422
    assert "本周还没有可汇总的学习记录" in summary.text
