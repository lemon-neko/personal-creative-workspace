"""Local phase execution pages; all changes are explicit form submissions."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.agent_core import DEFAULT_PROJECT_ID
from app.focus import (
    FOCUS_AREAS,
    FOCUS_PRIORITIES,
    FOCUS_STATUSES,
    FOCUS_VISIBILITIES,
    FocusRepository,
    focus_snapshot,
    is_overdue,
)
from app.web import TEMPLATES, not_found
from app.workspace import SHANGHAI


router = APIRouter()


def _repository(request: Request) -> FocusRepository:
    return request.app.state.focus


def _today():
    return datetime.now(SHANGHAI).date()


def _focus_context(request: Request, *, error: str = "") -> dict:
    repository = _repository(request)
    snapshot = focus_snapshot(repository)
    cycle = snapshot["focus_cycle"]
    goals = repository.goals(cycle.id) if cycle else ()
    deliveries = repository.cycle_deliverables(cycle.id) if cycle else ()
    actions = repository.cycle_actions(cycle.id) if cycle else ()
    return {
        "active_page": "focus",
        **snapshot,
        "all_goals": goals,
        "all_deliverables": deliveries,
        "all_actions": actions,
        "goal_lookup": {goal.id: goal for goal in goals},
        "deliverable_lookup": {row.id: row for row in deliveries},
        "decisions": repository.decisions(cycle.id) if cycle else (),
        "status_labels": FOCUS_STATUSES,
        "areas": tuple(sorted(FOCUS_AREAS)),
        "priorities": tuple(sorted(FOCUS_PRIORITIES)),
        "visibilities": FOCUS_VISIBILITIES,
        "today": _today(),
        "is_overdue": is_overdue,
        "error": error,
    }


def _goal_context(request: Request, goal_id: str, *, error: str = "") -> dict | None:
    repository = _repository(request)
    goal = repository.goal(goal_id)
    if goal is None:
        return None
    deliverables = repository.deliverables(goal_id)
    return {
        "active_page": "focus",
        "goal": goal,
        "cycle": repository.cycle(goal.cycle_id),
        "deliverables": deliverables,
        "actions": {row.id: repository.actions(row.id) for row in deliverables},
        "linked_tasks": request.app.state.agent_core.linked_tasks(goal_id),
        "status_labels": FOCUS_STATUSES,
        "today": _today(),
        "week_start": focus_snapshot(repository)["focus_week_start"],
        "is_overdue": is_overdue,
        "error": error,
    }


def _render_goal(request: Request, goal_id: str, error: str, status_code: int = 422) -> HTMLResponse:
    context = _goal_context(request, goal_id, error=error)
    if context is None:
        return not_found(request, "focus")
    return TEMPLATES.TemplateResponse(request=request, name="focus_goal.html", context=context, status_code=status_code)


@router.get("/focus", response_class=HTMLResponse, name="focus")
async def focus(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request=request, name="focus.html", context=_focus_context(request))


@router.get("/focus/history", response_class=HTMLResponse, name="focus_history")
async def focus_history(request: Request) -> HTMLResponse:
    repository = _repository(request)
    cycles = repository.cycles()
    return TEMPLATES.TemplateResponse(
        request=request, name="focus_history.html",
        context={
            "active_page": "focus", "cycles": cycles,
            "goals_by_cycle": {cycle.id: repository.goals(cycle.id) for cycle in cycles},
            "status_labels": FOCUS_STATUSES,
        },
    )


@router.post("/focus/cycles", name="create_focus_cycle")
async def create_focus_cycle(request: Request, title: str = Form(), starts_on: str = Form(), ends_on: str = Form()) -> HTMLResponse:
    try:
        _repository(request).create_cycle(
            key=f"{starts_on}:{ends_on}", title=title, starts_on=starts_on, ends_on=ends_on,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(request=request, name="focus.html", context=_focus_context(request, error=str(error)), status_code=422)
    return RedirectResponse(request.url_for("focus"), status_code=303)


@router.post("/focus/goals", name="create_focus_goal")
async def create_focus_goal(request: Request, cycle_id: str = Form(), title: str = Form(),
                            area: str = Form(), priority: str = Form(), summary: str = Form(default=""),
                            target_on: str = Form(default=""), visibility: str = Form(default="overview"),
                            module_key: str = Form(default="")) -> HTMLResponse:
    try:
        goal = _repository(request).create_goal(
            cycle_id=cycle_id, title=title, area=area, priority=priority,
            summary=summary, target_on=target_on, visibility=visibility, module_key=module_key,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(request=request, name="focus.html", context=_focus_context(request, error=str(error)), status_code=422)
    return RedirectResponse(request.url_for("focus_goal", goal_id=goal.id), status_code=303)


@router.get("/focus/goals/{goal_id}", response_class=HTMLResponse, name="focus_goal")
async def focus_goal(request: Request, goal_id: str) -> HTMLResponse:
    context = _goal_context(request, goal_id)
    if context is None:
        return not_found(request, "focus")
    return TEMPLATES.TemplateResponse(request=request, name="focus_goal.html", context=context)


@router.post("/focus/goals/{goal_id}", name="update_focus_goal")
async def update_focus_goal(request: Request, goal_id: str, title: str = Form(),
                            summary: str = Form(default=""), target_on: str = Form(default=""),
                            status: str = Form(), external_url: str = Form(default=""),
                            area: str = Form(), priority: str = Form(), visibility: str = Form(),
                            module_key: str = Form(default="")) -> HTMLResponse:
    try:
        _repository(request).update_goal(goal_id, title=title, summary=summary,
                                         target_on=target_on, status=status, external_url=external_url,
                                         area=area, priority=priority, visibility=visibility,
                                         module_key=module_key)
    except KeyError:
        return not_found(request, "focus")
    except ValueError as error:
        return _render_goal(request, goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=goal_id), status_code=303)


@router.post("/focus/goals/{goal_id}/deliverables", name="create_focus_deliverable")
async def create_focus_deliverable(request: Request, goal_id: str, title: str = Form(), due_on: str = Form(default="")) -> HTMLResponse:
    try:
        _repository(request).create_deliverable(goal_id=goal_id, title=title, due_on=due_on)
    except ValueError as error:
        return _render_goal(request, goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=goal_id), status_code=303)


@router.post("/focus/decisions/{decision_id}/status", name="update_focus_decision")
async def update_focus_decision(request: Request, decision_id: str,
                                status: str = Form()) -> HTMLResponse:
    try:
        _repository(request).update_decision_status(decision_id, status=status)
    except KeyError:
        return not_found(request, "focus")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request, name="focus.html",
            context=_focus_context(request, error=str(error)), status_code=422,
        )
    return RedirectResponse(request.url_for("focus"), status_code=303)


@router.post("/focus/deliverables/{deliverable_id}", name="update_focus_deliverable")
async def update_focus_deliverable(request: Request, deliverable_id: str, title: str = Form(),
                                   due_on: str = Form(default=""), status: str = Form()) -> HTMLResponse:
    repository = _repository(request)
    row = repository.deliverable(deliverable_id)
    if row is None:
        return not_found(request, "focus")
    try:
        repository.update_deliverable(deliverable_id, title=title, due_on=due_on, status=status)
    except ValueError as error:
        return _render_goal(request, row.goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=row.goal_id), status_code=303)


@router.post("/focus/deliverables/{deliverable_id}/week", name="toggle_focus_week")
async def toggle_focus_week(request: Request, deliverable_id: str, selected: bool = Form(default=False)) -> HTMLResponse:
    repository = _repository(request)
    row = repository.deliverable(deliverable_id)
    if row is None:
        return not_found(request, "focus")
    try:
        repository.set_week_focus(deliverable_id, selected=selected, on=_today())
    except ValueError as error:
        return _render_goal(request, row.goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=row.goal_id), status_code=303)


@router.post("/focus/deliverables/{deliverable_id}/actions", name="create_focus_action")
async def create_focus_action(request: Request, deliverable_id: str, title: str = Form(), due_on: str = Form(default="")) -> HTMLResponse:
    repository = _repository(request)
    row = repository.deliverable(deliverable_id)
    if row is None:
        return not_found(request, "focus")
    try:
        repository.create_action(deliverable_id=deliverable_id, title=title, due_on=due_on)
    except ValueError as error:
        return _render_goal(request, row.goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=row.goal_id), status_code=303)


@router.post("/focus/actions/{action_id}", name="update_focus_action")
async def update_focus_action(request: Request, action_id: str, title: str = Form(),
                              due_on: str = Form(default=""), status: str = Form()) -> HTMLResponse:
    repository = _repository(request)
    row = repository.action(action_id)
    if row is None:
        return not_found(request, "focus")
    goal_id = repository.deliverable(row.deliverable_id).goal_id
    try:
        repository.update_action(action_id, title=title, due_on=due_on, status=status)
    except ValueError as error:
        return _render_goal(request, goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=goal_id), status_code=303)


@router.post("/focus/actions/{action_id}/local-task", name="prepare_focus_action_task")
async def prepare_focus_action_task(request: Request, action_id: str) -> HTMLResponse:
    focus = _repository(request)
    action = focus.action(action_id)
    delivery = focus.deliverable(action.deliverable_id) if action else None
    goal = focus.goal(delivery.goal_id) if delivery else None
    if action is None or goal is None:
        return not_found(request, "focus")
    runtime = request.app.state.agent_core
    existing = runtime.linked_tasks(goal.id).get(action_id)
    if existing:
        return RedirectResponse(request.url_for("task_detail", task_id=existing), status_code=303)
    if action.status in {"done", "paused"} or goal.visibility == "detail_only":
        return _render_goal(request, goal.id, "仅首页可见且未完成、未暂缓的行动可以准备本地工作纸。", 409)
    task = runtime.create_task(
        title=action.title, objective=action.title,
        task_type={"venture": "build", "learning": "learning", "creation": "creation"}.get(goal.area, "research"),
        project_id=DEFAULT_PROJECT_ID, source_action_id=action.id,
    )
    try:
        run = runtime.plan_task(task.id)
    except ValueError:
        return RedirectResponse(request.url_for("task_detail", task_id=task.id), status_code=303)
    return RedirectResponse(request.url_for("run_detail", run_id=run.id), status_code=303)


@router.post("/focus/actions/{action_id}/today", name="toggle_focus_today")
async def toggle_focus_today(request: Request, action_id: str, selected: bool = Form(default=False)) -> HTMLResponse:
    repository = _repository(request)
    row = repository.action(action_id)
    if row is None:
        return not_found(request, "focus")
    goal_id = repository.deliverable(row.deliverable_id).goal_id
    try:
        repository.set_day_focus(action_id, selected=selected, on=_today())
    except ValueError as error:
        return _render_goal(request, goal_id, str(error))
    return RedirectResponse(request.url_for("focus_goal", goal_id=goal_id), status_code=303)


@router.get("/focus/checkin", response_class=HTMLResponse, name="focus_checkin")
async def focus_checkin(request: Request) -> HTMLResponse:
    repository = _repository(request)
    cycle = repository.current_cycle()
    context = {
        "active_page": "focus", "cycle": cycle,
        "checkin": repository.checkin(cycle.id, _today()) if cycle else None,
        "week_start": focus_snapshot(repository)["focus_week_start"],
    }
    return TEMPLATES.TemplateResponse(request=request, name="focus_checkin.html", context=context)


@router.post("/focus/checkin", name="save_focus_checkin")
async def save_focus_checkin(request: Request, cycle_id: str = Form(), completed: str = Form(default=""),
                             friction: str = Form(default=""), next_three: str = Form(default="")) -> HTMLResponse:
    try:
        _repository(request).save_checkin(cycle_id, on=_today(), completed=completed,
                                           friction=friction, next_three=next_three)
    except ValueError:
        return not_found(request, "focus")
    return RedirectResponse(request.url_for("focus_checkin"), status_code=303)
