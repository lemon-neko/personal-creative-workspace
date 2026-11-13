from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.assistant import AssistantContextBuilder
import app.focus as focus_module
import app.routers.focus as focus_router_module
from app.focus import FocusRepository, focus_snapshot, is_overdue, week_start
from app.main import create_app
from app.workspace import SHANGHAI


def _fictional_plan() -> tuple[dict, ...]:
    return (
        {
            "title": "完成社区服务演示",
            "area": "venture", "priority": "P0", "summary": "用一个场景完成演示。",
            "target_on": "2026-11-08",
            "deliverables": ({"title": "演示流程可运行", "due_on": "2026-10-18",
                              "actions": ({"title": "列出当前已完成步骤"},)},),
        },
        {
            "title": "私人安排样例", "area": "life", "priority": "P0",
            "visibility": "detail_only",
            "deliverables": ({"title": "PRIVATE_RELATION_DETAIL", "actions": ({"title": "PRIVATE_ACTION"},)},),
        },
    )


def test_private_import_is_atomic_and_idempotent(tmp_path: Path) -> None:
    repository = FocusRepository(tmp_path)
    options = dict(
        key="sample-period", title="虚构阶段", starts_on="2026-10-12", ends_on="2026-11-30",
        goals=_fictional_plan(), decisions=({"title": "检查进展", "due_on": "2026-10-25"},),
    )
    cycle = repository.import_plan(**options)
    second = repository.import_plan(**options)
    assert second.id == cycle.id
    assert len(repository.goals(cycle.id)) == 2
    assert len(repository.decisions(cycle.id)) == 1
    assert repository.decisions(cycle.id)[0].status == "planned"

    with pytest.raises(ValueError):
        repository.import_plan(
            **{**options, "key": "bad-period", "goals": (*_fictional_plan(), {"title": "无效领域", "area": "invalid", "priority": "P0"})}
        )
    assert len(repository.cycles()) == 1


def test_overdue_decision_waits_for_manual_resolution(tmp_path: Path) -> None:
    repository = FocusRepository(tmp_path)
    cycle = repository.import_plan(
        key="sample-period", title="虚构阶段", starts_on="2026-10-12", ends_on="2026-11-30",
        goals=_fictional_plan(),
        decisions=({"title": "第一次检查", "due_on": "2026-10-25"},
                   {"title": "第二次检查", "due_on": "2026-11-12"}),
    )
    first, second = repository.decisions(cycle.id)
    snapshot = focus_snapshot(repository, date(2026, 11, 1))
    assert snapshot["focus_next_decision"].id == first.id
    assert snapshot["focus_next_decision_overdue"] is True
    assert repository.decisions(cycle.id)[0].status == "planned"
    repository.update_decision_status(first.id, status="done")
    assert focus_snapshot(repository, date(2026, 11, 1))["focus_next_decision"].id == second.id


def test_daily_weekly_caps_and_private_projection(tmp_path: Path) -> None:
    repository = FocusRepository(tmp_path)
    cycle = repository.import_plan(
        key="sample-period", title="虚构阶段", starts_on="2026-10-12", ends_on="2026-11-30",
        goals=_fictional_plan(), decisions=(),
    )
    public, private = repository.goals(cycle.id)
    today = date(2026, 10, 12)
    for index in range(3):
        deliverable = repository.create_deliverable(goal_id=public.id, title=f"交付 {index}")
        repository.set_week_focus(deliverable.id, selected=True, on=today)
        action = repository.create_action(deliverable_id=deliverable.id, title=f"行动 {index}")
        repository.set_day_focus(action.id, selected=True, on=today)
    fourth = repository.create_deliverable(goal_id=public.id, title="第四项")
    with pytest.raises(ValueError, match="最多选择三项"):
        repository.set_week_focus(fourth.id, selected=True, on=today)
    fourth_action = repository.create_action(deliverable_id=fourth.id, title="第四个行动")
    with pytest.raises(ValueError, match="最多选择三项"):
        repository.set_day_focus(fourth_action.id, selected=True, on=today)
    private_delivery = repository.deliverables(private.id)[0]
    with pytest.raises(ValueError, match="仅详情可见"):
        repository.set_week_focus(private_delivery.id, selected=True, on=today)
    with pytest.raises(ValueError, match="仅详情可见"):
        repository.set_day_focus(repository.actions(private_delivery.id)[0].id, selected=True, on=today)

    snapshot = focus_snapshot(repository, today)
    assert len(snapshot["focus_week"]) == 3
    assert len(snapshot["focus_today"]) == 3
    assert set(snapshot["focus_today_goal_ids"].values()) == {public.id}
    assert all(goal.visibility == "overview" for goal in snapshot["focus_goals"])
    assert week_start(date(2026, 10, 18)) == "2026-10-12"
    assert is_overdue("2026-10-11", "planned", today)
    assert not is_overdue("2026-10-11", "done", today)
    repository.update_goal(
        public.id, title=public.title, summary=public.summary,
        target_on=public.target_on, status=public.status, external_url="",
        visibility="detail_only",
    )
    assert not focus_snapshot(repository, today)["focus_today"]
    assert not focus_snapshot(repository, today)["focus_week"]


