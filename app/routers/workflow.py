"""Desktop workbench handoffs and native Autoloop controls."""

import asyncio
import re
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app import workflow_control as control
from app.database import SHANGHAI
from app.plugins import WORKBENCH_ORIGIN
from app.web import TEMPLATES
from app.workflow_store import identifier

router = APIRouter()
OPAQUE_ID = re.compile(r"[a-zA-Z0-9_.:-]{1,120}")


@router.get("/tasks", response_class=HTMLResponse, name="tasks")
async def tasks_home(request: Request):
    if request.app.state.workflow is None:
        if request.app.state.plugins_enabled:
            return TEMPLATES.TemplateResponse(
                request=request, name="workflow.html", status_code=503,
                context={"active_page": "tasks", "configuration_unavailable": True},
            )
        from app.routers.agent_core import tasks

        return await tasks(request)
    return await dashboard(request)


def service(request: Request):
    workflow = request.app.state.workflow
    if workflow is None:
        raise HTTPException(503, "AI 工作流暂不可用")
    return workflow


async def call(workflow, path, **kwargs):
    try:
        return await workflow.autoloop.request(path, **kwargs)
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (400, 404, 409, 422):
            try:
                detail = error.response.json().get("error")
            except (ValueError, AttributeError):
                detail = None
            raise HTTPException(error.response.status_code, str(detail or "Autoloop 未接受操作")[:350]) from error
        raise HTTPException(503, "Autoloop 暂不可用，请稍后重试") from error
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(503, "Autoloop 暂不可用，请稍后重试") from error


class TaskHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)


@router.post("/workflow/handoff")
async def handoff(request: Request, task: TaskHandoff):
    if request.app.state.enforce_security and request.headers.get("origin") != WORKBENCH_ORIGIN:
        raise HTTPException(403, "任务交接只接受工作台页面")
    if not OPAQUE_ID.fullmatch(task.id):
        raise HTTPException(422, "任务 ID 无效")
    try:
        item = service(request).store.handoff(f"sp:{task.id}", task.title)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"url": str(request.url_for("workflow_item", item_id=item))}


@router.post("/workflow/new")
def new_item(request: Request, title: str = Form()):
    try:
        item = service(request).store.handoff(f"manual:{identifier()}", title)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return RedirectResponse(request.url_for("workflow_item", item_id=item), 303)


async def dashboard(request: Request, view="overview"):
    workflow = service(request)
    return TEMPLATES.TemplateResponse(request=request, name="workflow.html", context={
        "active_page": "tasks", "items": workflow.store.active_items(), "state_labels": LABELS,
        "execution_backend": workflow.execution_backend, "runtime_error": workflow.error, "view": view,
    })


@router.get("/tasks/history", name="workflow_history")
async def history(request: Request):
    return await dashboard(request, "history")


@router.get("/tasks/rules", name="workflow_rules")
async def rules(request: Request):
    return await dashboard(request, "rules")


@router.get("/tasks/matters", name="workflow_matters")
async def matters(request: Request):
    return await dashboard(request, "matter")


@router.get("/workflow/control/state")
async def control_state(request: Request, before: int | None = Query(None, gt=0, le=2**53 - 1)):
    try:
        return await control.snapshot(service(request), before)
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(503, "Autoloop 快照暂不可用") from error


@router.get("/workflow/control/stream")
async def control_stream(request: Request, after: int = Query(0, ge=0, le=2**53 - 1)):
    workflow = service(request)
    last = request.headers.get("last-event-id", "")
    if last:
        if not last.isascii() or not last.isdecimal() or len(last) > 16 or int(last) > 2**53 - 1:
            raise HTTPException(422, "日志序号无效")
        after = int(last)
    if not workflow.autoloop.connected:
        raise HTTPException(503, "Autoloop 暂不可用")

    return StreamingResponse(control.stream_events(workflow, after), media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no",
    })


async def run_details(request, run_id):
    workflow = service(request)
    facts = await call(workflow, f"/v1/runs/{run_id}/why")
    return control.run_details(workflow.store, run_id, facts)

