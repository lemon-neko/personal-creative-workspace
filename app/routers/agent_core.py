"""Local project, task, run and artifact pages."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.agent_core import (
    ROLE_DEFINITIONS,
    RUN_STATUS_LABELS,
    TASK_STATUS_LABELS,
    TASK_TYPE_LABELS,
    AgentCoreRepository,
)
from app.agent_runtime.domain.exceptions import InputLimitError, PreviewError
from app.web import TEMPLATES, not_found


router = APIRouter()


def _repository(request: Request) -> AgentCoreRepository:
    return request.app.state.agent_core


def _task_context(
    request: Request,
    task_id: str,
    *,
    error: str = "",
) -> dict | None:
    repository = _repository(request)
    task = repository.task(task_id)
    if task is None:
        return None
    project = repository.project(task.project_id)
    runs = repository.runs(task_id=task.id)
    daily_source, daily_day = repository.task_service.daily_task_context(task.id)
    return {
        "daily_day": daily_day,
        "active_page": "tasks",
        "task": task,
        "project": project,
        "source": repository.task_source(task.id),
        "daily_source": daily_source,
        "runs": runs,
        "planned_decisions": repository.planned_decisions(),
        "review_run": next((run for run in runs if run.status == "reviewing"), None),
        "artifacts": repository.artifacts(task_id=task.id),
        "task_status_labels": TASK_STATUS_LABELS,
        "run_status_labels": RUN_STATUS_LABELS,
        "task_type_labels": TASK_TYPE_LABELS,
        "role": next(
            (value for value in ROLE_DEFINITIONS.values() if value[0] == task.assigned_role),
            (task.assigned_role, task.assigned_role, ""),
        ),
        "error": error,
    }


@router.get("/legacy/tasks", response_class=HTMLResponse, name="legacy_tasks")
async def tasks(request: Request) -> HTMLResponse:
    repository = _repository(request)
    private_ids = repository.private_task_ids()
    visible_tasks = tuple(task for task in repository.tasks() if task.id not in private_ids)
    latest = {}
    for run in repository.runs():
        latest.setdefault(run.task_id, run)
    decisions = repository.planned_decisions()
    groups = {key: [] for key in ("decision", "reviewing", "running", "ready", "failed", "completed")}
    for task in visible_tasks:
        run = latest.get(task.id)
        state = decisions.get(run.id, task.status) if run else task.status
        group = {
            "draft": "ready", "planned": "ready", "resume": "ready", "cancelled": "completed",
        }.get(state, state)
        groups[group].append((task, run, state))
    return TEMPLATES.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "active_page": "tasks",
            "projects": repository.projects(),
            "tasks": visible_tasks,
            "workflow_groups": groups,
            "run_status_labels": RUN_STATUS_LABELS,
            "task_status_labels": TASK_STATUS_LABELS,
            "task_type_labels": TASK_TYPE_LABELS,
        },
    )


@router.post("/projects", name="create_workspace_project")
async def create_workspace_project(
    request: Request,
    title: str = Form(...),
    description: str = Form(default=""),
) -> HTMLResponse:
    try:
        _repository(request).create_project(title=title, description=description)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(request.url_for("tasks"), status_code=303)


@router.post("/tasks", name="create_workspace_task")
async def create_workspace_task(
    request: Request,
    title: str = Form(...),
    objective: str = Form(...),
    task_type: str = Form(...),
    project_id: str = Form(...),
    priority: int = Form(default=3),
) -> HTMLResponse:
    try:
        task = _repository(request).create_task(
            title=title,
            objective=objective,
            task_type=task_type,
            project_id=project_id,
            priority=priority,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(
        request.url_for("task_detail", task_id=task.id), status_code=303
    )


@router.get("/tasks/{task_id}", response_class=HTMLResponse, name="task_detail")
async def task_detail(request: Request, task_id: str) -> HTMLResponse:
    context = _task_context(request, task_id)
    if context is None:
        return not_found(request, "tasks")
    return TEMPLATES.TemplateResponse(
        request=request, name="task_detail.html", context=context
    )


@router.post("/tasks/{task_id}/plan", name="plan_workspace_task")
async def plan_workspace_task(request: Request, task_id: str) -> HTMLResponse:
    try:
        run = _repository(request).plan_task(task_id)
    except KeyError:
        return not_found(request, "tasks")
    except ValueError as error:
        context = _task_context(request, task_id, error=str(error))
        if context is None:
            return not_found(request, "tasks")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="task_detail.html",
            context=context,
            status_code=409,
        )
    return RedirectResponse(
        request.url_for("run_detail", run_id=run.id), status_code=303
    )


@router.get("/runs", response_class=HTMLResponse, name="runs")
async def runs(request: Request) -> HTMLResponse:
    repository = _repository(request)
    private_ids = repository.private_task_ids()
    rows = tuple(
        (run, repository.task(run.task_id)) for run in repository.runs()
        if run.task_id not in private_ids
    )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="runs.html",
        context={
            "active_page": "tasks",
            "rows": rows,
            "planned_decisions": repository.planned_decisions(),
            "run_status_labels": RUN_STATUS_LABELS,
        },
    )


def _run_context(request: Request, run_id: str, *, error: str = "") -> dict | None:
    repository = _repository(request)
    run = repository.run(run_id)
    if run is None:
        return None
    task = repository.task(run.task_id)
    if task is None:
        return None
    decision = repository.decision(run_id)
    preview = repository.run_service.model_preview(run, task, decision)
    daily_source, daily_day = repository.task_service.daily_task_context(task.id)
    return {
        "daily_day": daily_day,
        "active_page": "tasks",
        "run": run,
        "task": task,
        "source": repository.task_source(task.id),
        "daily_source": daily_source,
        "decision": decision,
        "ai_preview": preview,
        "model_enabled": repository.run_service.model_enabled,
        "steps": repository.steps(run.id),
        "tool_calls": repository.tool_calls(run.id),
        "artifacts": repository.artifacts(run_id=run.id),
        "run_status_labels": RUN_STATUS_LABELS,
        "task_status_labels": TASK_STATUS_LABELS,
        "role": next(
            (value for value in ROLE_DEFINITIONS.values() if value[0] == run.role_key),
            (run.role_key, run.role_key, ""),
        ),
        "error": error,
    }


@router.get("/runs/{run_id}", response_class=HTMLResponse, name="run_detail")
async def run_detail(request: Request, run_id: str) -> HTMLResponse:
    context = _run_context(request, run_id)
    if context is None:
        return not_found(request, "tasks")
    return TEMPLATES.TemplateResponse(
        request=request, name="run_detail.html", context=context
    )


def _run_error(request: Request, run_id: str, error: str, status: int = 409) -> HTMLResponse:
    context = _run_context(request, run_id, error=error)
    if context is None:
        return not_found(request, "tasks")
    return TEMPLATES.TemplateResponse(request=request, name="run_detail.html", context=context, status_code=status)


@router.post("/runs/{run_id}/ai", name="execute_agent_model")
def execute_agent_model(
    request: Request, run_id: str, background_tasks: BackgroundTasks,
    preview_fingerprint: str = Form(), background: bool = Form(False),
) -> HTMLResponse:
    repository = _repository(request)

    def finish_safely(finish):
        try:
            finish()
        except Exception:
            logging.getLogger(__name__).warning("Background agent run failed: %s", run_id)

    try:
        repository.run_service.execute_model(
            run_id, preview_fingerprint,
            dispatch=(lambda finish: background_tasks.add_task(finish_safely, finish)) if background else None,
        )
    except KeyError:
        return not_found(request, "tasks")
    except InputLimitError as error:
        return _run_error(request, run_id, str(error), 422)
    except PreviewError as error:
        return _run_error(request, run_id, str(error))
    except (RuntimeError, ValueError, OSError, httpx.HTTPError):
        return _run_error(request, run_id, "AI 未能完成本次运行。请刷新确认当前状态；若已失败，可重新规划。")
    return RedirectResponse(request.url_for("run_detail", run_id=run_id), status_code=303)


@router.post("/runs/{run_id}/objective", name="update_agent_objective")
async def update_agent_objective(request: Request, run_id: str, objective: str = Form()) -> HTMLResponse:
    try:
        _repository(request).update_run_objective(run_id, objective)
    except ValueError as error:
        return _run_error(request, run_id, str(error), 422)
    return RedirectResponse(request.url_for("run_detail", run_id=run_id), status_code=303)


@router.post("/runs/{run_id}/decision", name="answer_agent_decision")
async def answer_agent_decision(request: Request, run_id: str, answer: str = Form()) -> HTMLResponse:
    try:
        _repository(request).answer_decision(run_id, answer)
    except ValueError as error:
        return _run_error(request, run_id, str(error))
    return RedirectResponse(request.url_for("run_detail", run_id=run_id), status_code=303)


@router.post("/runs/{run_id}/execute", name="execute_agent_run")
async def execute_agent_run(request: Request, run_id: str) -> HTMLResponse:
    repository = _repository(request)
    try:
        repository.run_service.execute_run(run_id)
    except KeyError:
        return not_found(request, "tasks")
    except (RuntimeError, ValueError, OSError) as error:
        context = _run_context(request, run_id, error=str(error))
        if context is None:
            return not_found(request, "tasks")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="run_detail.html",
            context=context,
            status_code=409,
        )
    return RedirectResponse(
        request.url_for("run_detail", run_id=run_id), status_code=303
    )


@router.post("/runs/{run_id}/approve", name="approve_agent_run")
async def approve_agent_run(request: Request, run_id: str) -> HTMLResponse:
    try:
        _repository(request).approve_run(run_id)
    except KeyError:
        return not_found(request, "tasks")
    except ValueError as error:
        context = _run_context(request, run_id, error=str(error))
        if context is None:
            return not_found(request, "tasks")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="run_detail.html",
            context=context,
            status_code=409,
        )
    return RedirectResponse(
        request.url_for("run_detail", run_id=run_id), status_code=303
    )


@router.post("/runs/{run_id}/cancel", name="cancel_agent_run")
async def cancel_agent_run(request: Request, run_id: str) -> HTMLResponse:
    try:
        _repository(request).cancel_run(run_id)
    except KeyError:
        return not_found(request, "tasks")
    except ValueError as error:
        return _run_error(request, run_id, str(error))
    return RedirectResponse(
        request.url_for("run_detail", run_id=run_id), status_code=303
    )


@router.get(
    "/artifacts/{artifact_id}", response_class=HTMLResponse, name="agent_artifact"
)
async def agent_artifact(request: Request, artifact_id: str) -> HTMLResponse:
    repository = _repository(request)
    artifact = repository.artifact(artifact_id)
    if artifact is None:
        return not_found(request, "tasks")
    try:
        content = repository.artifact_content(artifact_id)
    except (KeyError, FileNotFoundError, ValueError):
        return not_found(request, "tasks")
    task = repository.task(artifact.task_id)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="agent_artifact.html",
        context={
            "active_page": "tasks",
            "artifact": artifact,
            "task": task,
            "content": content,
        },
    )