def test_shanghai_midnight_drives_today_and_week(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repository = FocusRepository(tmp_path)
    repository.import_plan(
        key="sample-period", title="虚构阶段", starts_on="2026-10-12", ends_on="2026-11-30",
        goals=_fictional_plan(), decisions=(),
    )
    utc_instant = datetime(2026, 10, 11, 16, 30, tzinfo=timezone.utc)

    class FixedClock:
        @staticmethod
        def now(zone):
            assert zone is SHANGHAI
            return utc_instant.astimezone(zone)

    monkeypatch.setattr(focus_module, "datetime", FixedClock)
    monkeypatch.setattr(focus_router_module, "datetime", FixedClock)
    assert focus_snapshot(repository)["focus_today_date"] == "2026-10-12"
    assert focus_snapshot(repository)["focus_week_start"] == "2026-10-12"
    assert focus_router_module._today() == date(2026, 10, 12)


def test_pages_and_assistant_keep_detail_only_text_private(tmp_path: Path) -> None:
    application = create_app(content_root=tmp_path / "content", data_root=tmp_path,
                             enable_scheduler=False, enforce_security=True)
    repository = application.state.focus
    repository.import_plan(
        key="sample-period", title="虚构阶段", starts_on="2026-10-12", ends_on="2026-11-30",
        goals=_fictional_plan(), decisions=({"title": "检查进展", "due_on": "2026-10-25"},),
    )
    client = TestClient(application)
    home = client.get("/")
    overview = client.get("/focus")
    private_goal = next(goal for goal in repository.goals(repository.current_cycle().id) if goal.visibility == "detail_only")
    detail = client.get(f"/focus/goals/{private_goal.id}")
    assert home.status_code == 200 and overview.status_code == 200 and detail.status_code == 200
    assert "PRIVATE_RELATION_DETAIL" not in home.text
    assert "PRIVATE_RELATION_DETAIL" not in overview.text
    assert "PRIVATE_RELATION_DETAIL" in detail.text

    snapshot = AssistantContextBuilder(
        application.state.content_root, application.state.career,
        application.state.search, application.state.video,
        application.state.income, repository,
    ).build("先做什么")
    assert "完成社区服务演示" in snapshot.material
    assert '"phase_next_decision"' in snapshot.material
    assert '"next_action"' in snapshot.material
    assert "PRIVATE_RELATION_DETAIL" not in snapshot.material
    assert "PRIVATE_ACTION" not in snapshot.material

    missing = client.post("/focus/cycles", data={"title": "另一个阶段", "starts_on": "2026-12-01", "ends_on": "2026-12-31"})
    assert missing.status_code == 403
    token = client.cookies.get("pcw_csrf")
    decision_id = repository.decisions(repository.current_cycle().id)[0].id
    decision_saved = client.post(
        f"/focus/decisions/{decision_id}/status",
        data={"csrf_token": token, "status": "active"}, follow_redirects=False,
    )
    assert decision_saved.status_code == 303
    assert repository.decisions(repository.current_cycle().id)[0].status == "active"
    created = client.post("/focus/cycles", data={"csrf_token": token, "title": "另一个阶段", "starts_on": "2026-12-01", "ends_on": "2026-12-31"}, follow_redirects=False)
    assert created.status_code == 303


def test_career_job_plan_fields_are_manual_and_validated(tmp_path: Path) -> None:
    application = create_app(content_root=tmp_path / "content", data_root=tmp_path, enable_scheduler=False)
    repository = application.state.career
    job = repository.add_job(
        company="虚构组织", title="应用工程师", jd_text="真实输入由作者手工保存。",
        tier="A", applied_on="2026-10-15", next_action="准备项目讲解",
        next_action_on="2026-10-17",
    )
    assert job.tier == "A" and job.applied_on == "2026-10-15"
    updated = repository.update_job_plan(
        job.id, tier="B", applied_on=job.applied_on,
        next_action="跟进面试反馈", next_action_on="2026-10-20",
    )
    assert updated.next_action == "跟进面试反馈"
    with pytest.raises(ValueError, match="日期格式"):
        repository.update_job_plan(job.id, tier="B", applied_on="明天",
                                   next_action="", next_action_on="")


def test_focus_action_local_run_review_returns_to_source_without_completing_it(tmp_path: Path) -> None:
    app = create_app(content_root=tmp_path / "content", data_root=tmp_path,
                     enable_scheduler=False, enforce_security=True)
    focus = app.state.focus
    runtime = app.state.agent_core
    today = datetime.now(SHANGHAI).date()
    cycle = focus.import_plan(key="closed-loop", title="虚构阶段", starts_on=today.isoformat(),
                              ends_on=today.isoformat(), goals=_fictional_plan(), decisions=())
    goal, private = focus.goals(cycle.id)
    action = focus.actions(focus.deliverables(goal.id)[0].id)[0]
    private_action = focus.actions(focus.deliverables(private.id)[0].id)[0]
    focus.set_day_focus(action.id, selected=True, on=today)
    client = TestClient(app)
    detail = client.get(f"/focus/goals/{goal.id}")
    assert "准备本地工作纸" in detail.text
    token = client.cookies.get("pcw_csrf")
    path = f"/focus/actions/{action.id}/local-task"
    assert client.post(path).status_code == 403
    headers = {"x-csrf-token": token}
    assert client.post(f"/focus/actions/{private_action.id}/local-task", headers=headers).status_code == 409
    created = client.post(path, headers=headers, follow_redirects=False)
    assert created.status_code == 303 and "/runs/" in created.headers["location"]
    run_id = created.headers["location"].rsplit("/", 1)[1]
    task_id = runtime.linked_tasks(goal.id)[action.id]
    again = client.post(path, headers=headers, follow_redirects=False)
    assert again.headers["location"].endswith(f"/tasks/{task_id}")
    assert len(runtime.tasks()) == len(runtime.runs()) == 1
    assert "待执行" in client.get("/").text
    assert runtime.artifacts(run_id=run_id) == ()
    running = client.post(f"/runs/{run_id}/execute", headers=headers)
    assert running.status_code == 200
    assert "待验收" in client.get("/").text
    assert f"#action-{action.id}" in running.text
    assert runtime.run(run_id).status == "reviewing"

    focus.update_goal(goal.id, title=goal.title, summary=goal.summary, target_on=goal.target_on,
                      status=goal.status, external_url="", visibility="detail_only")
    for page in ("/", "/tasks", "/runs"):
        assert action.title not in client.get(page).text
    assert "查看本地任务" in client.get(f"/focus/goals/{goal.id}").text
    focus.update_goal(goal.id, title=goal.title, summary=goal.summary, target_on=goal.target_on,
                      status=goal.status, external_url="", visibility="overview")
    accepted = client.post(f"/runs/{run_id}/approve", headers=headers)
    assert accepted.status_code == 200 and "回到原行动" in accepted.text
    assert "待验收" not in client.get("/").text
    assert focus.action(action.id).status == "planned"
    assert runtime.artifacts(run_id=run_id)[0].status == "accepted"