@router.get("/workflow/control/runs/{run_id}")
async def control_run(request: Request, run_id: int):
    return await run_details(request, run_id)


@router.get("/workflow/control/matter")
async def control_matter(
    request: Request,
    run: int | None = Query(None, gt=0, le=2**53 - 1),
    item: str | None = Query(None, min_length=1, max_length=32),
    before: int | None = Query(None, gt=0, le=2**53 - 1),
):
    if (run is None) == (item is None):
        raise HTTPException(422, "请选择一个事项或关联轮次")
    workflow = service(request)
    seed = await run_details(request, run) if run else None
    item_id = item or (seed and seed["item"])
    local = workflow.store.item(item_id) if item_id else None
    if item_id and not local:
        raise HTTPException(404, "工作项不存在")
    try:
        view = await control.snapshot(workflow, before)
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        if not local:
            raise HTTPException(503, "事项历史暂不可用") from error
        view = {}
    result = control.matter_details(workflow.store, view, item=local, seed=seed)
    ids = [entry["id"] for entry in result["runs"] if before is None or entry["id"] < before]
    cursor = ids[7] if len(ids) > 8 else view.get("nextBefore") if not local else None
    limit = asyncio.Semaphore(4)

    async def read_history(run_id):
        if seed and seed["id"] == run_id:
            return seed
        async with limit:
            try:
                return await run_details(request, run_id)
            except HTTPException:
                return None

    histories = await asyncio.gather(*(read_history(run_id) for run_id in ids[:8]))
    cards = {card["id"]: card for card in result["cards"]}
    facts = {}
    for history in histories:
        if history is None:
            continue
        run_id = history["id"]
        for card in history["cards"]:
            if card["run_id"] == run_id:
                cards.setdefault(card["id"], card | {"run": run_id, "item": result["item"]})
        for step in history["timeline"]:
            origin = step.get("originRun") or run_id
            identity = (step["seq"], step["kind"], origin, step.get("card"), step.get("event"), step.get("timer"), step.get("run"))
            facts[identity] = step | {"runId": origin}
    return result | {
        "cards": list(cards.values()),
        "history": sorted(facts.values(), key=lambda step: step["seq"], reverse=True),
        "historyUnavailable": [run_id for run_id, history in zip(ids[:8], histories) if history is None],
        "more": cursor is not None, "nextBefore": cursor,
    }


class CardAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    choice: int | None = Field(None, ge=0)
    text: str | None = Field(None, max_length=4000)


class CardResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: str = Field(min_length=1, max_length=4000)


async def actionable_card(request, card_id, kind):
    workflow = service(request)
    snapshot = await call(workflow, "/v1/state")
    card = next((card for card in snapshot["cards"] if card["id"] == card_id), None)
    if card is None or card["kind"] != kind:
        raise HTTPException(409, "此卡片已处理或不支持该操作")
    if card.get("about") and workflow.store.turn(card["about"]):
        raise HTTPException(409, "此卡片须在工作项中预览并确认")
    return workflow


@router.post("/workflow/cards/{card_id}/answer")
async def answer_card(request: Request, card_id: int, answer: CardAnswer):
    text = (answer.text or "").strip()
    if bool(text) == (answer.choice is not None):
        raise HTTPException(422, "请选择一个选项或填写文字")
    workflow = await actionable_card(request, card_id, "ask")
    body = {"text": text} if text else {"choice": answer.choice}
    result = await call(workflow, f"/v1/cards/{card_id}/answer", method="POST", body=body)
    if not result.get("changed"):
        raise HTTPException(409, "此卡片已处理，请刷新")
    return result


@router.post("/workflow/cards/{card_id}/resolve")
async def resolve_card(request: Request, card_id: int, resolution: CardResolution):
    if not (reason := resolution.reason.strip()):
        raise HTTPException(422, "请填写处理原因")
    workflow = await actionable_card(request, card_id, "notice")
    result = await call(workflow, f"/v1/cards/{card_id}/resolve", method="POST", body={"reason": reason})
    if not result.get("changed"):
        raise HTTPException(409, "此卡片已处理，请刷新")
    return result


