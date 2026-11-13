"""Workspace, ideas, knowledge landing and review routes."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.agent_core import DEFAULT_PROJECT_ID
from app.atomic import content_lock
from app.focus import FOCUS_STATUSES, daily_board, focus_snapshot, planner_slot
from app.content import ContentCollection, ContentItem, render_markdown, semantic_revision
from app.knowledge import (
    DEFAULT_SUBJECTS,
    distillable_items,
    eligible_items,
    format_relation_lines,
)
from app.knowledge_quality import inspect_knowledge_quality
from app.knowledge_store import (
    create_knowledge_card,
    layered_graph,
    load_knowledge_store,
    subjects_for_topic_maps,
    supersede_knowledge_card,
)
from app.model_gateway import POLICIES, ModelTaskKind
from app.obsidian import obsidian_uri
from app.planner import planner_context
from app.web import TEMPLATES, WORKSPACE_VIEWS, collection, not_found
from app.workspace import (
    SHANGHAI,
    WEEKDAYS,
    ContentConflictError,
    create_item,
    current_week_items,
    load_workspace_settings,
    move_to_trash,
    next_summary_run,
    save_weekly_review,
    save_workspace_settings,
    set_item_status,
    update_item,
)


router = APIRouter()


def _collection(request: Request):
    return collection(request)


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return not_found(request, active_page)


def _item_context(item: ContentItem, content_root: Path | None = None) -> dict:
    context = {
        "item": item,
        "item_html": render_markdown(
            item.body,
            source=item.source,
            content_root=content_root,
        ),
        "tags_value": "，".join(item.tags),
        "subjects_value": "，".join(item.subjects),
        "concepts_value": "，".join(item.concepts),
        "relations_value": format_relation_lines(item.relations),
        "source_revision": semantic_revision(item),
        "obsidian_url": obsidian_uri(item.source),
    }
    if content_root is not None:
        store = load_knowledge_store(content_root)
        context["derived_cards"] = tuple(
            card for card in store.cards if item.id in card.source_ids
        )
        context["has_legacy_knowledge"] = bool(
            item.subjects or item.concepts or item.relations
        )
    return context


def _review_context(
    request: Request,
    item: ContentItem,
    *,
    error: str | None = None,
) -> dict:
    context = _item_context(item, request.app.state.content_root)
    context.update({"active_page": "reviews", "error": error})
    return context


def _distill_context(
    request: Request,
    item: ContentItem,
    *,
    error: str | None = None,
) -> dict:
    store = load_knowledge_store(request.app.state.content_root)
    cards = tuple(card for card in store.cards if item.id in card.source_ids)
    revision = semantic_revision(item)
    card_rows = tuple(
        {
            "card": card,
            "source_state": (
                "unconfirmed"
                if item.id not in card.source_revisions
                else "current"
                if card.source_revisions[item.id] == revision
                else "changed"
            ),
        }
        for card in cards
    )
    return {
        "active_page": "ideas",
        "item": item,
        "source_revision": revision,
        "card_rows": card_rows,
        "topic_maps": tuple(value for value in store.maps if value.kind == "topic"),
        "active_cards": tuple(card for card in store.cards if card.status == "active"),
        "error": error,
    }


def _refresh_obsidian_links(request: Request) -> None:
    """Best-effort refresh of derived links; authored writes remain authoritative."""

    try:
        request.app.state.obsidian.rebuild_links()
    except (OSError, TypeError, UnicodeError, ValueError):
        return


def _refresh_search_item(request: Request, item: ContentItem) -> None:
    try:
        request.app.state.search.upsert_content_item(item)
    except (AttributeError, OSError, RuntimeError, sqlite3.Error):
        return


def _knowledge_context(
    request: Request,
    *,
    saved: str | None = None,
    error: str | None = None,
) -> dict:
    collection = _collection(request)
    items = eligible_items(collection)
    thought_sources = distillable_items(collection)
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
        item for item in thought_sources if item.id not in card_source_ids
    )
    graph = layered_graph(items, store)
    quality_issues = inspect_knowledge_quality(items, store)
    return {
        "active_page": "knowledge",
        "knowledge_items": thought_sources,
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

def _workspace_context(
    request: Request,
    *,
    saved: str | None = None,
    error: str | None = None,
    form_data: dict | None = None,
    query: str | None = None,
    view: str | None = None,
) -> dict:
    today = datetime.now(SHANGHAI).date()
    show_workspace_feed = "view" in request.query_params or "q" in request.query_params
    notices = {
        "created": "想法已落进本地 Markdown。先记下来，整理可以晚一点。",
        "article": "候选稿已保存为新的文章草稿，原始想法没有被改动。",
        "status": "内容状态已更新。",
        "review": "本周回顾草稿已生成。",
        "existing": "本周回顾已经存在，没有重复生成。",
        "fallback": "模型未使用，已生成稳定的规则回顾草稿。",
    }
    context = {
        "active_page": "workspace",
        **focus_snapshot(request.app.state.focus, today),
        "attention_runs": request.app.state.agent_core.attention_runs(),
        "focus_status_labels": FOCUS_STATUSES,
        "show_workspace_feed": show_workspace_feed,
        "notice": notices.get(saved or ""),
        "error": error,
        "form_data": form_data or {},
        "board_view": "upcoming" if request.query_params.get("board") == "upcoming" else "today",
        "board_show_done": request.query_params.get("done") == "1",
        "board_date_label": f"{today.month}月{today.day}日 · 周{'一二三四五六日'[today.weekday()]}",
    }
    context.update(daily_board(request.app.state.focus, context, today))
    context["planner_view"] = not show_workspace_feed and "board" not in request.query_params
    if context["planner_view"]:
        context.update(planner_context(request.app.state.focus, context, today, request.query_params.get("day", "")))
    runtime = request.app.state.agent_core
    task_ids = runtime.daily_task_ids()
    displayed = context["board_upcoming"] if context["board_view"] == "upcoming" else context["board_events"]
    goal_ids = {goal.id for goal in context["focus_goals"]} if context["planner_view"] else {goal.id for _, goal, _ in displayed if goal}
    for goal_id in goal_ids:
        task_ids.update(runtime.linked_tasks(goal_id))
    context["board_task_ids"] = task_ids
    if show_workspace_feed:
        collection = _collection(request)
        context["diagnostics"] = collection.diagnostics
        context.update(_workspace_feed_context(collection, query=query, view=view))
    return context

def _workspace_feed_context(
    collection: ContentCollection,
    *,
    query: str | None,
    view: str | None,
    feed_notice: str | None = None,
) -> dict:
    selected_view = view if view in WORKSPACE_VIEWS else "pending"
    cleaned_query = (query or "").strip()
    searched = collection.filter(query=cleaned_query, kind="thought")

    def in_view(item: ContentItem, target: str) -> bool:
        if target == "pending":
            return item.kind == "thought" and item.status == "draft"
        if target == "organized":
            return item.kind == "thought" and item.status == "published"
        return item.kind == "thought"

    counts = {
        target: sum(in_view(item, target) for item in collection.items)
        for target in WORKSPACE_VIEWS
    }
    return {
        "workspace_items": tuple(
            item for item in searched if in_view(item, selected_view)
        ),
        "workspace_query": cleaned_query,
        "workspace_view": selected_view,
        "workspace_view_counts": counts,
        "feed_notice": feed_notice,
    }

def _idea_filters(
    collection: ContentCollection,
    *,
    query: str | None,
    status: str | None,
    tag: str | None,
    category: str | None,
    date_from: str | None,
    date_to: str | None,
) -> dict:
    return {
        "items": collection.filter(
            query=query,
            status=status,
            kind="thought",
            tag=tag,
            category=category,
            date_from=date_from,
            date_to=date_to,
        ),
        "tags": sorted(
            {
                tag
                for item in collection.items
                if item.kind == "thought"
                for tag in item.tags
            }
        ),
        "categories": sorted(
            {
                item.category
                for item in collection.items
                if item.kind == "thought" and item.category
            },
        ),
        "selected": {
            "q": query or "",
            "status": status or "",
            "tag": tag or "",
            "category": category or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    }

def _llm_target(request: Request) -> str:
    config = getattr(request.app.state.llm_client, "config", None)
    return getattr(config, "base_url", "") if config else "已配置的模型接口"

def _disclosure_context(
    request: Request,
    *,
    purpose: str,
    source_labels: tuple[str, ...],
    submit_url,
    outbound_text: str,
    back_url,
    task_type: str = "",
    hidden_fields: dict[str, str] | None = None,
    error: str | None = None,
) -> dict:
    return {
        "active_page": "settings",
        "purpose": purpose,
        "source_labels": source_labels,
        "target": _llm_target(request),
        "submit_url": submit_url,
        "outbound_text": outbound_text,
        "back_url": back_url,
        "task_type": task_type,
        "hidden_fields": hidden_fields or {},
        "error": error,
    }

def _items_payload(items: tuple[ContentItem, ...]) -> str:
    return json.dumps(
        {
            "items": [
                {
                    "id": item.id,
                    "created_at": item.created_at.isoformat(),
                    "title": item.title,
                    "body": item.body,
                }
                for item in items
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
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

@router.get("/legacy/planner", response_class=HTMLResponse, name="legacy_workspace")
async def workspace(
    request: Request,
    saved: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    view: Optional[str] = Query(default="pending"),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="workspace.html",
        context=_workspace_context(request, saved=saved, query=q, view=view),
    )


@router.post("/today/events", name="create_daily_event")
async def create_daily_event(
    request: Request, title: str = Form(), deliverable_id: str = Form(""), due_on: str = Form(""),
    start_on: str = Form(""), start_time: str = Form(""),
):
    today = datetime.now(SHANGHAI).date()
    try:
        slot = planner_slot(start_on, start_time) if start_on else None
        request.app.state.focus.create_daily_event(title, today, deliverable_id, due_on, slot=slot)
    except ValueError as error:
        return _board_response(
            request, status=422, board_error=str(error), event_title=title,
            event_delivery=deliverable_id, event_date=due_on, event_start_time=start_time,
        )
    message = "已添加到待安排" if not slot and due_on and due_on > today.isoformat() else "已添加待办"
    return _board_response(request, board_message=message)


@router.post("/today/events/{event_id}/status", name="update_daily_event")
async def update_daily_event(
    request: Request, event_id: str, status: str = Form(), expected_status: str = Form(""),
    title: str | None = Form(None), due_on: str | None = Form(None), edit: bool = Form(False),
):
    try:
        previous = request.app.state.focus.update_board_event(
            event_id, status, datetime.now(SHANGHAI).date(), expected_status=expected_status,
            title=(title or "") if edit else None, due_on=(due_on or "") if edit else None,
        )
    except KeyError:
        return not_found(request, "workspace")
    except ValueError as error:
        return _board_response(
            request, status=422, board_error=str(error), board_error_id=event_id,
            board_edit={"title": title or "", "due_on": due_on or "", "status": status} if edit else None,
            board_show_done=expected_status == "done",
        )
    completed = status == "done" and previous != status
    return _board_response(
        request, board_message="已完成待办" if completed else "已恢复待办" if previous == "done" and status != previous else "已更新待办",
        board_undo=(event_id, previous) if completed else None, board_event_id=event_id,
        board_show_done=status == "done" and not completed,
        anchor=f"event-{event_id}" if request.query_params.get("board") != "upcoming" and not (edit and due_on) else "today",
        done=status == "done",
    )


@router.post("/today/events/{event_id}/today", name="schedule_daily_event")
async def schedule_daily_event(request: Request, event_id: str):
    repository = request.app.state.focus
    today = datetime.now(SHANGHAI).date()
    projection = daily_board(repository, focus_snapshot(repository, today), today)
    item = next((row for row in projection["board_upcoming"] if row[0].id == event_id), None)
    if item is None:
        return _board_response(request, status=422, board_error="这项待办已不在待安排列表，请检查当前状态")
    event, goal, _ = item
    try:
        if event.status == "paused":
            raise ValueError("请先恢复这项待办")
        if goal:
            repository.set_day_focus(event_id, selected=True, on=today)
        else:
            repository.update_board_event(
                event_id, event.status, today, due_on=today.isoformat(), expected_status=event.status,
            )
    except ValueError as error:
        return _board_response(request, status=422, board_error=str(error), board_error_id=event_id)
    return _board_response(request, board_message="已安排到今天")


@router.post("/today/events/{event_id}/slot", name="set_daily_event_slot")
async def set_daily_event_slot(
    request: Request, event_id: str, expected_slot: str = Form(""),
    start_on: str = Form(""), start_time: str = Form(""), clear: bool = Form(False),
):
    try:
        slot = None if clear else planner_slot(start_on, start_time)
        request.app.state.focus.set_planner_slot(event_id, datetime.now(SHANGHAI).date(), slot, expected_slot)
    except ValueError as error:
        return _board_response(request, status=422, board_error=str(error))
    return _board_response(request, board_message="已取消安排" if clear else "已安排待办")


def _board_response(request: Request, *, status: int = 200, anchor: str = "today", done: bool = False, **feedback):
    fragment = request.headers.get("X-Workspace-Board") == "1"
    if not fragment and status == 200:
        params = {key: request.query_params[key] for key in ("board", "day") if key in request.query_params}
        if done:
            params["done"] = "1"
        query = f"?{urlencode(params)}" if params else ""
        return RedirectResponse(f"{request.url_for('legacy_workspace') if request.app.state.plugins_enabled else request.url_for('workspace')}{query}#{anchor}", status_code=303)
    context = _workspace_context(request)
    context.update(feedback)
    if context.get("board_error_id") and not context["planner_view"]:
        rows = context["board_upcoming"] if context["board_view"] == "upcoming" else context["board_events"]
        if not any(event.id == context["board_error_id"] for event, _, _ in rows):
            context["board_error_id"] = ""
    partial = "partials/planner.html" if context["planner_view"] else "partials/daily_desk.html"
    return TEMPLATES.TemplateResponse(
        request=request, name=partial if fragment else "workspace.html",
        context=context, status_code=status,
    )


@router.post("/today/events/{event_id}/agent", name="prepare_daily_task")
async def prepare_daily_task(request: Request, event_id: str):
    event = request.app.state.focus.daily_event(event_id)
    if event is None or event.status in {"done", "paused"}:
        return not_found(request, "workspace")
    runtime = request.app.state.agent_core
    task = runtime.create_task(
        title=event.title, objective=event.title, task_type="research",
        project_id=DEFAULT_PROJECT_ID, source_event_id=event.id,
    )
    try:
        run = runtime.plan_task(task.id)
    except ValueError:
        return RedirectResponse(request.url_for("task_detail", task_id=task.id), status_code=303)
    return RedirectResponse(request.url_for("run_detail", run_id=run.id), status_code=303)


@router.get(
    "/partials/workspace-feed",
    response_class=HTMLResponse,
    name="workspace_feed_partial",
)
async def workspace_feed_partial(
    request: Request,
    q: Optional[str] = Query(default=None),
    view: Optional[str] = Query(default="pending"),
) -> HTMLResponse:
    context = _workspace_feed_context(_collection(request), query=q, view=view)
    response = TEMPLATES.TemplateResponse(
        request=request,
        name="partials/workspace_feed.html",
        context=context,
    )
    response.headers["HX-Push-Url"] = (
        f"/?{urlencode({'view': context['workspace_view'], 'q': context['workspace_query']})}"
    )
    return response

@router.post("/ideas", name="create_idea")
async def create_idea(
    request: Request,
    body: str = Form(...),
    title: str = Form(default=""),
    tags: str = Form(default=""),
    category: str = Form(default=""),
) -> HTMLResponse:
    try:
        item = create_item(
            request.app.state.content_root,
            body=body,
            title=title,
            tags=tags,
            category=category,
        )
        _refresh_search_item(request, item)
        _refresh_obsidian_links(request)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="workspace.html",
            context=_workspace_context(
                request,
                error=str(error),
                form_data={
                    "body": body,
                    "title": title,
                    "tags": tags,
                    "category": category,
                },
                view="pending",
            ),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("workspace").include_query_params(
            saved="created",
            view="pending",
        ),
        status_code=303,
    )

@router.get("/ideas", response_class=HTMLResponse, name="ideas")
async def ideas(
    request: Request,
    q: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> HTMLResponse:
    collection = _collection(request)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="ideas.html",
        context={
            "active_page": "ideas",
            "diagnostics": collection.diagnostics,
            **_idea_filters(
                collection,
                query=q,
                status=status,
                tag=tag,
                category=category,
                date_from=date_from,
                date_to=date_to,
            ),
        },
    )

@router.get(
    "/partials/ideas",
    response_class=HTMLResponse,
    name="ideas_partial",
)
async def ideas_partial(
    request: Request,
    q: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> HTMLResponse:
    context = _idea_filters(
        _collection(request),
        query=q,
        status=status,
        tag=tag,
        category=category,
        date_from=date_from,
        date_to=date_to,
    )
    response = TEMPLATES.TemplateResponse(
        request=request,
        name="partials/idea_list.html",
        context=context,
    )
    query_string = request.url.query
    response.headers["HX-Push-Url"] = (
        f"/ideas{f'?{query_string}' if query_string else ''}"
    )
    return response

@router.get(
    "/ideas/{item_id}",
    response_class=HTMLResponse,
    name="idea_detail",
)
async def idea_detail(request: Request, item_id: str) -> HTMLResponse:
    collection = _collection(request)
    item = collection.get(item_id)
    if item is None:
        return _not_found(request, "ideas")
    if item.kind == "article":
        return RedirectResponse(
            request.url_for("article_detail", item_id=item.id),
            status_code=303,
        )
    if item.kind == "weekly-review":
        return RedirectResponse(
            request.url_for("review_detail", item_id=item.id),
            status_code=303,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="idea_detail.html",
        context={
            "active_page": "ideas",
            "knowledge_candidates": tuple(
                candidate
                for candidate in distillable_items(collection)
                if candidate.id != item.id
            ),
            **_item_context(item, request.app.state.content_root),
        },
    )


@router.get(
    "/ideas/{item_id}/distill",
    response_class=HTMLResponse,
    name="distill_idea",
)
async def distill_idea(request: Request, item_id: str) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if item is None or item.kind != "thought" or item.status == "archived":
        return _not_found(request, "ideas")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="idea_distill.html",
        context=_distill_context(request, item),
    )


@router.post(
    "/ideas/{item_id}/distill/cards",
    name="create_distilled_knowledge_card",
)
async def create_distilled_knowledge_card(
    request: Request,
    item_id: str,
    title: str = Form(...),
    body: str = Form(...),
    card_type: str = Form(...),
    map_ids: list[str] = Form(default=[]),
    concepts: str = Form(default=""),
    supersedes_card_id: str = Form(default=""),
) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if item is None or item.kind != "thought" or item.status == "archived":
        return _not_found(request, "ideas")
    try:
        with content_lock(request.app.state.content_root):
            store = load_knowledge_store(request.app.state.content_root)
            previous = store.card(supersedes_card_id) if supersedes_card_id else None
            if supersedes_card_id and (
                previous is None
                or previous.status != "active"
                or item.id not in previous.source_ids
            ):
                raise ValueError("要替代的知识卡不是这条随想的有效已有结论")
            selected_maps = tuple(dict.fromkeys(map_ids))
            card = create_knowledge_card(
                request.app.state.content_root,
                title=title,
                body=body,
                card_type=card_type,
                subjects=subjects_for_topic_maps(store, selected_maps),
                source_ids=(item.id,),
                map_ids=selected_maps,
                concepts=tuple(
                    dict.fromkeys(
                        value.strip()
                        for value in concepts.replace("，", ",").split(",")
                        if value.strip()
                    )
                ),
            )
            if previous is not None:
                supersede_knowledge_card(
                    request.app.state.content_root,
                    previous.id,
                    card.id,
                )
        _refresh_obsidian_links(request)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_distill.html",
            context=_distill_context(request, item, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("distill_idea", item_id=item.id).include_query_params(
            saved="card"
        ),
        status_code=303,
    )


@router.post(
    "/ideas/{item_id}/distill/model-task",
    name="create_idea_distill_model_task",
)
async def create_idea_distill_model_task(
    request: Request,
    item_id: str,
) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if item is None or item.kind != "thought" or item.status == "archived":
        return _not_found(request, "ideas")
    store = load_knowledge_store(request.app.state.content_root)
    payload = json.dumps(
        {
            "sources": [{"id": item.id, "title": item.title, "body": item.body}],
            "allowed_subjects": list(DEFAULT_SUBJECTS),
            "allowed_relation_targets": [
                card.id for card in store.cards if card.status == "active"
            ],
            "allowed_map_ids": [value.id for value in store.maps if value.kind == "topic"],
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.KNOWLEDGE.value,
            purpose=f"把随想《{item.title}》拆成原子知识卡候选",
            source_labels=(item.title,),
            payload=payload,
            return_url=str(request.url_for("distill_idea", item_id=item.id)),
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_distill.html",
            context=_distill_context(request, item, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id),
        status_code=303,
    )

@router.post("/ideas/{item_id}", name="update_idea")
async def update_idea(
    request: Request,
    item_id: str,
    body: str = Form(...),
    title: str = Form(default=""),
    tags: str = Form(default=""),
    category: str = Form(default=""),
    source_revision: str = Form(default=""),
) -> HTMLResponse:
    existing = _collection(request).get(item_id)
    if existing is None or existing.kind != "thought":
        return _not_found(request, "ideas")
    try:
        item = update_item(
            request.app.state.content_root,
            item_id,
            body=body,
            title=title,
            tags=tags,
            category=category,
            expected_revision=source_revision,
        )
    except ContentConflictError as error:
        current = error.current
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_conflict.html",
            context={
                "active_page": "ideas",
                "item": current,
                "current_html": render_markdown(
                    current.body,
                    source=current.source,
                    content_root=request.app.state.content_root,
                ),
                "submitted": {
                    "title": title,
                    "body": body,
                    "tags": tags,
                    "category": category,
                },
                "submitted_html": render_markdown(body),
                "obsidian_url": obsidian_uri(current.source),
            },
            status_code=409,
        )
    except KeyError:
        return _not_found(request, "ideas")
    except ValueError as error:
        current = _collection(request).get(item_id)
        if current is None:
            return _not_found(request, "ideas")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_detail.html",
            context={
                "active_page": "ideas",
                **_item_context(current, request.app.state.content_root),
                "error": str(error),
            },
            status_code=422,
        )
    _refresh_search_item(request, item)
    return RedirectResponse(
        request.url_for("idea_detail", item_id=item.id).include_query_params(
            saved="updated",
        ),
        status_code=303,
    )

@router.post(
    "/ideas/{item_id}/knowledge",
    name="update_idea_knowledge",
)
async def update_idea_knowledge(
    request: Request,
    item_id: str,
    subjects: str = Form(...),
    concepts: str = Form(default=""),
    relations: str = Form(default=""),
) -> HTMLResponse:
    collection = _collection(request)
    item = collection.get(item_id)
    if item is None or item.kind != "thought" or item.status == "archived":
        return _not_found(request, "ideas")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="idea_detail.html",
        context={
            "active_page": "ideas",
            **_item_context(item, request.app.state.content_root),
            "error": (
                "原始想法的旧版知识字段已停止写入。请在 Obsidian 中创建"
                "知识卡，并把这条想法选为来源。"
            ),
        },
        status_code=410,
    )

@router.post("/ideas/{item_id}/status", name="change_idea_status")
async def change_idea_status(
    request: Request,
    item_id: str,
    status: str = Form(...),
    return_to: str = Form(default="detail"),
    view: str = Form(default="pending"),
    q: str = Form(default=""),
) -> HTMLResponse:
    existing = _collection(request).get(item_id)
    if existing is None or existing.kind != "thought":
        return _not_found(request, "ideas")
    try:
        item = set_item_status(request.app.state.content_root, item_id, status)
        _refresh_obsidian_links(request)
    except KeyError:
        return _not_found(request, "ideas")
    except ValueError:
        return _not_found(request, "ideas")
    if return_to == "workspace":
        if request.headers.get("HX-Request", "").lower() == "true":
            return TEMPLATES.TemplateResponse(
                request=request,
                name="partials/workspace_feed.html",
                context=_workspace_feed_context(
                    _collection(request),
                    query=q,
                    view=view,
                    feed_notice="内容状态已更新。",
                ),
            )
        return RedirectResponse(
            request.url_for("workspace").include_query_params(
                saved="status",
                view=view if view in WORKSPACE_VIEWS else "pending",
                q=q.strip(),
            ),
            status_code=303,
        )
    return RedirectResponse(
        request.url_for("idea_detail", item_id=item.id).include_query_params(
            saved="status",
        ),
        status_code=303,
    )

@router.post("/ideas/{item_id}/trash", name="trash_idea")
async def trash_idea(request: Request, item_id: str) -> HTMLResponse:
    existing = _collection(request).get(item_id)
    if existing is None or existing.kind != "thought":
        return _not_found(request, "ideas")
    try:
        move_to_trash(request.app.state.content_root, item_id)
    except KeyError:
        return _not_found(request, "ideas")
    return RedirectResponse(
        request.url_for("ideas").include_query_params(saved="trashed"),
        status_code=303,
    )

@router.get(
    "/knowledge",
    response_class=HTMLResponse,
    name="knowledge",
)
async def knowledge(
    request: Request,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="knowledge.html",
        context=_knowledge_context(request, saved=saved),
    )

@router.post("/knowledge/analyze", name="analyze_knowledge")
async def analyze_knowledge(
    request: Request,
    outbound_text: str = Form(default=""),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="knowledge.html",
        context=_knowledge_context(
            request,
            error=(
                "旧版学科元数据分析已经停用。请使用“人工拆卡任务”或"
                "Obsidian 知识卡模板，候选结果会写入正式知识卡。"
            ),
        ),
        status_code=410,
    )

@router.post(
    "/knowledge/analyze/manual", name="manual_analyze_knowledge"
)
async def manual_analyze_knowledge(request: Request) -> HTMLResponse:
    collection = _collection(request)
    store = load_knowledge_store(request.app.state.content_root)
    covered = {
        source_id
        for card in store.cards
        if card.status != "archived"
        for source_id in card.source_ids
    }
    pending_items = tuple(
        item
        for item in distillable_items(collection)
        if item.id not in covered
    )
    if not pending_items:
        return RedirectResponse(
            request.url_for("knowledge").include_query_params(saved="up-to-date"),
            status_code=303,
        )
    selected = pending_items[: POLICIES[ModelTaskKind.KNOWLEDGE].max_items]
    payload = json.dumps(
        {
            "sources": [
                {"id": item.id, "title": item.title, "body": item.body}
                for item in selected
            ],
            "allowed_subjects": list(DEFAULT_SUBJECTS),
            "allowed_relation_targets": [
                item.id for item in eligible_items(collection)
            ],
            "allowed_map_ids": [
                item.id
                for item in load_knowledge_store(
                    request.app.state.content_root
                ).maps
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.KNOWLEDGE.value,
            purpose="把原始来源拆成可追溯的原子知识卡候选",
            source_labels=tuple(item.title for item in selected),
            payload=payload,
            return_url=str(request.url_for("knowledge")),
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge.html",
            context=_knowledge_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post("/knowledge/confirm", name="confirm_knowledge")
async def confirm_knowledge(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="knowledge.html",
        context=_knowledge_context(
            request,
            error="旧版来源元数据确认已经停用，原始想法不会再承担正式知识结构。",
        ),
        status_code=410,
    )

@router.get("/reviews", response_class=HTMLResponse, name="reviews")
async def reviews(
    request: Request,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    collection = _collection(request)
    settings = load_workspace_settings(request.app.state.content_root)
    notices = {
        "review": "本周回顾草稿已生成。",
        "existing": "本周回顾已经存在，没有重复生成。",
        "schedule": "本地定时设置已保存。",
        "fallback": "模型未使用，已生成稳定的规则回顾草稿。",
    }
    review_items = tuple(
        item for item in collection.items if item.kind == "weekly-review"
    )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="reviews.html",
        context={
            "active_page": "reviews",
            "week_items": current_week_items(request.app.state.content_root),
            "review_items": review_items,
            "latest_review": review_items[0] if review_items else None,
            "settings": settings,
            "weekdays": WEEKDAYS,
            "next_run": next_summary_run(settings),
            "llm_enabled": request.app.state.llm_client.enabled,
            "notice": notices.get(saved or ""),
        },
    )

@router.post("/reviews/generate", name="generate_review")
async def generate_review(
    request: Request,
    return_to: str = Form(default="reviews"),
    use_ai: str = Form(default=""),
    outbound_text: str = Form(default=""),
) -> HTMLResponse:
    client = request.app.state.llm_client
    summarizer = None
    if use_ai == "on" and client.enabled:
        originals = current_week_items(request.app.state.content_root)
        if not outbound_text:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="llm_disclosure.html",
                context=_disclosure_context(
                    request,
                    purpose="生成中性、直接的本周记录汇总",
                    task_type=ModelTaskKind.WEEKLY_REVIEW.value,
                    source_labels=tuple(item.title for item in originals),
                    submit_url=request.url_for("generate_review"),
                    outbound_text=_items_payload(originals),
                    back_url=request.url_for("reviews"),
                    hidden_fields={"return_to": return_to, "use_ai": "on"},
                ),
            )
        try:
            reviewed_items = _redacted_items(outbound_text, originals)
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="llm_disclosure.html",
                context=_disclosure_context(
                    request,
                    purpose="生成中性、直接的本周记录汇总",
                    task_type=ModelTaskKind.WEEKLY_REVIEW.value,
                    source_labels=tuple(item.title for item in originals),
                    submit_url=request.url_for("generate_review"),
                    outbound_text=outbound_text,
                    back_url=request.url_for("reviews"),
                    hidden_fields={"return_to": return_to, "use_ai": "on"},
                    error=str(error),
                ),
                status_code=422,
            )

        def summarize_reviewed(_items):
            return client.summarize(reviewed_items)

        summarizer = summarize_reviewed
    try:
        _, created, used_ai = await asyncio.to_thread(
            save_weekly_review,
            request.app.state.content_root,
            summarizer=summarizer,
        )
    except ValueError as error:
        if return_to == "workspace":
            return TEMPLATES.TemplateResponse(
                request=request,
                name="workspace.html",
                context=_workspace_context(
                    request,
                    error=str(error),
                    view="pending",
                ),
                status_code=422,
            )
        collection = _collection(request)
        settings = load_workspace_settings(request.app.state.content_root)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="reviews.html",
            context={
                "active_page": "reviews",
                "week_items": (),
                "review_items": tuple(
                    item
                    for item in collection.items
                    if item.kind == "weekly-review"
                ),
                "latest_review": None,
                "settings": settings,
                "weekdays": WEEKDAYS,
                "next_run": next_summary_run(settings),
                "llm_enabled": client.enabled,
                "error": str(error),
            },
            status_code=422,
        )
    saved = "existing" if not created else "review" if used_ai else "fallback"
    if return_to == "workspace":
        return RedirectResponse(
            request.url_for("workspace").include_query_params(
                saved=saved,
                view="pending",
            ),
            status_code=303,
        )
    return RedirectResponse(
        request.url_for("reviews").include_query_params(saved=saved),
        status_code=303,
    )

@router.post("/reviews/manual", name="manual_review_task")
async def manual_review_task(request: Request) -> HTMLResponse:
    originals = current_week_items(request.app.state.content_root)
    if not originals:
        return RedirectResponse(
            request.url_for("reviews").include_query_params(saved="fallback"),
            status_code=303,
        )
    try:
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.WEEKLY_REVIEW.value,
            purpose="生成中性、直接、可追溯的本周记录汇总",
            source_labels=tuple(item.title for item in originals),
            payload=_items_payload(originals),
            return_url=str(request.url_for("reviews")),
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="reviews.html",
            context={
                "active_page": "reviews",
                "week_items": originals,
                "review_items": tuple(
                    item
                    for item in _collection(request).items
                    if item.kind == "weekly-review"
                ),
                "latest_review": None,
                "settings": load_workspace_settings(
                    request.app.state.content_root
                ),
                "weekdays": WEEKDAYS,
                "next_run": next_summary_run(
                    load_workspace_settings(request.app.state.content_root)
                ),
                "llm_enabled": request.app.state.llm_client.enabled,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post("/reviews/schedule", name="save_review_schedule")
async def save_review_schedule(
    request: Request,
    enabled: Optional[str] = Form(default=None),
    weekday: int = Form(...),
    time_value: str = Form(..., alias="time"),
) -> HTMLResponse:
    try:
        save_workspace_settings(
            request.app.state.content_root,
            enabled=enabled == "on",
            weekday=weekday,
            time_value=time_value,
        )
    except ValueError:
        return _not_found(request, "reviews")
    return RedirectResponse(
        request.url_for("reviews").include_query_params(saved="schedule"),
        status_code=303,
    )


@router.get(
    "/reviews/{item_id}",
    response_class=HTMLResponse,
    name="review_detail",
)
async def review_detail(request: Request, item_id: str) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if item is None or item.kind != "weekly-review":
        return _not_found(request, "reviews")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="review_detail.html",
        context=_review_context(request, item),
    )


@router.post("/reviews/{item_id}", name="update_review")
async def update_review(
    request: Request,
    item_id: str,
    body: str = Form(...),
    title: str = Form(default=""),
    tags: str = Form(default=""),
    category: str = Form(default=""),
    source_revision: str = Form(default=""),
) -> HTMLResponse:
    existing = _collection(request).get(item_id)
    if existing is None or existing.kind != "weekly-review":
        return _not_found(request, "reviews")
    try:
        item = update_item(
            request.app.state.content_root,
            item_id,
            body=body,
            title=title,
            tags=tags,
            category=category,
            expected_revision=source_revision,
        )
    except ContentConflictError as error:
        current = error.current
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_conflict.html",
            context={
                "active_page": "reviews",
                "item": current,
                "detail_url": request.url_for("review_detail", item_id=current.id),
                "current_html": render_markdown(
                    current.body,
                    source=current.source,
                    content_root=request.app.state.content_root,
                ),
                "submitted": {
                    "title": title,
                    "body": body,
                    "tags": tags,
                    "category": category,
                },
                "submitted_html": render_markdown(body),
                "obsidian_url": obsidian_uri(current.source),
            },
            status_code=409,
        )
    except (KeyError, ValueError) as error:
        current = _collection(request).get(item_id)
        if current is None or current.kind != "weekly-review":
            return _not_found(request, "reviews")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="review_detail.html",
            context=_review_context(request, current, error=str(error)),
            status_code=422,
        )
    _refresh_search_item(request, item)
    return RedirectResponse(
        request.url_for("review_detail", item_id=item.id).include_query_params(
            saved="updated"
        ),
        status_code=303,
    )


@router.post("/reviews/{item_id}/status", name="change_review_status")
async def change_review_status(
    request: Request,
    item_id: str,
    status: str = Form(...),
) -> HTMLResponse:
    existing = _collection(request).get(item_id)
    if existing is None or existing.kind != "weekly-review":
        return _not_found(request, "reviews")
    try:
        item = set_item_status(request.app.state.content_root, item_id, status)
        _refresh_obsidian_links(request)
    except (KeyError, ValueError):
        return _not_found(request, "reviews")
    return RedirectResponse(
        request.url_for("review_detail", item_id=item.id).include_query_params(
            saved="status"
        ),
        status_code=303,
    )
