from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent_core import DEFAULT_PROJECT_ID


def test_source_handoff_is_idempotent_and_private_run_stays_out_of_attention(runtime, focus):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    cycle = focus.import_plan(
        key="agent-runtime-test", title="虚构阶段", starts_on=today.isoformat(), ends_on=today.isoformat(),
        goals=({"title": "虚构私人目标", "area": "life", "priority": "P0", "visibility": "detail_only"},),
        decisions=(),
    )
    goal, = focus.goals(cycle.id)
    deliverable = focus.create_deliverable(goal_id=goal.id, title="虚构交付物")
    action = focus.create_action(deliverable_id=deliverable.id, title="虚构行动")
    event = focus.create_daily_event("虚构事件", today, slot=(today.isoformat(), 540))
    fields = dict(project_id=DEFAULT_PROJECT_ID, title="虚构任务", objective="核对测试资料", task_type="research")
    service = runtime.task_service

    with pytest.raises(ValueError, match="只能关联"):
        service.create_task(**fields, source_action_id=action.id, source_event_id=event)
    private = service.create_task(**fields, source_action_id=action.id)
    public = service.create_task(**fields, source_event_id=event)
    assert service.create_task(**fields, source_action_id=action.id) == private
    assert service.create_task(**fields, source_event_id=event) == public
    assert service.linked_tasks(goal.id) == {action.id: private.id}
    assert service.task_source(private.id) == (goal.id, action.id)
    assert service.private_task_ids() == {private.id}
    assert service.daily_task_ids() == {event: public.id}
    assert service.daily_task_source(public.id) == event
    assert service.daily_task_context(public.id) == (event, today.isoformat())
    runtime.plan_task(private.id)
    run = runtime.plan_task(public.id)
    assert [row["id"] for row in runtime.attention_runs()] == [run.id]
    assert sorted(row["event_id"] for row in focus.planner_activity(today.isoformat()) if row["action"] == "交给 AI") == (
        sorted((event, action.id))
    )
