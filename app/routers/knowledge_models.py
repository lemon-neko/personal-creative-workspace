"""Model cost center and canonical knowledge routes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.content import ContentItem, render_markdown
from app.knowledge import eligible_items
from app.knowledge_quality import inspect_knowledge_quality
from app.knowledge_store import (
    KnowledgeEdge,
    create_knowledge_card,
    create_knowledge_map,
    layered_graph,
    load_knowledge_store,
    supersede_knowledge_card,
)
from app.model_gateway import POLICIES, ModelGateway, ModelTaskKind
from app.obsidian import obsidian_uri
from app.web import TEMPLATES, collection, not_found
from app.workspace import create_item, current_week_items, save_weekly_review


router = APIRouter()


def _collection(request: Request):
    return collection(request)


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return not_found(request, active_page)


def _return_path_id(return_url: str, prefix: str) -> str | None:
    path = urlparse(return_url).path
    expected = f"{prefix.rstrip('/')}/"
    if not path.startswith(expected):
        return None
    value = path[len(expected) :].split("/", 1)[0]
    return value if value and Path(value).name == value else None

def _refresh_obsidian_links(request: Request) -> None:
    """Best-effort refresh of derived links; authored writes remain authoritative."""

    try:
        request.app.state.obsidian.rebuild_links()
    except (OSError, TypeError, UnicodeError, ValueError):
        return

def _knowledge_context(
    request: Request,
    *,
    saved: str | None = None,
    error: str | None = None,
) -> dict:
    collection = _collection(request)
    items = eligible_items(collection)
    notices = {
        "card": "知识卡已保存，原始来源没有被覆盖。",
        "map": "知识地图已保存。",
        "up-to-date": "当前没有需要重新分析的内容。",
    }
    store = load_knowledge_store(request.app.state.content_root)
    subject_maps = tuple(item for item in store.maps if item.kind == "subject")
    topic_maps = tuple(item for item in store.maps if item.kind == "topic")
    card_source_ids = {
        source_id
        for card in store.cards
        if card.status != "archived"
        for source_id in card.source_ids
    }
    pending_sources = tuple(
        item
        for item in items
        if item.id not in card_source_ids and item.kind != "weekly-review"
    )
    graph = layered_graph(items, store)
    quality_issues = inspect_knowledge_quality(items, store)
    return {
        "active_page": "knowledge",
        "knowledge_items": items,
        "pending_sources": pending_sources,
        "core_graph": graph,
        "knowledge_cards": store.cards,
        "knowledge_maps": store.maps,
        "subject_maps": subject_maps,
        "topic_maps": topic_maps,
        "recent_cards": tuple(
            card for card in store.cards if card.status == "active"
        )[:6],
        "knowledge_store_diagnostics": store.diagnostics,
        "knowledge_quality_issues": quality_issues,
        "notice": notices.get(saved or ""),
        "error": error,
    }

def _redacted_items(
    payload: str, originals: tuple[ContentItem, ...]
) -> tuple[ContentItem, ...]:
    try:
        data = json.loads(payload)
        rows = data["items"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("外发内容必须保留约定的 JSON 结构") from error
    if not isinstance(rows, list):
        raise ValueError("外发内容中的 items 必须是列表")
    original_map = {item.id: item for item in originals}
    redacted: list[ContentItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("外发内容条目格式无效")
        item_id = str(row.get("id", ""))
        if item_id not in original_map or item_id in seen:
            raise ValueError("外发内容包含未知或重复的内容 ID")
        title = str(row.get("title", "")).strip()
        body = str(row.get("body", "")).strip()
        if not title or not body:
            raise ValueError("保留的外发条目必须包含标题和正文")
        redacted.append(
            replace(original_map[item_id], title=title[:120], body=body[:50_000])
        )
        seen.add(item_id)
    if not redacted:
        raise ValueError("请至少保留一条要发送的内容")
    return tuple(redacted)

def _comma_values(value: str) -> list[str]:
    return [
        part.strip() for part in value.replace("，", ",").split(",") if part.strip()
    ]

@router.get("/models", response_class=HTMLResponse, name="models")
async def models(
    request: Request,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    gateway: ModelGateway = request.app.state.model_gateway
    return TEMPLATES.TemplateResponse(
        request=request,
        name="models.html",
        context={
            "active_page": "models",
            "gateway": gateway,
            "policies": tuple(POLICIES.values()),
            "usage_records": gateway.usage.recent(),
            "usage_totals": gateway.usage.totals(),
            "notice": "模型价格已保存在本地账本。" if saved else None,
        },
    )
@router.post("/models/pricing", name="save_model_pricing")
async def save_model_pricing(
    request: Request,
    input_price: float = Form(...),
    output_price: float = Form(...),
) -> HTMLResponse:
    gateway: ModelGateway = request.app.state.model_gateway
    try:
        gateway.save_prices(input_price, output_price)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="models.html",
            context={
                "active_page": "models",
                "gateway": gateway,
                "policies": tuple(POLICIES.values()),
                "usage_records": gateway.usage.recent(),
                "usage_totals": gateway.usage.totals(),
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("models").include_query_params(saved="pricing"),
        status_code=303,
    )

@router.post("/model-tasks", name="create_model_task")
async def create_model_task(
    request: Request,
    task_type: str = Form(...),
    purpose: str = Form(...),
    payload: str = Form(...),
    source_labels: str = Form(default=""),
    return_url: str = Form(default="/models"),
) -> HTMLResponse:
    parsed_return = urlparse(return_url)
    if not return_url.startswith("/") or return_url.startswith("//") or parsed_return.hostname:
        return_url = "/models"
    try:
        task = request.app.state.model_tasks.create(
            task_type=task_type,
            purpose=purpose,
            source_labels=tuple(
                label.strip() for label in source_labels.splitlines() if label.strip()
            ),
            payload=payload,
            return_url=return_url,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="models.html",
            context={
                "active_page": "models",
                "gateway": request.app.state.model_gateway,
                "policies": tuple(POLICIES.values()),
                "usage_records": request.app.state.model_gateway.usage.recent(),
                "usage_totals": request.app.state.model_gateway.usage.totals(),
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id),
        status_code=303,
    )

@router.get(
    "/model-tasks/{task_id}", response_class=HTMLResponse, name="model_task"
)
async def model_task(request: Request, task_id: str) -> HTMLResponse:
    task = request.app.state.model_tasks.get(task_id)
    if task is None:
        return _not_found(request, "models")
    result = json.loads(task.result) if task.result else None
    return TEMPLATES.TemplateResponse(
        request=request,
        name="model_task.html",
        context={
            "active_page": "models",
            "task": task,
            "result": result,
            "local_enabled": request.app.state.model_gateway.enabled,
        },
    )

@router.post(
    "/model-tasks/{task_id}/run-local", name="run_local_model_task"
)
async def run_local_model_task(request: Request, task_id: str) -> HTMLResponse:
    task = request.app.state.model_tasks.get(task_id)
    gateway: ModelGateway = request.app.state.model_gateway
    if task is None:
        return _not_found(request, "models")
    try:
        if task.task_type == ModelTaskKind.KNOWLEDGE.value:
            payload = await asyncio.to_thread(
                gateway.knowledge_card_candidate,
                task.payload,
            )
        elif task.task_type == ModelTaskKind.WEEKLY_REVIEW.value:
            reviewed = _redacted_items(
                task.payload,
                current_week_items(request.app.state.content_root),
            )
            payload = {
                "markdown": await asyncio.to_thread(gateway.summarize, reviewed),
            }
        elif task.task_type == ModelTaskKind.PUBLISH.value:
            source = json.loads(task.payload)
            candidate = await asyncio.to_thread(
                gateway.polish,
                title=str(source["title"]),
                body=str(source["body"]),
                mode=str(source.get("mode", "auto")),
            )
            payload = {
                "title": candidate.title,
                "markdown": candidate.markdown,
                "image_suggestions": list(candidate.image_suggestions),
            }
        elif task.task_type == ModelTaskKind.PROFILE.value:
            payload = await asyncio.to_thread(gateway.profile_candidate, task.payload)
        elif task.task_type == ModelTaskKind.JOB_SKILLS.value:
            skills = await asyncio.to_thread(gateway.job_skill_candidate, task.payload)
            payload = {"skills": list(skills)}
        else:
            raise ValueError("未知模型任务")
        request.app.state.model_tasks.store_result(task.id, payload)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="model_task.html",
            context={
                "active_page": "models",
                "task": task,
                "result": None,
                "local_enabled": gateway.enabled,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post(
    "/model-tasks/{task_id}/import", name="import_model_task"
)
async def import_model_task(
    request: Request,
    task_id: str,
    result: str = Form(...),
) -> HTMLResponse:
    try:
        task, _ = request.app.state.model_tasks.import_result(task_id, result)
    except KeyError:
        return _not_found(request, "models")
    except ValueError as error:
        task = request.app.state.model_tasks.get(task_id)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="model_task.html",
            context={
                "active_page": "models",
                "task": task,
                "result": None,
                "local_enabled": request.app.state.model_gateway.enabled,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post(
    "/model-tasks/{task_id}/confirm", name="confirm_model_task"
)
async def confirm_model_task(request: Request, task_id: str) -> HTMLResponse:
    task = request.app.state.model_tasks.get(task_id)
    if task is None:
        return _not_found(request, "models")
    if task.status != "imported" or not task.result:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="model_task.html",
            context={
                "active_page": "models",
                "task": task,
                "result": json.loads(task.result) if task.result else None,
                "local_enabled": request.app.state.model_gateway.enabled,
                "error": "候选结果尚未导入或已经确认。",
            },
            status_code=422,
        )
    result = json.loads(task.result)
    form = await request.form()
    redirect_url = task.return_url
    try:
        if task.task_type == ModelTaskKind.KNOWLEDGE.value:
            selected = tuple(dict.fromkeys(str(value) for value in form.getlist("selected")))
            if not selected:
                raise ValueError("请至少选择一张知识卡候选")
            suggestions = result["suggestions"]
            for key in selected:
                parts = key.split("-")
                if len(parts) != 2 or not all(value.isdigit() for value in parts):
                    raise ValueError("知识卡候选编号无效")
                source_index, card_index = (int(value) for value in parts)
                suggestion = suggestions[source_index]
                original = suggestion["cards"][card_index]
                relations = tuple(
                    KnowledgeEdge(
                        str(value["target_id"]),
                        str(value["type"]),
                        str(value.get("note", ""))[:160],
                    )
                    for value in original.get("relations", [])
                )
                create_knowledge_card(
                    request.app.state.content_root,
                    title=str(form.get(f"title_{key}", "")),
                    body=str(form.get(f"body_{key}", "")),
                    card_type=str(form.get(f"type_{key}", "")),
                    subjects=tuple(
                        _comma_values(str(form.get(f"subjects_{key}", "")))
                    ),
                    concepts=tuple(
                        _comma_values(str(form.get(f"concepts_{key}", "")))
                    ),
                    map_ids=tuple(
                        _comma_values(str(form.get(f"maps_{key}", "")))
                    ),
                    source_ids=(str(suggestion["item_id"]),),
                    relations=relations,
                )
            redirect_url = str(request.url_for("knowledge"))
        elif task.task_type == ModelTaskKind.WEEKLY_REVIEW.value:
            markdown = str(form.get("markdown", "")).strip()
            if not markdown:
                raise ValueError("周回顾候选不能为空")
            save_weekly_review(
                request.app.state.content_root,
                summarizer=lambda _items: markdown,
            )
            redirect_url = str(request.url_for("reviews"))
        elif task.task_type == ModelTaskKind.PUBLISH.value:
            source_id = _return_path_id(task.return_url, "/publish")
            source = _collection(request).get(source_id or "")
            if source is None:
                raise ValueError("公众号候选来源已经不存在")
            create_item(
                request.app.state.content_root,
                title=str(form.get("title", "")),
                body=str(form.get("markdown", "")),
                tags=source.tags,
                category=source.category or "",
                kind="article",
                parent_id=source.id,
            )
            redirect_url = str(
                request.url_for("workspace").include_query_params(
                    view="articles", saved="article"
                )
            )
        elif task.task_type == ModelTaskKind.PROFILE.value:
            request.app.state.career.save_profile(
                **{
                    key: str(form.get(key, ""))
                    for key in (
                        "target_roles",
                        "contact",
                        "education",
                        "experience",
                        "certifications",
                        "skills",
                        "facts",
                    )
                }
            )
            redirect_url = str(request.url_for("career_profile"))
        elif task.task_type == ModelTaskKind.JOB_SKILLS.value:
            job_id = _return_path_id(task.return_url, "/career/jobs")
            if request.app.state.career.job(job_id or "") is None:
                raise ValueError("职位已经不存在")
            selected = tuple(dict.fromkeys(str(value) for value in form.getlist("selected")))
            if not selected:
                raise ValueError("请至少选择一条技能候选")
            for raw_index in selected:
                if not raw_index.isdigit():
                    raise ValueError("技能候选编号无效")
                index = int(raw_index)
                row = result["skills"][index]
                name = str(form.get(f"name_{index}", "")).strip()
                importance = int(str(form.get(f"importance_{index}", "3")))
                skill = request.app.state.career.find_or_add_skill(
                    name=name,
                    category=str(form.get(f"category_{index}", "")),
                )
                request.app.state.career.set_job_skill_gap(
                    job_id=job_id,
                    skill_id=skill.id,
                    importance=importance,
                    gap_note=str(
                        form.get(f"requirement_{index}", row.get("requirement", ""))
                    ),
                )
            redirect_url = str(
                request.url_for("career_job_detail", job_id=job_id)
            )
        else:
            raise ValueError("未知模型任务")
        request.app.state.model_tasks.mark_confirmed(task.id)
    except (IndexError, KeyError, TypeError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="model_task.html",
            context={
                "active_page": "models",
                "task": task,
                "result": result,
                "local_enabled": request.app.state.model_gateway.enabled,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(redirect_url, status_code=303)

@router.get(
    "/knowledge/cards/{card_id}", response_class=HTMLResponse, name="knowledge_card"
)
async def knowledge_card(request: Request, card_id: str) -> HTMLResponse:
    store = load_knowledge_store(request.app.state.content_root)
    card = store.card(card_id)
    if card is None:
        return _not_found(request, "knowledge")
    source_map = {item.id: item for item in _collection(request).items}
    map_lookup = {item.id: item for item in store.maps}
    return TEMPLATES.TemplateResponse(
        request=request,
        name="knowledge_card.html",
        context={
            "active_page": "knowledge",
            "card": card,
            "card_html": render_markdown(
                card.body,
                source=card.source,
                content_root=request.app.state.content_root,
            ),
            "obsidian_url": obsidian_uri(card.source),
            "sources": tuple(source_map[value] for value in card.source_ids if value in source_map),
            "maps": tuple(map_lookup[value] for value in card.map_ids if value in map_lookup),
            "replacement": store.card(card.superseded_by or ""),
            "replacement_candidates": tuple(
                value
                for value in store.cards
                if value.id != card.id and value.status == "active"
            ),
        },
    )

@router.post(
    "/knowledge/cards/{card_id}/supersede",
    name="supersede_knowledge_card",
)
async def supersede_knowledge_card_route(
    request: Request,
    card_id: str,
    replacement_id: str = Form(...),
) -> HTMLResponse:
    try:
        supersede_knowledge_card(
            request.app.state.content_root,
            card_id,
            replacement_id,
        )
        _refresh_obsidian_links(request)
    except ValueError:
        return _not_found(request, "knowledge")
    return RedirectResponse(
        request.url_for("knowledge_card", card_id=card_id), status_code=303
    )

@router.get(
    "/knowledge/maps/{map_id}", response_class=HTMLResponse, name="knowledge_map"
)
async def knowledge_map(request: Request, map_id: str) -> HTMLResponse:
    store = load_knowledge_store(request.app.state.content_root)
    item = store.map(map_id)
    if item is None:
        return _not_found(request, "knowledge")
    lookup = {value.id: value for value in store.maps}
    return TEMPLATES.TemplateResponse(
        request=request,
        name="knowledge_map.html",
        context={
            "active_page": "knowledge",
            "knowledge_map": item,
            "map_html": render_markdown(
                item.body,
                source=item.source,
                content_root=request.app.state.content_root,
            ),
            "obsidian_url": obsidian_uri(item.source),
            "parents": tuple(lookup[value] for value in item.parent_ids if value in lookup),
            "children": tuple(value for value in store.maps if item.id in value.parent_ids),
            "cards": tuple(card for card in store.cards if item.id in card.map_ids),
        },
    )

@router.post("/knowledge/maps", name="create_knowledge_map")
async def create_knowledge_map_route(
    request: Request,
    title: str = Form(...),
    kind: str = Form(...),
    summary: str = Form(...),
    parent_ids: list[str] = Form(default=[]),
    body: str = Form(default=""),
) -> HTMLResponse:
    try:
        item = create_knowledge_map(
            request.app.state.content_root,
            title=title,
            kind=kind,
            summary=summary,
            parent_ids=tuple(parent_ids),
            body=body,
        )
        _refresh_obsidian_links(request)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge.html",
            context=_knowledge_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("knowledge_map", map_id=item.id), status_code=303
    )

@router.post("/knowledge/cards", name="create_knowledge_card")
async def create_knowledge_card_route(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    card_type: str = Form(...),
    subjects: str = Form(...),
    source_ids: list[str] = Form(default=[]),
    map_ids: list[str] = Form(default=[]),
    concepts: str = Form(default=""),
) -> HTMLResponse:
    known_sources = {item.id for item in eligible_items(_collection(request))}
    if not source_ids or not set(source_ids) <= known_sources:
        return _not_found(request, "knowledge")
    try:
        card = create_knowledge_card(
            request.app.state.content_root,
            title=title,
            body=body,
            card_type=card_type,
            subjects=tuple(_comma_values(subjects)),
            source_ids=tuple(source_ids),
            map_ids=tuple(map_ids),
            concepts=tuple(_comma_values(concepts)),
        )
        _refresh_obsidian_links(request)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge.html",
            context=_knowledge_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("knowledge_card", card_id=card.id), status_code=303
    )