LABELS = {
    "approval": "待确认外发", "approved": "等待派发", "running": "执行中", "decision": "待你决定",
    "draft": "待验收", "accepted": "已验收", "failed": "待重试", "cancelled": "已停止",
    "queued": "排队中", "claimed": "已领取", "unknown": "状态待核实", "done": "本轮已结束",
}


async def open_card(workflow, previous):
    if previous and previous["state"] in ("approval", "decision"):
        snapshot = await call(workflow, "/v1/state")
        return next((card for card in snapshot["cards"] if card["about"] == previous["id"]), None)
    return None


async def item_page(request, item_id, *, objective=None, choice=None, answer_text="", preview=None, error="", status=200):
    workflow = service(request)
    item = workflow.store.item(item_id)
    if item is None:
        raise HTTPException(404, "工作项不存在")
    turns = workflow.store.turns(item_id)
    archived = workflow.store.item_archived(item_id)
    previous = turns[0] if turns else None
    candidate = None
    if previous and previous["state"] in ("draft", "accepted", "decision"):
        try:
            candidate = workflow.store.payload(previous["id"])
        except (OSError, ValueError):
            error = error or "本地产物文件缺失，请检查插件备份"
    card = None
    if not archived and previous and previous["state"] in ("approval", "decision"):
        try:
            card = await open_card(workflow, previous)
        except HTTPException:
            error = error or "暂时无法读取决策卡片，请稍后刷新"
    return TEMPLATES.TemplateResponse(request=request, name="workflow_item.html", status_code=status, context={
        "active_page": "tasks", "item": item, "turns": turns, "previous": previous,
        "card": card, "candidate": candidate, "preview": preview, "error": error, "choice": choice,
        "answer_text": answer_text,
        "objective": objective if objective is not None else (previous["objective"] if previous else ""),
        "model_enabled": workflow.gateway.enabled, "state_labels": LABELS, "archived": archived,
        "execution_backend": workflow.execution_backend,
    })


@router.get("/workflow/items/{item_id}", name="workflow_item")
async def item(request: Request, item_id: str):
    return await item_page(request, item_id)


@router.post("/workflow/items/{item_id}/preview", name="workflow_preview")
async def preview(request: Request, item_id: str, objective: str = Form(), choice: int | None = Form(None),
                  answer_text: str = Form("")):
    workflow = service(request)
    turns = workflow.store.turns(item_id)
    previous = turns[0] if turns else None
    try:
        if previous and previous["state"] in ("approved", "running"):
            raise ValueError("请等待当前轮次结束")
        if previous and previous["state"] in ("approval", "decision") and not await open_card(workflow, previous):
            raise ValueError("决策卡片已关闭或尚未就绪")
        data = workflow.preview(item_id, objective, previous, choice, answer_text)
    except KeyError as error:
        raise HTTPException(404, "工作项不存在") from error
    except OSError:
        return await item_page(request, item_id, objective=objective, choice=choice, answer_text=answer_text, error="本地决策文件缺失", status=409)
    except ValueError as error:
        return await item_page(request, item_id, objective=objective, choice=choice, answer_text=answer_text, error=str(error), status=422)
    return await item_page(request, item_id, objective=objective, choice=choice, answer_text=answer_text, preview=data)


@router.post("/workflow/items/{item_id}/approve", name="workflow_approve")
async def approve(
    request: Request, item_id: str, objective: str = Form(), fingerprint: str = Form(),
    previous_id: str = Form(""), choice: int | None = Form(None), answer_text: str = Form(""),
):
    workflow = service(request)
    turns = workflow.store.turns(item_id)
    previous = turns[0] if turns else None
    try:
        if (previous["id"] if previous else "") != previous_id or (
            previous and previous["state"] in ("approved", "running")
        ):
            raise ValueError("预览已过期，请刷新")
        card = await open_card(workflow, previous)
        if previous and previous["state"] in ("approval", "decision") and not card:
            raise ValueError("决策卡片已关闭或尚未就绪")
        workflow.approve(item_id, objective, previous, card["id"] if card else None, choice, fingerprint, answer_text)
    except KeyError as error:
        raise HTTPException(404, "工作项不存在") from error
    except OSError:
        return await item_page(request, item_id, objective=objective, choice=choice, answer_text=answer_text,
                               error="无法保存或读取本地决策材料", status=409)
    except ValueError as error:
        return await item_page(request, item_id, objective=objective, choice=choice, answer_text=answer_text, error=str(error), status=409)
    return RedirectResponse(request.url_for("workflow_item", item_id=item_id), 303)


