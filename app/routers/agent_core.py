"""Local project, task, run and artifact pages."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.agent_core import (
    ROLE_DEFINITIONS,
    RUN_STATUS_LABELS,
    TASK_STATUS_LABELS,
    TASK_TYPE_LABELS,
    AgentCoreRepository,
)
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
    return {
        "active_page": "tasks",
        "task": task,
        "project": project,
        "runs": runs,
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


@router.get("/tasks", response_class=HTMLResponse, name="tasks")
async def tasks(request: Request) -> HTMLResponse:
    repository = _repository(request)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "active_page": "tasks",
            "projects": repository.projects(),
            "tasks": repository.tasks(),
            "runs": repository.runs(),
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
    rows = tuple(
        (run, repository.task(run.task_id)) for run in repository.runs()
    )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="runs.html",
        context={
            "active_page": "tasks",
            "rows": rows,
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
    return {
        "active_page": "tasks",
        "run": run,
        "task": task,
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


@router.post("/runs/{run_id}/execute", name="execute_agent_run")
async def execute_agent_run(request: Request, run_id: str) -> HTMLResponse:
    repository = _repository(request)
    run = repository.run(run_id)
    if run is None:
        return not_found(request, "tasks")
    task = repository.task(run.task_id)
    if task is None:
        return not_found(request, "tasks")
    results = request.app.state.search.search(task.objective, limit=8)
    if not results:
        results = request.app.state.search.search(task.title, limit=8)
    try:
        repository.execute_run(run_id, results)
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
    except (KeyError, FileNotFoundError):
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
