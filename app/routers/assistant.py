"""Source-backed private decision assistant routes."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.assistant import (
    AssistantContextBuilder,
    AssistantRecommendation,
    AssistantRepository,
    enrich_assistant_recommendation,
    validate_assistant_result,
)
from app.model_gateway import POLICIES, ModelGateway, ModelTaskKind, estimate_tokens
from app.web import TEMPLATES, not_found
from app.workspace import create_item


router = APIRouter()


def _repository(request: Request) -> AssistantRepository:
    return request.app.state.assistant


def _builder(request: Request) -> AssistantContextBuilder:
    return AssistantContextBuilder(
        request.app.state.content_root,
        request.app.state.career,
        request.app.state.search,
        request.app.state.video,
        request.app.state.income,
    )


def _conversation_context(
    request: Request,
    *,
    conversation_id: str = "",
    recommendation: AssistantRecommendation | None = None,
    notice: str = "",
    error: str = "",
) -> dict:
    repository = _repository(request)
    conversations = repository.conversations(include_archived=True)
    selected = repository.conversation(conversation_id) if conversation_id else None
    if selected is None:
        selected = next(
            (value for value in conversations if value.status == "active"), None
        )
    turns = repository.turns(selected.id) if selected else ()
    return {
        "active_page": "assistant",
        "conversations": conversations,
        "conversation": selected,
        "turns": turns,
        "decisions": {
            turn.id: {value.action_id: value for value in repository.decisions(turn.id)}
            for turn in turns
        },
        "skills": request.app.state.career.skills(),
        "recommendation": recommendation,
        "gateway": request.app.state.model_gateway,
        "notice": notice,
        "error": error,
    }


def _preview_context(
    request: Request,
    *,
    material: str,
    sources,
    conversation_id: str,
    error: str = "",
) -> dict:
    gateway: ModelGateway = request.app.state.model_gateway
    return {
        "active_page": "assistant",
        "material": material,
        "sources": sources,
        "conversation_id": conversation_id,
        "estimated_tokens": estimate_tokens(material),
        "policy": POLICIES[ModelTaskKind.ASSISTANT],
        "gateway": gateway,
        "target": gateway.config.base_url or "未配置直接模型",
        "error": error,
    }


def _conversation_from_return_url(return_url: str) -> str:
    parsed = urlparse(return_url)
    if parsed.path != "/assistant":
        return ""
    values = parse_qs(parsed.query).get("conversation_id", [])
    return values[0] if values else ""


def _validated_recommendation(
    request: Request,
    payload: object,
    material: str,
) -> AssistantRecommendation:
    builder = _builder(request)
    source_ids, skill_ids = builder.validate_outbound(material)
    recommendation = validate_assistant_result(
        payload,
        allowed_source_ids=source_ids,
        allowed_skill_ids=skill_ids,
    )
    question = str(json.loads(material).get("question", ""))
    canonical = builder.build(question)
    return enrich_assistant_recommendation(recommendation, canonical.sources)


@router.get("/assistant", response_class=HTMLResponse, name="assistant")
async def assistant_page(
    request: Request,
    conversation_id: str = Query(default=""),
    saved: str = Query(default=""),
) -> HTMLResponse:
    notices = {
        "action": "已执行你确认的操作。",
        "discarded": "候选操作已放弃，没有修改工作台。",
        "archived": "会话摘要已归档。",
        "deleted": "会话摘要与决策记录已删除。",
        "manual": "人工桥接结果已校验并保存为会话摘要。",
    }
    return TEMPLATES.TemplateResponse(
        request=request,
        name="assistant.html",
        context=_conversation_context(
            request,
            conversation_id=conversation_id,
            notice=notices.get(saved, ""),
        ),
    )


@router.post("/assistant/preview", response_class=HTMLResponse, name="assistant_preview")
async def assistant_preview(
    request: Request,
    question: str = Form(...),
    conversation_id: str = Form(default=""),
) -> HTMLResponse:
    conversation = (
        _repository(request).conversation(conversation_id) if conversation_id else None
    )
    if conversation_id and (conversation is None or conversation.status != "active"):
        return not_found(request, "assistant")
    try:
        snapshot = _builder(request).build(
            question,
            conversation_summary=conversation.summary if conversation else "",
        )
        if estimate_tokens(snapshot.material) > POLICIES[
            ModelTaskKind.ASSISTANT
        ].max_input_tokens:
            raise ValueError("助手上下文超过 12K Token，请在预览中缩小范围")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant.html",
            context=_conversation_context(
                request,
                conversation_id=conversation_id,
                error=str(error),
            ),
            status_code=422,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="assistant_preview.html",
        context=_preview_context(
            request,
            material=snapshot.material,
            sources=snapshot.sources,
            conversation_id=conversation_id,
        ),
    )


@router.post("/assistant/ask", response_class=HTMLResponse, name="assistant_ask")
async def assistant_ask(
    request: Request,
    outbound_text: str = Form(...),
    conversation_id: str = Form(default=""),
) -> HTMLResponse:
    gateway: ModelGateway = request.app.state.model_gateway
    conversation = (
        _repository(request).conversation(conversation_id) if conversation_id else None
    )
    if conversation_id and (conversation is None or conversation.status != "active"):
        return not_found(request, "assistant")
    try:
        source_ids, _skill_ids = _builder(request).validate_outbound(outbound_text)
        if estimate_tokens(outbound_text) > POLICIES[
            ModelTaskKind.ASSISTANT
        ].max_input_tokens:
            raise ValueError("外发内容超过助手 12K Token 上限")
        if not gateway.enabled:
            raise RuntimeError("尚未配置可直接调用的本地或外部模型")
        payload = await asyncio.to_thread(gateway.assistant_candidate, outbound_text)
        recommendation = _validated_recommendation(request, payload, outbound_text)
        saved_conversation, _turn = _repository(request).save_turn(
            recommendation,
            conversation_id=conversation_id,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        try:
            parsed = json.loads(outbound_text)
            sources = tuple(
                row
                for row in parsed.get("allowed_sources", [])
                if isinstance(row, dict) and row.get("id") in locals().get("source_ids", set())
            )
        except (AttributeError, json.JSONDecodeError):
            sources = ()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant_preview.html",
            context=_preview_context(
                request,
                material=outbound_text,
                sources=sources,
                conversation_id=conversation_id,
                error=str(error),
            ),
            status_code=422,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="assistant.html",
        context=_conversation_context(
            request,
            conversation_id=saved_conversation.id,
            recommendation=recommendation,
        ),
    )


@router.post("/assistant/manual", name="assistant_manual")
async def assistant_manual(
    request: Request,
    outbound_text: str = Form(...),
    conversation_id: str = Form(default=""),
) -> HTMLResponse:
    conversation = (
        _repository(request).conversation(conversation_id) if conversation_id else None
    )
    if conversation_id and (conversation is None or conversation.status != "active"):
        return not_found(request, "assistant")
    try:
        source_ids, _skill_ids = _builder(request).validate_outbound(outbound_text)
        parsed = json.loads(outbound_text)
        source_labels = tuple(
            str(row.get("title", "")).strip()
            for row in parsed.get("allowed_sources", [])
            if isinstance(row, dict) and row.get("id") in source_ids
        )
        return_url = "/assistant"
        if conversation_id:
            return_url = f"/assistant?conversation_id={conversation_id}"
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.ASSISTANT.value,
            purpose="基于工作台现状给出一个有来源的优先建议",
            source_labels=source_labels,
            payload=outbound_text,
            return_url=return_url,
        )
    except (ValueError, json.JSONDecodeError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant_preview.html",
            context=_preview_context(
                request,
                material=outbound_text,
                sources=(),
                conversation_id=conversation_id,
                error=str(error),
            ),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("assistant_manual_task", task_id=task.id), status_code=303
    )


@router.get(
    "/assistant/manual/{task_id}",
    response_class=HTMLResponse,
    name="assistant_manual_task",
)
async def assistant_manual_task(request: Request, task_id: str) -> HTMLResponse:
    task = request.app.state.model_tasks.get(task_id)
    if task is None or task.task_type != ModelTaskKind.ASSISTANT.value:
        return not_found(request, "assistant")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="assistant_manual.html",
        context={"active_page": "assistant", "task": task},
    )


@router.post(
    "/assistant/manual/{task_id}/import",
    name="assistant_manual_import",
)
async def assistant_manual_import(
    request: Request,
    task_id: str,
    result: str = Form(...),
) -> HTMLResponse:
    task = request.app.state.model_tasks.get(task_id)
    if task is None or task.task_type != ModelTaskKind.ASSISTANT.value:
        return not_found(request, "assistant")
    try:
        imported, payload = request.app.state.model_tasks.import_result(task_id, result)
        recommendation = _validated_recommendation(request, payload, task.payload)
        conversation_id = _conversation_from_return_url(task.return_url)
        conversation, _turn = _repository(request).save_turn(
            recommendation,
            conversation_id=conversation_id,
        )
        request.app.state.model_tasks.mark_confirmed(imported.id)
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant_manual.html",
            context={"active_page": "assistant", "task": task, "error": str(error)},
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("assistant").include_query_params(
            conversation_id=conversation.id, saved="manual"
        ),
        status_code=303,
    )


@router.post(
    "/assistant/turns/{turn_id}/actions/{action_id}",
    name="assistant_action",
)
async def assistant_action(
    request: Request,
    turn_id: str,
    action_id: str,
    decision: str = Form(...),
    title: str = Form(default=""),
    body: str = Form(default=""),
    skill_id: str = Form(default=""),
    priority: int = Form(default=3),
) -> HTMLResponse:
    repository = _repository(request)
    turn = repository.turn(turn_id)
    if turn is None:
        return not_found(request, "assistant")
    suggestion = next((value for value in turn.suggestions if value.id == action_id), None)
    if suggestion is None:
        return not_found(request, "assistant")
    redirect = request.url_for("assistant").include_query_params(
        conversation_id=turn.conversation_id
    )
    existing = repository.decision(turn_id, action_id)
    if existing is not None:
        saved = "discarded" if existing.status == "discarded" else "action"
        return RedirectResponse(redirect.include_query_params(saved=saved), status_code=303)
    if decision == "discard":
        repository.reserve_decision(turn_id, suggestion, discarded=True)
        return RedirectResponse(
            redirect.include_query_params(saved="discarded"), status_code=303
        )
    if decision != "confirm":
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant.html",
            context=_conversation_context(
                request,
                conversation_id=turn.conversation_id,
                error="候选操作决策无效",
            ),
            status_code=422,
        )
    clean_title = title.strip()[:200]
    clean_body = body.strip()[:10_000]
    if not clean_title or not clean_body or priority not in range(1, 6):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant.html",
            context=_conversation_context(
                request,
                conversation_id=turn.conversation_id,
                error="候选标题、正文或优先级无效",
            ),
            status_code=422,
        )
    if suggestion.action_type == "create-learning-task" and skill_id not in {
        value.id for value in request.app.state.career.skills()
    }:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant.html",
            context=_conversation_context(
                request,
                conversation_id=turn.conversation_id,
                error="请选择现有技能后再创建学习任务",
            ),
            status_code=422,
        )
    repository.reserve_decision(turn_id, suggestion)
    try:
        if suggestion.action_type == "create-thought":
            target = create_item(
                request.app.state.content_root,
                title=clean_title,
                body=clean_body,
                kind="thought",
            )
        else:
            target = request.app.state.career.add_learning_task(
                skill_id=skill_id,
                title=clean_title,
                status="backlog",
                priority=priority,
                notes=clean_body,
            )
        repository.finish_decision(
            turn_id, action_id, status="confirmed", target_id=target.id
        )
    except (OSError, RuntimeError, ValueError) as error:
        repository.finish_decision(turn_id, action_id, status="failed")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant.html",
            context=_conversation_context(
                request,
                conversation_id=turn.conversation_id,
                error=f"操作没有完成：{error}",
            ),
            status_code=422,
        )
    return RedirectResponse(redirect.include_query_params(saved="action"), status_code=303)


@router.post(
    "/assistant/conversations/{conversation_id}/archive",
    name="assistant_archive",
)
async def assistant_archive(request: Request, conversation_id: str) -> HTMLResponse:
    try:
        _repository(request).set_status(conversation_id, "archived")
    except KeyError:
        return not_found(request, "assistant")
    return RedirectResponse(
        request.url_for("assistant").include_query_params(saved="archived"),
        status_code=303,
    )


@router.post(
    "/assistant/conversations/{conversation_id}/delete",
    name="assistant_delete",
)
async def assistant_delete(
    request: Request,
    conversation_id: str,
    confirmation: str = Form(...),
) -> HTMLResponse:
    if confirmation.strip() != "删除会话":
        return TEMPLATES.TemplateResponse(
            request=request,
            name="assistant.html",
            context=_conversation_context(
                request,
                conversation_id=conversation_id,
                error="请输入“删除会话”确认删除摘要与决策记录",
            ),
            status_code=422,
        )
    try:
        _repository(request).delete(conversation_id)
    except KeyError:
        return not_found(request, "assistant")
    return RedirectResponse(
        request.url_for("assistant").include_query_params(saved="deleted"),
        status_code=303,
    )