@router.post("/workflow/items/{item_id}/accept", name="workflow_accept")
def accept(request: Request, item_id: str, turn_id: str = Form()):
    workflow = service(request)
    if not workflow.store.accept(item_id, turn_id):
        raise HTTPException(409, "该轮产物不在待验收状态")
    return RedirectResponse(request.url_for("workflow_item", item_id=item_id), 303)


@router.post("/workflow/rules/{operation}", name="workflow_rule")
async def rule(request: Request, operation: str, name: str = Form()):
    if operation not in ("run", "pause", "resume") or not name or len(name) > 150:
        raise HTTPException(422, "规则或操作无效")
    result = await call(service(request), f"/v1/rules/{quote(name, safe='')}/{operation}", method="POST", body={})
    if request.headers.get("accept") == "application/json":
        return result
    return RedirectResponse(request.url_for("tasks"), 303)


@router.post("/workflow/runs/{run_id}/cancel", name="workflow_cancel")
async def cancel(request: Request, run_id: int):
    workflow = service(request)
    details = await call(workflow, f"/v1/runs/{run_id}/why")
    result = await call(workflow, f"/v1/runs/{run_id}/cancel", method="POST", body={})
    approved_events, cards = control.cancellation_links(run_id, details)
    workflow.store.cancel(run_id, approved_events, cards)
    if request.headers.get("accept") == "application/json":
        return result
    return RedirectResponse(request.url_for("tasks"), 303)


@router.get("/workflow/runs/{run_id}", name="workflow_run")
async def run(request: Request, run_id: int):
    details = await run_details(request, run_id)
    return TEMPLATES.TemplateResponse(request=request, name="workflow_run.html", context={
        "active_page": "tasks", "run_id": run_id, "details": details,
        "fact_labels": control.TIMELINE_LABELS, "terminal": details["state"] in {"done", "nothing", "cancelled"},
        "time": observed_time,
    })


def observed_time(value):
    if value is None:
        return "未上报"
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1000, SHANGHAI)
    else:
        value = datetime.fromisoformat(value).astimezone(SHANGHAI)
    return value.strftime("%Y-%m-%d %H:%M:%S")


@router.get("/tasks/sessions/{run_id}", name="workflow_session")
async def session(request: Request, run_id: int):
    details = await run_details(request, run_id)
    execution = control.execution_details(service(request).store, details)
    duration = None
    if details["started"] is not None and details["finishedAt"]:
        finished = datetime.fromisoformat(details["finishedAt"]).timestamp() * 1000
        if finished >= details["started"]:
            duration = round((finished - details["started"]) / 1000, 1)
    tokens = details["usage"] or {}
    return TEMPLATES.TemplateResponse(request=request, name="workflow_session.html", context={
        "active_page": "tasks", "details": details, "execution": execution, "run_id": run_id,
        "duration": duration, "tokens": tokens, "time": observed_time,
    })

@router.get("/workflow/items/{item_id}/artifacts/{turn_id}", name="workflow_artifact")
def artifact(request: Request, item_id: str, turn_id: str):
    workflow = service(request)
    turn = workflow.store.turn(turn_id)
    if not turn or turn["item_id"] != item_id or turn["state"] not in ("draft", "accepted"):
        raise HTTPException(404, "产物不存在")
    try:
        return PlainTextResponse(workflow.store.payload(turn_id)["draft"])
    except (OSError, KeyError, ValueError) as error:
        raise HTTPException(404, "本地产物文件缺失，请检查插件备份") from error
