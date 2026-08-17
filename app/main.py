"""FastAPI application for 羽白工作台."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
import yaml
from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.responses import Response

from app.backup import (
    create_encrypted_backup,
    inspect_encrypted_backup,
    restore_encrypted_backup,
)
from app.career import (
    DOCUMENT_KINDS,
    JOB_STATUSES,
    LEARNING_STATUSES,
    PROJECT_STATUSES,
    RESUME_STATUSES,
    CareerRepository,
)
from app.content import (
    ContentCollection,
    ContentItem,
    load_items,
    render_markdown,
    semantic_revision,
)
from app.knowledge import (
    DEFAULT_SUBJECTS,
    clear_pending_suggestions,
    eligible_items,
    format_relation_lines,
    load_pending_suggestions,
    parse_relation_lines,
    rebuild_knowledge_index,
    save_pending_suggestions,
    stale_items,
    validate_suggestions,
)
from app.knowledge_store import (
    KnowledgeCard,
    KnowledgeEdge,
    create_knowledge_card,
    create_knowledge_map,
    layered_graph,
    load_knowledge_store,
    supersede_knowledge_card,
)
from app.library import (
    MATERIAL_STATUSES,
    MATERIAL_TYPES,
    create_material,
    load_materials,
    update_material_status,
)
from app.llm import OpenAICompatibleClient, PolishResult, StyleClient
from app.model_gateway import (
    POLICIES,
    ModelGateway,
    ModelTaskKind,
    ModelTaskStore,
)
from app.mobile import MobileStore
from app.obsidian import ObsidianBridge, obsidian_uri
from app.publishing import (
    PublishingSource,
    WECHAT_RENDERER,
    resolve_publishing_source,
)
from app.privacy import (
    LocalOnlyMiddleware,
    csrf_token,
    default_data_root,
    prepare_private_root,
    require_csrf,
)
from app.search import SearchRepository
from app.vault import apply_vault_migration, plan_vault_migration
from app.video import (
    VIDEO_ASPECT_RATIOS,
    VIDEO_PLATFORMS,
    VIDEO_STATUS_LABELS,
    VIDEO_STATUSES,
    VIDEO_TYPES,
    VideoProjectRepository,
    VideoScene,
    inspect_opencut,
)
from app.workspace import (
    KIND_LABELS,
    SHANGHAI,
    STATUS_LABELS,
    WEEKDAYS,
    ContentConflictError,
    create_item,
    current_week_items,
    items_directory,
    load_workspace_settings,
    move_to_trash,
    next_summary_run,
    permanently_delete,
    restore_from_trash,
    run_summary_scheduler,
    save_weekly_review,
    save_workspace_settings,
    set_item_status,
    trash_directory,
    update_item,
    update_knowledge_metadata,
)


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
TEMPLATES = Jinja2Templates(directory=APP_DIR / "templates")
TEMPLATES.env.globals.update(
    kind_labels=KIND_LABELS,
    status_labels=STATUS_LABELS,
    video_status_labels=VIDEO_STATUS_LABELS,
    video_platform_labels=VIDEO_PLATFORMS,
    video_type_labels=VIDEO_TYPES,
    csrf_token=csrf_token,
)

WORKSPACE_VIEWS = {
    "pending": "待整理",
    "articles": "文章草稿",
    "published": "已成稿",
    "all": "全部",
}
TEMPLATES.env.globals.update(workspace_view_labels=WORKSPACE_VIEWS)


class SafeStaticFiles(StaticFiles):
    """Serve application assets while blocking legacy/private article images."""

    async def get_response(self, path: str, scope) -> Response:
        if path == "images" or path.startswith("images/"):
            return Response(status_code=404)
        return await super().get_response(path, scope)


def _collection(request: Request) -> ContentCollection:
    return load_items(items_directory(request.app.state.content_root))


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="404.html",
        context={"active_page": active_page},
        status_code=404,
    )


def _return_path_id(return_url: str, prefix: str) -> str | None:
    path = urlparse(return_url).path
    expected = f"{prefix.rstrip('/')}/"
    if not path.startswith(expected):
        return None
    value = path[len(expected) :].split("/", 1)[0]
    return value if value and Path(value).name == value else None


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


def _obsidian_context(
    request: Request,
    *,
    state=None,
    notice: str = "",
    error: str = "",
) -> dict:
    bridge: ObsidianBridge = request.app.state.obsidian
    store = load_knowledge_store(request.app.state.content_root)
    collection = _collection(request)
    return {
        "active_page": "settings",
        "state": state or bridge.state(),
        "inbox": bridge.inbox(),
        "knowledge_inbox": bridge.knowledge_inbox(),
        "knowledge_maps": store.maps,
        "knowledge_sources": eligible_items(collection),
        "migration": bridge.migration_preview(),
        "vault_url": obsidian_uri(request.app.state.content_root),
        "knowledge_home_url": obsidian_uri(
            request.app.state.content_root / "知识首页.md"
        ),
        "notice": notice,
        "error": error,
    }


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
    collection = _collection(request)
    today = datetime.now(SHANGHAI).date()
    today_items = tuple(
        item for item in collection.items if item.created_at.date() == today
    )
    notices = {
        "created": "想法已落进本地 Markdown。先记下来，整理可以晚一点。",
        "article": "候选稿已保存为新的文章草稿，原始想法没有被改动。",
        "status": "内容状态已更新。",
        "review": "本周回顾草稿已生成。",
        "existing": "本周回顾已经存在，没有重复生成。",
        "fallback": "模型未使用，已生成稳定的规则回顾草稿。",
    }
    settings = load_workspace_settings(request.app.state.content_root)
    week_items = current_week_items(request.app.state.content_root)
    review_items = tuple(
        item for item in collection.items if item.kind == "weekly-review"
    )
    article_drafts = tuple(
        item
        for item in collection.items
        if item.kind == "article" and item.status == "draft"
    )
    career: CareerRepository = request.app.state.career
    video_projects = request.app.state.video.projects()
    jobs = career.jobs()
    learning_tasks = career.learning_tasks()
    return {
        "active_page": "workspace",
        "today_items": today_items,
        "pending_count": len(
            [item for item in collection.items if item.status == "draft"],
        ),
        "published_count": len(collection.published),
        "week_items": week_items,
        "latest_review": review_items[0] if review_items else None,
        "settings": settings,
        "next_run": next_summary_run(settings),
        "llm_enabled": request.app.state.llm_client.enabled,
        "article_drafts": article_drafts[:3],
        "video_projects": tuple(
            project for project in video_projects if project.status != "archived"
        )[:3],
        "career_jobs": jobs[:4],
        "career_active_count": sum(
            job.status not in {"rejected", "withdrawn", "archived"} for job in jobs
        ),
        "learning_tasks": tuple(
            task for task in learning_tasks if task.status in {"backlog", "active"}
        )[:4],
        "diagnostics": collection.diagnostics,
        "notice": notices.get(saved or ""),
        "error": error,
        "form_data": form_data or {},
        **_workspace_feed_context(collection, query=query, view=view),
    }


def _video_context(
    request: Request,
    *,
    saved: str | None = None,
    error: str | None = None,
) -> dict:
    collection = _collection(request)
    projects = request.app.state.video.projects()
    notices = {
        "created": "视频策划项目已生成。原文章没有被修改，初始分镜和私有交接文件已经就位。",
        "status": "视频项目状态已更新。",
        "plan": "视频规格与分镜已保存，旁白、字幕、Remotion Props 和 OpenCut 交接文件已重新生成。",
    }
    return {
        "active_page": "video",
        "articles": tuple(
            item
            for item in collection.items
            if item.kind == "article" and item.status != "archived"
        ),
        "video_projects": projects,
        "video_counts": {
            status: sum(project.status == status for project in projects)
            for status in VIDEO_STATUSES
        },
        "opencut": inspect_opencut(REPO_ROOT.parent / "OpenCut"),
        "video_platforms": VIDEO_PLATFORMS,
        "video_aspect_ratios": tuple(sorted(VIDEO_ASPECT_RATIOS)),
        "video_types": VIDEO_TYPES,
        "notice": notices.get(saved or ""),
        "error": error,
    }


def _workspace_feed_context(
    collection: ContentCollection,
    *,
    query: str | None,
    view: str | None,
    feed_notice: str | None = None,
) -> dict:
    selected_view = view if view in WORKSPACE_VIEWS else "pending"
    cleaned_query = (query or "").strip()
    searched = collection.filter(query=cleaned_query)

    def in_view(item: ContentItem, target: str) -> bool:
        if target == "pending":
            return item.status == "draft" and item.kind != "article"
        if target == "articles":
            return item.status == "draft" and item.kind == "article"
        if target == "published":
            return item.status == "published"
        return True

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
    kind: str | None,
    tag: str | None,
    category: str | None,
    date_from: str | None,
    date_to: str | None,
) -> dict:
    return {
        "items": collection.filter(
            query=query,
            status=status,
            kind=kind,
            tag=tag,
            category=category,
            date_from=date_from,
            date_to=date_to,
        ),
        "tags": sorted({tag for item in collection.items for tag in item.tags}),
        "categories": sorted(
            {item.category for item in collection.items if item.category},
        ),
        "selected": {
            "q": query or "",
            "status": status or "",
            "kind": kind or "",
            "tag": tag or "",
            "category": category or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    }


def _publish_context(
    request: Request,
    item: ContentItem,
    *,
    candidate: PolishResult | None = None,
    error: str | None = None,
) -> dict:
    source = PublishingSource(
        source_id=item.id,
        kind=item.kind,
        title=candidate.title if candidate else item.title,
        summary=item.summary,
        markdown=candidate.markdown if candidate else item.body,
    )
    return {
        "active_page": "publish",
        "item": item,
        "source": source,
        "rendered": WECHAT_RENDERER.render(source),
        "original_html": render_markdown(item.body),
        "candidate": candidate,
        "error": error,
        "llm_enabled": request.app.state.llm_client.enabled,
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


def _career_job_context(
    request: Request,
    job,
    *,
    skill_candidates: tuple[dict, ...] = (),
    error: str | None = None,
) -> dict:
    repository: CareerRepository = request.app.state.career
    gap_map = {gap.skill_id: gap for gap in repository.gaps() if gap.job_id == job.id}
    analyzer = getattr(request.app.state.llm_client, "job_skill_candidate", None)
    return {
        "active_page": "career",
        "job": job,
        "events": repository.job_events(job.id),
        "skills": repository.skills(),
        "gap_map": gap_map,
        "job_statuses": JOB_STATUSES,
        "llm_enabled": request.app.state.llm_client.enabled and callable(analyzer),
        "skill_candidates": skill_candidates,
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


def _comma_values(value: str) -> list[str]:
    return [
        part.strip() for part in value.replace("，", ",").split(",") if part.strip()
    ]


def create_app(
    content_root: Path | None = None,
    *,
    data_root: Path | None = None,
    enable_scheduler: bool = True,
    llm_client: StyleClient | None = None,
    enforce_security: bool | None = None,
) -> FastAPI:
    """Create the local-first workspace, optionally isolated for tests."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        task = None
        if enable_scheduler:
            task = asyncio.create_task(
                run_summary_scheduler(
                    application.state.content_root,
                    summarizer=None,
                ),
            )
        yield
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    workspace_app = FastAPI(
        title="羽白工作台",
        description="本地优先的个人想法工作台",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        dependencies=[Depends(require_csrf)],
    )
    is_test_isolation = content_root is not None and data_root is None
    resolved_data_root = (
        data_root.expanduser().resolve()
        if data_root is not None
        else (content_root.resolve() if is_test_isolation else default_data_root())
    )
    prepare_private_root(resolved_data_root)
    workspace_app.state.data_root = resolved_data_root
    workspace_app.state.content_root = (
        content_root.resolve()
        if content_root is not None
        else resolved_data_root / "content"
    )
    workspace_app.state.enforce_security = (
        not is_test_isolation if enforce_security is None else enforce_security
    )
    if llm_client is None:
        gateway = ModelGateway(resolved_data_root)
        workspace_app.state.model_gateway = gateway
        workspace_app.state.llm_client = gateway
    else:
        workspace_app.state.llm_client = llm_client
        workspace_app.state.model_gateway = ModelGateway(
            resolved_data_root,
            client=llm_client if isinstance(llm_client, OpenAICompatibleClient) else None,
        )
    workspace_app.state.model_tasks = ModelTaskStore(
        resolved_data_root,
        workspace_app.state.model_gateway.usage,
    )
    workspace_app.state.career = CareerRepository(resolved_data_root)
    workspace_app.state.video = VideoProjectRepository(
        resolved_data_root,
        workspace_app.state.content_root,
    )
    workspace_app.state.search = SearchRepository(resolved_data_root)
    workspace_app.state.mobile_store = MobileStore(resolved_data_root)
    workspace_app.state.obsidian = ObsidianBridge(
        resolved_data_root,
        workspace_app.state.content_root,
    )
    workspace_app.state.career.seed_agent_reliability_campaign(
        str(REPO_ROOT.parent / "agent-reliability-arena"),
    )
    workspace_app.add_middleware(
        LocalOnlyMiddleware,
        enforce=workspace_app.state.enforce_security,
    )
    workspace_app.mount(
        "/static",
        SafeStaticFiles(directory=APP_DIR / "static"),
        name="static",
    )

    @workspace_app.get("/assets/{asset_name}", name="private_asset")
    async def private_asset(request: Request, asset_name: str) -> FileResponse:
        if Path(asset_name).name != asset_name or Path(
            asset_name
        ).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return _not_found(request)  # type: ignore[return-value]
        path = request.app.state.content_root / "assets" / asset_name
        if not path.is_file():
            return _not_found(request)  # type: ignore[return-value]
        return FileResponse(path)

    @workspace_app.get("/", response_class=HTMLResponse, name="workspace")
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

    @workspace_app.get(
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

    @workspace_app.post("/ideas", name="create_idea")
    async def create_idea(
        request: Request,
        body: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            create_item(
                request.app.state.content_root,
                body=body,
                title=title,
                tags=tags,
                category=category,
            )
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

    @workspace_app.get("/ideas", response_class=HTMLResponse, name="ideas")
    async def ideas(
        request: Request,
        q: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        kind: Optional[str] = Query(default=None),
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
                    kind=kind,
                    tag=tag,
                    category=category,
                    date_from=date_from,
                    date_to=date_to,
                ),
            },
        )

    @workspace_app.get(
        "/partials/ideas",
        response_class=HTMLResponse,
        name="ideas_partial",
    )
    async def ideas_partial(
        request: Request,
        q: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        kind: Optional[str] = Query(default=None),
        tag: Optional[str] = Query(default=None),
        category: Optional[str] = Query(default=None),
        date_from: Optional[str] = Query(default=None),
        date_to: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        context = _idea_filters(
            _collection(request),
            query=q,
            status=status,
            kind=kind,
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

    @workspace_app.get(
        "/ideas/{item_id}",
        response_class=HTMLResponse,
        name="idea_detail",
    )
    async def idea_detail(request: Request, item_id: str) -> HTMLResponse:
        collection = _collection(request)
        item = collection.get(item_id)
        if item is None:
            return _not_found(request, "ideas")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_detail.html",
            context={
                "active_page": "ideas",
                "knowledge_candidates": tuple(
                    candidate
                    for candidate in eligible_items(collection)
                    if candidate.id != item.id
                ),
                **_item_context(item, request.app.state.content_root),
            },
        )

    @workspace_app.post("/ideas/{item_id}", name="update_idea")
    async def update_idea(
        request: Request,
        item_id: str,
        body: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
        source_revision: str = Form(default=""),
    ) -> HTMLResponse:
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
        return RedirectResponse(
            request.url_for("idea_detail", item_id=item.id).include_query_params(
                saved="updated",
            ),
            status_code=303,
        )

    @workspace_app.post(
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
        if item is None or item.kind == "weekly-review" or item.status == "archived":
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

    @workspace_app.post("/ideas/{item_id}/status", name="change_idea_status")
    async def change_idea_status(
        request: Request,
        item_id: str,
        status: str = Form(...),
        return_to: str = Form(default="detail"),
        view: str = Form(default="pending"),
        q: str = Form(default=""),
    ) -> HTMLResponse:
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

    @workspace_app.post("/ideas/{item_id}/trash", name="trash_idea")
    async def trash_idea(request: Request, item_id: str) -> HTMLResponse:
        try:
            move_to_trash(request.app.state.content_root, item_id)
        except KeyError:
            return _not_found(request, "ideas")
        return RedirectResponse(
            request.url_for("ideas").include_query_params(saved="trashed"),
            status_code=303,
        )

    @workspace_app.get(
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

    @workspace_app.post("/knowledge/analyze", name="analyze_knowledge")
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
        collection = _collection(request)
        pending_items = stale_items(collection)
        if not pending_items:
            return RedirectResponse(
                request.url_for("knowledge").include_query_params(saved="up-to-date"),
                status_code=303,
            )
        client = request.app.state.llm_client
        analyzer = getattr(client, "analyze_knowledge", None)
        if not client.enabled or not callable(analyzer):
            return TEMPLATES.TemplateResponse(
                request=request,
                name="knowledge.html",
                context=_knowledge_context(
                    request,
                    error="尚未配置可用模型，请先手动维护学科和概念。",
                ),
                status_code=422,
            )
        all_items = eligible_items(collection)
        if not outbound_text:
            payload = json.dumps(
                {
                    "items": [
                        {"id": item.id, "title": item.title, "body": item.body}
                        for item in pending_items
                    ],
                    "catalog": [
                        {
                            "id": item.id,
                            "title": item.title,
                            "subjects": list(item.subjects),
                        }
                        for item in all_items
                    ],
                    "allowed_subjects": list(DEFAULT_SUBJECTS),
                },
                ensure_ascii=False,
                indent=2,
            )
            return TEMPLATES.TemplateResponse(
                request=request,
                name="llm_disclosure.html",
                context=_disclosure_context(
                    request,
                    purpose="为待整理内容建议学科、概念和内容关联",
                    task_type=ModelTaskKind.KNOWLEDGE.value,
                    source_labels=tuple(item.title for item in pending_items),
                    submit_url=request.url_for("analyze_knowledge"),
                    outbound_text=payload,
                    back_url=request.url_for("knowledge"),
                ),
            )
        try:
            material_analyzer = getattr(client, "analyze_knowledge_material", None)
            if callable(material_analyzer):
                suggestions = await asyncio.to_thread(
                    material_analyzer,
                    outbound_text,
                    all_items,
                )
            else:
                reviewed_items = _redacted_items(outbound_text, all_items)
                suggestions = await asyncio.to_thread(
                    analyzer,
                    reviewed_items,
                    all_items,
                    DEFAULT_SUBJECTS,
                )
            save_pending_suggestions(
                request.app.state.content_root,
                suggestions,
                all_items,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="knowledge.html",
                context=_knowledge_context(
                    request,
                    error=f"知识分析失败：{error}",
                ),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("knowledge").include_query_params(saved="analyzed"),
            status_code=303,
        )

    @workspace_app.post(
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
            for item in eligible_items(collection)
            if item.kind != "weekly-review" and item.id not in covered
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

    @workspace_app.post("/knowledge/confirm", name="confirm_knowledge")
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
        form = await request.form()
        selected_ids = {str(value) for value in form.getlist("selected")}
        collection = _collection(request)
        items = eligible_items(collection)
        pending = {
            suggestion.item_id: suggestion
            for suggestion in load_pending_suggestions(
                request.app.state.content_root,
                items,
            )
        }
        if not selected_ids:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="knowledge.html",
                context=_knowledge_context(
                    request,
                    error="请至少选择一条建议后再确认。",
                ),
                status_code=422,
            )
        if not selected_ids <= pending.keys():
            return _not_found(request, "knowledge")
        raw_suggestions: list[dict] = []
        try:
            for item_id in sorted(selected_ids):
                relation_values = parse_relation_lines(
                    str(form.get(f"relations__{item_id}", "")),
                    item_id=item_id,
                    known_ids={item.id for item in items},
                )
                raw_suggestions.append(
                    {
                        "item_id": item_id,
                        "subjects": _comma_values(
                            str(form.get(f"subjects__{item_id}", "")),
                        ),
                        "concepts": _comma_values(
                            str(form.get(f"concepts__{item_id}", "")),
                        ),
                        "relations": [
                            {
                                "target_id": relation.target_id,
                                "type": relation.relation,
                                "note": relation.note,
                            }
                            for relation in relation_values
                        ],
                    },
                )
            confirmed = validate_suggestions(
                {"suggestions": raw_suggestions},
                items,
            )
            for suggestion in confirmed:
                update_knowledge_metadata(
                    request.app.state.content_root,
                    suggestion.item_id,
                    subjects=suggestion.subjects,
                    concepts=suggestion.concepts,
                    relations=suggestion.relations,
                )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="knowledge.html",
                context=_knowledge_context(request, error=str(error)),
                status_code=422,
            )

        refreshed = eligible_items(_collection(request))
        rebuild_knowledge_index(
            request.app.state.content_root,
            refreshed,
            model_summaries=None,
        )
        clear_pending_suggestions(request.app.state.content_root)
        return RedirectResponse(
            request.url_for("knowledge").include_query_params(
                saved="confirmed-fallback",
            ),
            status_code=303,
        )

    @workspace_app.get("/reviews", response_class=HTMLResponse, name="reviews")
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

    @workspace_app.post("/reviews/generate", name="generate_review")
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

    @workspace_app.post("/reviews/manual", name="manual_review_task")
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

    @workspace_app.post("/reviews/schedule", name="save_review_schedule")
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

    @workspace_app.get("/publish", response_class=HTMLResponse, name="publish_index")
    async def publish_index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish_index.html",
            context={
                "active_page": "publish",
                "items": _collection(request).items,
                "llm_enabled": request.app.state.llm_client.enabled,
            },
        )

    @workspace_app.get(
        "/publish/{item_id}",
        response_class=HTMLResponse,
        name="publish_item",
    )
    async def publish_item(request: Request, item_id: str) -> HTMLResponse:
        item = _collection(request).get(item_id)
        if (
            item is None
            or resolve_publishing_source(
                request.app.state.content_root,
                item_id,
            )
            is None
        ):
            return _not_found(request, "publish")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context=_publish_context(request, item),
        )

    @workspace_app.post(
        "/publish/{item_id}/polish",
        response_class=HTMLResponse,
        name="polish_item",
    )
    async def polish_item(
        request: Request,
        item_id: str,
        mode: str = Form(default="auto"),
        outbound_text: str = Form(default=""),
    ) -> HTMLResponse:
        item = _collection(request).get(item_id)
        if item is None:
            return _not_found(request, "publish")
        client = request.app.state.llm_client
        if not client.enabled:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="publish.html",
                context=_publish_context(
                    request,
                    item,
                    error="尚未配置兼容模型，忠实排版仍可正常使用。",
                ),
                status_code=422,
            )
        if not outbound_text:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="llm_disclosure.html",
                context=_disclosure_context(
                    request,
                    purpose="生成公众号幻想栈风格候选稿",
                    task_type=ModelTaskKind.PUBLISH.value,
                    source_labels=(item.title,),
                    submit_url=request.url_for("polish_item", item_id=item.id),
                    outbound_text=json.dumps(
                        {"title": item.title, "body": item.body},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    back_url=request.url_for("publish_item", item_id=item.id),
                    hidden_fields={"mode": mode},
                ),
            )
        try:
            reviewed = json.loads(outbound_text)
            reviewed_title = str(reviewed["title"]).strip()
            reviewed_body = str(reviewed["body"]).strip()
            if not reviewed_title or not reviewed_body:
                raise ValueError("标题和正文不能为空")
            candidate = await asyncio.to_thread(
                client.polish,
                title=reviewed_title[:120],
                body=reviewed_body,
                mode=mode,
            )
        except (
            KeyError,
            TypeError,
            json.JSONDecodeError,
            RuntimeError,
            ValueError,
            httpx.HTTPError,
        ) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="publish.html",
                context=_publish_context(request, item, error=f"润色失败：{error}"),
                status_code=502,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context=_publish_context(request, item, candidate=candidate),
        )

    @workspace_app.post(
        "/publish/{item_id}/manual", name="manual_publish_task"
    )
    async def manual_publish_task(
        request: Request,
        item_id: str,
        mode: str = Form(default="auto"),
    ) -> HTMLResponse:
        item = _collection(request).get(item_id)
        if item is None or mode not in {"auto", "essay", "explainer"}:
            return _not_found(request, "publish")
        payload = json.dumps(
            {"title": item.title, "body": item.body, "mode": mode},
            ensure_ascii=False,
            indent=2,
        )
        try:
            task = request.app.state.model_tasks.create(
                task_type=ModelTaskKind.PUBLISH.value,
                purpose="生成幻想栈风格公众号候选稿，不覆盖原文",
                source_labels=(item.title,),
                payload=payload,
                return_url=str(request.url_for("publish_item", item_id=item.id)),
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="publish.html",
                context=_publish_context(request, item, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("model_task", task_id=task.id), status_code=303
        )

    @workspace_app.post("/publish/{item_id}/save", name="save_polished_article")
    async def save_polished_article(
        request: Request,
        item_id: str,
        title: str = Form(...),
        markdown: str = Form(...),
    ) -> HTMLResponse:
        source = _collection(request).get(item_id)
        if source is None:
            return _not_found(request, "publish")
        try:
            created = create_item(
                request.app.state.content_root,
                title=title,
                body=markdown,
                tags=source.tags,
                category=source.category or "",
                kind="article",
                parent_id=source.id,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="publish.html",
                context=_publish_context(request, source, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("workspace").include_query_params(
                saved="article",
                view="articles",
                created=created.id,
            ),
            status_code=303,
        )

    @workspace_app.get("/video", response_class=HTMLResponse, name="video_studio")
    async def video_studio(
        request: Request,
        saved: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="video.html",
            context=_video_context(request, saved=saved),
        )

    @workspace_app.post("/video/projects", name="create_video_project")
    async def create_video_project(
        request: Request,
        source_id: str = Form(...),
        notes: str = Form(default=""),
        platform: str = Form(default="general"),
        aspect_ratio: str = Form(default="16:9"),
        target_duration: int = Form(default=90),
        video_type: str = Form(default="knowledge-explainer"),
        audience: str = Form(default="对主题感兴趣的普通读者"),
        tone: str = Form(default="清晰、克制、保留个人观察"),
    ) -> HTMLResponse:
        source = _collection(request).get(source_id)
        if source is None:
            return _not_found(request, "video")
        try:
            request.app.state.video.create(
                source,
                notes=notes,
                platform=platform,
                aspect_ratio=aspect_ratio,
                target_duration=target_duration,
                video_type=video_type,
                audience=audience,
                tone=tone,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="video.html",
                context=_video_context(request, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("video_studio").include_query_params(saved="created"),
            status_code=303,
        )

    @workspace_app.post(
        "/video/projects/{project_id}/plan",
        name="update_video_project_plan",
    )
    async def update_video_project_plan(
        request: Request,
        project_id: str,
        platform: str = Form(...),
        aspect_ratio: str = Form(...),
        target_duration: int = Form(...),
        video_type: str = Form(...),
        audience: str = Form(...),
        tone: str = Form(...),
        notes: str = Form(default=""),
        scene_duration: list[int] = Form(...),
        scene_narration: list[str] = Form(...),
        scene_visual: list[str] = Form(...),
        scene_caption: list[str] = Form(...),
        scene_assets: list[str] = Form(default=[]),
    ) -> HTMLResponse:
        lengths = {
            len(scene_duration),
            len(scene_narration),
            len(scene_visual),
            len(scene_caption),
        }
        if len(lengths) != 1 or not scene_duration:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="video.html",
                context=_video_context(request, error="分镜表单结构无效，请刷新页面后重试"),
                status_code=422,
            )
        padded_assets = scene_assets + [""] * (len(scene_duration) - len(scene_assets))
        scenes = tuple(
            VideoScene(
                id=f"scene-{index + 1:02d}",
                duration_seconds=duration,
                narration=scene_narration[index],
                visual=scene_visual[index],
                caption=scene_caption[index],
                assets=tuple(
                    value.strip()
                    for value in padded_assets[index].replace("，", ",").split(",")
                    if value.strip()
                ),
            )
            for index, duration in enumerate(scene_duration)
        )
        try:
            request.app.state.video.update_plan(
                project_id,
                platform=platform,
                aspect_ratio=aspect_ratio,
                target_duration=target_duration,
                video_type=video_type,
                audience=audience,
                tone=tone,
                notes=notes,
                scenes=scenes,
            )
        except KeyError:
            return _not_found(request, "video")
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="video.html",
                context=_video_context(request, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("video_studio").include_query_params(saved="plan"),
            status_code=303,
        )

    @workspace_app.post(
        "/video/projects/{project_id}/status",
        name="update_video_project_status",
    )
    async def update_video_project_status(
        request: Request,
        project_id: str,
        status: str = Form(...),
    ) -> HTMLResponse:
        try:
            request.app.state.video.update_status(project_id, status)
        except KeyError:
            return _not_found(request, "video")
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="video.html",
                context=_video_context(request, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("video_studio").include_query_params(saved="status"),
            status_code=303,
        )

    @workspace_app.get(
        "/video/projects/{project_id}/files/{file_path:path}",
        name="video_project_file",
    )
    async def video_project_file(
        request: Request,
        project_id: str,
        file_path: str,
    ) -> FileResponse:
        path = request.app.state.video.resolve_file(project_id, file_path)
        if path is None:
            return _not_found(request, "video")  # type: ignore[return-value]
        return FileResponse(path, filename=path.name)

    @workspace_app.get("/career", response_class=HTMLResponse, name="career")
    async def career(request: Request) -> HTMLResponse:
        repository: CareerRepository = request.app.state.career
        jobs = repository.jobs()
        tasks = repository.learning_tasks()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career.html",
            context={
                "active_page": "career",
                "profile": repository.profile(),
                "jobs": jobs,
                "projects": repository.projects(),
                "resumes": repository.resumes(),
                "active_jobs": tuple(
                    job
                    for job in jobs
                    if job.status not in {"rejected", "withdrawn", "archived"}
                ),
                "active_tasks": tuple(
                    task for task in tasks if task.status in {"backlog", "active"}
                ),
            },
        )

    @workspace_app.get(
        "/career/profile",
        response_class=HTMLResponse,
        name="career_profile",
    )
    async def career_profile(request: Request) -> HTMLResponse:
        repository: CareerRepository = request.app.state.career
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_profile.html",
            context={
                "active_page": "career",
                "profile": repository.profile(),
                "documents": repository.documents(),
                "llm_enabled": request.app.state.llm_client.enabled,
            },
        )

    @workspace_app.post("/career/profile", name="save_career_profile")
    async def save_career_profile(
        request: Request,
        target_roles: str = Form(default=""),
        contact: str = Form(default=""),
        education: str = Form(default=""),
        experience: str = Form(default=""),
        certifications: str = Form(default=""),
        skills: str = Form(default=""),
        facts: str = Form(default=""),
    ) -> HTMLResponse:
        request.app.state.career.save_profile(
            target_roles=target_roles,
            contact=contact,
            education=education,
            experience=experience,
            certifications=certifications,
            skills=skills,
            facts=facts,
        )
        return RedirectResponse(
            request.url_for("career_profile").include_query_params(saved="profile"),
            status_code=303,
        )

    @workspace_app.post(
        "/career/profile/import/{document_id}/preview",
        response_class=HTMLResponse,
        name="preview_profile_import",
    )
    async def preview_profile_import(
        request: Request, document_id: str
    ) -> HTMLResponse:
        document = request.app.state.career.document(document_id)
        if document is None or not document.extracted_text:
            return _not_found(request, "career")
        config = getattr(request.app.state.llm_client, "config", None)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="llm_disclosure.html",
            context={
                "active_page": "career",
                "purpose": "从简历资料提取候选人档案候选字段",
                "task_type": ModelTaskKind.PROFILE.value,
                "source_labels": (document.original_name,),
                "target": getattr(config, "base_url", "") if config else "",
                "submit_url": request.url_for(
                    "analyze_profile_import", document_id=document_id
                ),
                "outbound_text": document.extracted_text,
                "back_url": request.url_for("career_profile"),
            },
        )

    @workspace_app.post(
        "/career/profile/import/{document_id}/manual",
        name="manual_profile_import",
    )
    async def manual_profile_import(
        request: Request, document_id: str
    ) -> HTMLResponse:
        document = request.app.state.career.document(document_id)
        if document is None or not document.extracted_text:
            return _not_found(request, "career")
        try:
            task = request.app.state.model_tasks.create(
                task_type=ModelTaskKind.PROFILE.value,
                purpose="从简历资料提取候选人档案候选字段",
                source_labels=(document.original_name,),
                payload=document.extracted_text,
                return_url=str(request.url_for("career_profile")),
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_profile.html",
                context={
                    "active_page": "career",
                    "profile": request.app.state.career.profile(),
                    "documents": request.app.state.career.documents(),
                    "llm_enabled": request.app.state.llm_client.enabled,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("model_task", task_id=task.id), status_code=303
        )

    @workspace_app.post(
        "/career/profile/import/{document_id}/analyze",
        response_class=HTMLResponse,
        name="analyze_profile_import",
    )
    async def analyze_profile_import(
        request: Request,
        document_id: str,
        outbound_text: str = Form(...),
    ) -> HTMLResponse:
        document = request.app.state.career.document(document_id)
        client = request.app.state.llm_client
        analyzer = getattr(client, "profile_candidate", None)
        if document is None or not client.enabled or not callable(analyzer):
            return _not_found(request, "career")
        try:
            candidate = await asyncio.to_thread(analyzer, outbound_text)
        except (RuntimeError, ValueError, httpx.HTTPError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="llm_disclosure.html",
                context={
                    "active_page": "career",
                    "purpose": "从简历资料提取候选人档案候选字段",
                    "task_type": ModelTaskKind.PROFILE.value,
                    "source_labels": (document.original_name,),
                    "target": getattr(getattr(client, "config", None), "base_url", ""),
                    "submit_url": request.url_for(
                        "analyze_profile_import", document_id=document_id
                    ),
                    "outbound_text": outbound_text,
                    "back_url": request.url_for("career_profile"),
                    "error": f"分析失败：{error}",
                },
                status_code=502,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_profile.html",
            context={
                "active_page": "career",
                "profile": request.app.state.career.profile(),
                "candidate": candidate,
                "documents": request.app.state.career.documents(),
                "llm_enabled": True,
                "notice": "模型只生成了候选字段；请检查后再保存。",
            },
        )

    @workspace_app.get(
        "/career/documents",
        response_class=HTMLResponse,
        name="career_documents",
    )
    async def career_documents(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_documents.html",
            context={
                "active_page": "career",
                "documents": request.app.state.career.documents(),
                "document_kinds": DOCUMENT_KINDS,
            },
        )

    @workspace_app.post("/career/documents", name="upload_career_document")
    async def upload_career_document(
        request: Request,
        kind: str = Form(...),
        upload: UploadFile = File(...),
    ) -> HTMLResponse:
        content = await upload.read(20 * 1024 * 1024 + 1)
        try:
            request.app.state.career.add_document(
                kind=kind,
                filename=upload.filename or "upload",
                content=content,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_documents.html",
                context={
                    "active_page": "career",
                    "documents": request.app.state.career.documents(),
                    "document_kinds": DOCUMENT_KINDS,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("career_documents").include_query_params(saved="uploaded"),
            status_code=303,
        )

    @workspace_app.get(
        "/career/documents/{document_id}/download", name="download_career_document"
    )
    async def download_career_document(
        request: Request, document_id: str
    ) -> FileResponse:
        document = request.app.state.career.document(document_id)
        if document is None:
            return _not_found(request, "career")  # type: ignore[return-value]
        if Path(document.stored_name).name != document.stored_name:
            return _not_found(request, "career")  # type: ignore[return-value]
        path = request.app.state.data_root / "documents" / document.stored_name
        if not path.is_file():
            return _not_found(request, "career")  # type: ignore[return-value]
        return FileResponse(
            path, media_type="application/octet-stream", filename=document.original_name
        )

    @workspace_app.post(
        "/career/documents/{document_id}/delete", name="delete_career_document"
    )
    async def delete_career_document(
        request: Request,
        document_id: str,
        confirmation: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            request.app.state.career.delete_document(document_id, confirmation)
        except KeyError:
            return _not_found(request, "career")
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_documents.html",
                context={
                    "active_page": "career",
                    "documents": request.app.state.career.documents(),
                    "document_kinds": DOCUMENT_KINDS,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("career_documents").include_query_params(saved="deleted"),
            status_code=303,
        )

    @workspace_app.get(
        "/career/projects", response_class=HTMLResponse, name="career_projects"
    )
    async def career_projects(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_projects.html",
            context={
                "active_page": "career",
                "projects": request.app.state.career.projects(),
                "project_statuses": PROJECT_STATUSES,
            },
        )

    @workspace_app.post("/career/projects", name="create_career_project")
    async def create_career_project(request: Request) -> HTMLResponse:
        form = await request.form()
        try:
            request.app.state.career.add_project(
                **{
                    key: str(value)
                    for key, value in form.items()
                    if key != "csrf_token"
                }
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_projects.html",
                context={
                    "active_page": "career",
                    "projects": request.app.state.career.projects(),
                    "project_statuses": PROJECT_STATUSES,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("career_projects").include_query_params(saved="created"),
            status_code=303,
        )

    @workspace_app.post("/career/projects/{project_id}", name="update_career_project")
    async def update_career_project(request: Request, project_id: str) -> HTMLResponse:
        form = await request.form()
        try:
            request.app.state.career.update_project(
                project_id,
                **{
                    key: str(value)
                    for key, value in form.items()
                    if key != "csrf_token"
                },
            )
        except (KeyError, ValueError):
            return _not_found(request, "career")
        return RedirectResponse(
            request.url_for("career_projects").include_query_params(saved="updated"),
            status_code=303,
        )

    @workspace_app.get(
        "/career/resumes", response_class=HTMLResponse, name="career_resumes"
    )
    async def career_resumes(request: Request) -> HTMLResponse:
        repository = request.app.state.career
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_resumes.html",
            context={
                "active_page": "career",
                "resumes": repository.resumes(),
                "documents": repository.documents("resume"),
                "projects": repository.projects(),
                "resume_statuses": RESUME_STATUSES,
            },
        )

    @workspace_app.post("/career/resumes", name="create_resume_version")
    async def create_resume_version(
        request: Request,
        title: str = Form(...),
        target_role: str = Form(default=""),
        document_id: str = Form(default=""),
        project_ids: list[str] = Form(default=[]),
        status: str = Form(default="draft"),
        notes: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            request.app.state.career.add_resume(
                title=title,
                target_role=target_role,
                document_id=document_id,
                project_ids=tuple(project_ids),
                status=status,
                notes=notes,
            )
        except ValueError as error:
            repository = request.app.state.career
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_resumes.html",
                context={
                    "active_page": "career",
                    "resumes": repository.resumes(),
                    "documents": repository.documents("resume"),
                    "projects": repository.projects(),
                    "resume_statuses": RESUME_STATUSES,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("career_resumes").include_query_params(saved="created"),
            status_code=303,
        )

    @workspace_app.post(
        "/career/resumes/{resume_id}/status", name="change_resume_status"
    )
    async def change_resume_status(
        request: Request, resume_id: str, status: str = Form(...)
    ) -> HTMLResponse:
        try:
            request.app.state.career.update_resume_status(resume_id, status)
        except (KeyError, ValueError):
            return _not_found(request, "career")
        return RedirectResponse(request.url_for("career_resumes"), status_code=303)

    @workspace_app.get("/career/jobs", response_class=HTMLResponse, name="career_jobs")
    async def career_jobs(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_jobs.html",
            context={
                "active_page": "career",
                "jobs": request.app.state.career.jobs(),
                "job_statuses": JOB_STATUSES,
            },
        )

    @workspace_app.post("/career/jobs", name="create_career_job")
    async def create_career_job(
        request: Request,
        company: str = Form(...),
        title: str = Form(...),
        jd_text: str = Form(...),
        location: str = Form(default=""),
        source_url: str = Form(default=""),
        notes: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            job = request.app.state.career.add_job(
                company=company,
                title=title,
                jd_text=jd_text,
                location=location,
                source_url=source_url,
                notes=notes,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_jobs.html",
                context={
                    "active_page": "career",
                    "jobs": request.app.state.career.jobs(),
                    "job_statuses": JOB_STATUSES,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("career_job_detail", job_id=job.id), status_code=303
        )

    @workspace_app.get(
        "/career/jobs/{job_id}", response_class=HTMLResponse, name="career_job_detail"
    )
    async def career_job_detail(request: Request, job_id: str) -> HTMLResponse:
        repository = request.app.state.career
        job = repository.job(job_id)
        if job is None:
            return _not_found(request, "career")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_job_detail.html",
            context=_career_job_context(request, job),
        )

    @workspace_app.post("/career/jobs/{job_id}/status", name="change_job_status")
    async def change_job_status(
        request: Request,
        job_id: str,
        status: str = Form(...),
        note: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            request.app.state.career.update_job_status(job_id, status, note)
        except (KeyError, ValueError):
            return _not_found(request, "career")
        return RedirectResponse(
            request.url_for("career_job_detail", job_id=job_id), status_code=303
        )

    @workspace_app.post("/career/jobs/{job_id}/skills", name="save_job_skill_gap")
    async def save_job_skill_gap(
        request: Request,
        job_id: str,
        skill_id: str = Form(...),
        importance: int = Form(...),
        evidence: str = Form(default=""),
        gap_note: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            request.app.state.career.set_job_skill_gap(
                job_id=job_id,
                skill_id=skill_id,
                importance=importance,
                evidence=evidence,
                gap_note=gap_note,
            )
        except ValueError:
            return _not_found(request, "career")
        return RedirectResponse(
            request.url_for("career_job_detail", job_id=job_id), status_code=303
        )

    @workspace_app.post(
        "/career/jobs/{job_id}/skills/preview",
        response_class=HTMLResponse,
        name="preview_job_skills",
    )
    async def preview_job_skills(request: Request, job_id: str) -> HTMLResponse:
        job = request.app.state.career.job(job_id)
        analyzer = getattr(request.app.state.llm_client, "job_skill_candidate", None)
        if (
            job is None
            or not request.app.state.llm_client.enabled
            or not callable(analyzer)
        ):
            return _not_found(request, "career")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="llm_disclosure.html",
            context=_disclosure_context(
                request,
                purpose="从不可信职位描述中提取技能要求候选",
                task_type=ModelTaskKind.JOB_SKILLS.value,
                source_labels=(f"{job.company} · {job.title}",),
                submit_url=request.url_for("analyze_job_skills", job_id=job.id),
                outbound_text=job.jd_text,
                back_url=request.url_for("career_job_detail", job_id=job.id),
            ),
        )

    @workspace_app.post(
        "/career/jobs/{job_id}/skills/manual", name="manual_job_skills"
    )
    async def manual_job_skills(request: Request, job_id: str) -> HTMLResponse:
        job = request.app.state.career.job(job_id)
        if job is None or not job.jd_text.strip():
            return _not_found(request, "career")
        try:
            task = request.app.state.model_tasks.create(
                task_type=ModelTaskKind.JOB_SKILLS.value,
                purpose="从不可信职位描述中提取技能要求候选",
                source_labels=(f"{job.company} · {job.title}",),
                payload=job.jd_text,
                return_url=str(
                    request.url_for("career_job_detail", job_id=job.id)
                ),
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_job_detail.html",
                context=_career_job_context(request, job, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("model_task", task_id=task.id), status_code=303
        )

    @workspace_app.post(
        "/career/jobs/{job_id}/skills/analyze",
        response_class=HTMLResponse,
        name="analyze_job_skills",
    )
    async def analyze_job_skills(
        request: Request,
        job_id: str,
        outbound_text: str = Form(...),
    ) -> HTMLResponse:
        job = request.app.state.career.job(job_id)
        client = request.app.state.llm_client
        analyzer = getattr(client, "job_skill_candidate", None)
        if job is None or not client.enabled or not callable(analyzer):
            return _not_found(request, "career")
        try:
            candidates = await asyncio.to_thread(analyzer, outbound_text)
        except (RuntimeError, ValueError, httpx.HTTPError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_job_detail.html",
                context=_career_job_context(
                    request,
                    job,
                    error=f"职位要求分析失败：{error}",
                ),
                status_code=502,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_job_detail.html",
            context=_career_job_context(
                request,
                job,
                skill_candidates=tuple(candidates),
            ),
        )

    @workspace_app.post(
        "/career/jobs/{job_id}/skills/confirm",
        name="confirm_job_skills",
    )
    async def confirm_job_skills(request: Request, job_id: str) -> HTMLResponse:
        repository: CareerRepository = request.app.state.career
        job = repository.job(job_id)
        if job is None:
            return _not_found(request, "career")
        form = await request.form()
        selected = list(dict.fromkeys(str(value) for value in form.getlist("selected")))
        try:
            if not selected or len(selected) > 30:
                raise ValueError("请至少选择一条技能候选")
            reviewed: list[tuple[str, str, int, str]] = []
            for raw_index in selected:
                if not raw_index.isdigit():
                    raise ValueError("技能候选编号无效")
                index = int(raw_index)
                name = str(form.get(f"name_{index}", "")).strip()
                category = str(form.get(f"category_{index}", "")).strip()
                requirement = str(form.get(f"requirement_{index}", "")).strip()
                importance = int(str(form.get(f"importance_{index}", "3")))
                if not name or len(name) > 120 or importance not in range(1, 6):
                    raise ValueError("技能名称或重要度无效")
                reviewed.append((name, category[:120], importance, requirement[:2000]))
        except (TypeError, ValueError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="career_job_detail.html",
                context=_career_job_context(request, job, error=str(error)),
                status_code=422,
            )
        for name, category, importance, requirement in reviewed:
            skill = repository.find_or_add_skill(name=name, category=category)
            repository.set_job_skill_gap(
                job_id=job.id,
                skill_id=skill.id,
                importance=importance,
                gap_note=requirement,
            )
        return RedirectResponse(
            request.url_for("career_job_detail", job_id=job.id).include_query_params(
                saved="skills",
            ),
            status_code=303,
        )

    @workspace_app.get("/learning", response_class=HTMLResponse, name="learning")
    async def learning(request: Request) -> HTMLResponse:
        repository = request.app.state.career
        repository.seed_agent_reliability_campaign(
            str(REPO_ROOT.parent / "agent-reliability-arena"),
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="learning.html",
            context={
                "active_page": "learning",
                "skills": repository.skills(),
                "tasks": repository.learning_tasks(),
                "gaps": repository.gaps(),
                "jobs": {job.id: job for job in repository.jobs()},
                "learning_statuses": LEARNING_STATUSES,
                "projects": repository.projects(),
                "content_items": eligible_items(_collection(request)),
                "campaigns": repository.campaigns(),
                "campaign_xp": {
                    campaign.id: repository.campaign_xp(campaign.id)
                    for campaign in repository.campaigns()
                },
            },
        )

    def campaign_context(
        request: Request,
        campaign_id: str,
        *,
        error: str | None = None,
        notice: str | None = None,
    ) -> dict | None:
        repository: CareerRepository = request.app.state.career
        campaign = repository.campaign(campaign_id)
        if campaign is None:
            return None
        quests = repository.quests(campaign_id)
        tasks = {task.id: task for task in repository.learning_tasks()}
        return {
            "active_page": "learning",
            "campaign": campaign,
            "quests": quests,
            "quest_evidence": {
                quest.id: repository.quest_evidence(quest.id) for quest in quests
            },
            "tasks": tasks,
            "earned_xp": repository.campaign_xp(campaign_id),
            "error": error,
            "notice": notice,
        }

    @workspace_app.get(
        "/learning/campaigns/{campaign_id}",
        response_class=HTMLResponse,
        name="learning_campaign",
    )
    async def learning_campaign(
        request: Request,
        campaign_id: str,
        saved: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        notices = {
            "started": "关卡已开始。通关靠证据，不靠签到。",
            "evidence": "验收证据已保存到本地私人数据库。",
            "cleared": "关卡已通关，XP 已到账，下一关已解锁。",
        }
        context = campaign_context(
            request,
            campaign_id,
            notice=notices.get(saved or ""),
        )
        if context is None:
            return _not_found(request, "learning")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="learning_campaign.html",
            context=context,
        )

    @workspace_app.post(
        "/learning/campaigns/{campaign_id}/quests/{quest_id}/start",
        name="start_campaign_quest",
    )
    async def start_campaign_quest(
        request: Request,
        campaign_id: str,
        quest_id: str,
    ) -> HTMLResponse:
        try:
            quest = request.app.state.career.start_quest(quest_id)
            if quest.campaign_id != campaign_id:
                raise KeyError(quest_id)
        except (KeyError, ValueError):
            return _not_found(request, "learning")
        return RedirectResponse(
            request.url_for(
                "learning_campaign", campaign_id=campaign_id
            ).include_query_params(
                saved="started",
            ),
            status_code=303,
        )

    @workspace_app.post(
        "/learning/campaigns/{campaign_id}/quests/{quest_id}/evidence",
        name="submit_quest_evidence",
    )
    async def submit_quest_evidence(
        request: Request,
        campaign_id: str,
        quest_id: str,
        commit_sha: str = Form(...),
        test_result: str = Form(...),
        reflection: str = Form(default=""),
        evidence_url: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            quest = request.app.state.career.quest(quest_id)
            if quest is None or quest.campaign_id != campaign_id:
                raise KeyError(quest_id)
            request.app.state.career.add_quest_evidence(
                quest_id,
                commit_sha=commit_sha,
                test_result=test_result,
                reflection=reflection,
                evidence_url=evidence_url,
            )
        except KeyError:
            return _not_found(request, "learning")
        except ValueError as error:
            context = campaign_context(request, campaign_id, error=str(error))
            if context is None:
                return _not_found(request, "learning")
            return TEMPLATES.TemplateResponse(
                request=request,
                name="learning_campaign.html",
                context=context,
                status_code=422,
            )
        return RedirectResponse(
            request.url_for(
                "learning_campaign", campaign_id=campaign_id
            ).include_query_params(
                saved="evidence",
            ),
            status_code=303,
        )

    @workspace_app.post(
        "/learning/campaigns/{campaign_id}/quests/{quest_id}/clear",
        name="clear_campaign_quest",
    )
    async def clear_campaign_quest(
        request: Request,
        campaign_id: str,
        quest_id: str,
        confirmation: str = Form(default=""),
    ) -> HTMLResponse:
        if confirmation.strip() != "确认通关":
            context = campaign_context(
                request,
                campaign_id,
                error="请输入“确认通关”后再结算 XP。",
            )
            if context is None:
                return _not_found(request, "learning")
            return TEMPLATES.TemplateResponse(
                request=request,
                name="learning_campaign.html",
                context=context,
                status_code=422,
            )
        try:
            quest = request.app.state.career.quest(quest_id)
            if quest is None or quest.campaign_id != campaign_id:
                raise KeyError(quest_id)
            request.app.state.career.clear_quest(quest_id)
        except KeyError:
            return _not_found(request, "learning")
        except ValueError as error:
            context = campaign_context(request, campaign_id, error=str(error))
            if context is None:
                return _not_found(request, "learning")
            return TEMPLATES.TemplateResponse(
                request=request,
                name="learning_campaign.html",
                context=context,
                status_code=422,
            )
        return RedirectResponse(
            request.url_for(
                "learning_campaign", campaign_id=campaign_id
            ).include_query_params(
                saved="cleared",
            ),
            status_code=303,
        )

    @workspace_app.post("/learning/skills", name="create_skill")
    async def create_skill(
        request: Request,
        name: str = Form(...),
        category: str = Form(default=""),
        current_level: int = Form(default=0),
        target_level: int = Form(default=3),
        notes: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            request.app.state.career.add_skill(
                name=name,
                category=category,
                current_level=current_level,
                target_level=target_level,
                notes=notes,
            )
        except ValueError as error:
            repository = request.app.state.career
            return TEMPLATES.TemplateResponse(
                request=request,
                name="learning.html",
                context={
                    "active_page": "learning",
                    "skills": repository.skills(),
                    "tasks": repository.learning_tasks(),
                    "gaps": repository.gaps(),
                    "jobs": {job.id: job for job in repository.jobs()},
                    "learning_statuses": LEARNING_STATUSES,
                    "projects": repository.projects(),
                    "content_items": eligible_items(_collection(request)),
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(request.url_for("learning"), status_code=303)

    @workspace_app.post("/learning/tasks", name="create_learning_task")
    async def create_learning_task(
        request: Request,
        skill_id: str = Form(...),
        title: str = Form(...),
        status: str = Form(default="backlog"),
        priority: int = Form(default=3),
        linked_content_id: str = Form(default=""),
        linked_project_id: str = Form(default=""),
        notes: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            request.app.state.career.add_learning_task(
                skill_id=skill_id,
                title=title,
                status=status,
                priority=priority,
                linked_content_id=linked_content_id,
                linked_project_id=linked_project_id,
                notes=notes,
            )
        except ValueError:
            return _not_found(request, "learning")
        return RedirectResponse(request.url_for("learning"), status_code=303)

    @workspace_app.post(
        "/learning/tasks/{task_id}/status", name="change_learning_task_status"
    )
    async def change_learning_task_status(
        request: Request, task_id: str, status: str = Form(...)
    ) -> HTMLResponse:
        try:
            request.app.state.career.update_learning_task_status(task_id, status)
        except (KeyError, ValueError):
            return _not_found(request, "learning")
        return RedirectResponse(request.url_for("learning"), status_code=303)

    @workspace_app.get("/models", response_class=HTMLResponse, name="models")
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

    @workspace_app.post("/models/pricing", name="save_model_pricing")
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

    @workspace_app.post("/model-tasks", name="create_model_task")
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

    @workspace_app.get(
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

    @workspace_app.post(
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

    @workspace_app.post(
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

    @workspace_app.post(
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

    @workspace_app.get(
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

    @workspace_app.post(
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

    @workspace_app.get(
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

    @workspace_app.post("/knowledge/maps", name="create_knowledge_map")
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

    @workspace_app.post("/knowledge/cards", name="create_knowledge_card")
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

    @workspace_app.get("/library", response_class=HTMLResponse, name="library")
    async def library(
        request: Request,
        material: Optional[str] = Query(default=None),
        saved: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        materials = load_materials(request.app.state.content_root)
        selected = next((item for item in materials if item.id == material), None)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="library.html",
            context={
                "active_page": "library",
                "materials": materials,
                "selected_material": selected,
                "selected_material_html": (
                    render_markdown(selected.body) if selected else ""
                ),
                "material_types": MATERIAL_TYPES,
                "material_statuses": MATERIAL_STATUSES,
                "documents": request.app.state.career.documents(),
                "notice": "材料已保存；链接没有被自动访问。" if saved else None,
            },
        )

    @workspace_app.post("/library", name="create_library_material")
    async def create_library_material(
        request: Request,
        title: str = Form(...),
        body: str = Form(default=""),
        source_type: str = Form(default="note"),
        source_url: str = Form(default=""),
        document_id: str = Form(default=""),
        status: str = Form(default="inbox"),
    ) -> HTMLResponse:
        if document_id and request.app.state.career.document(document_id) is None:
            return _not_found(request, "library")
        try:
            material = create_material(
                request.app.state.content_root,
                title=title,
                body=body,
                source_type=source_type,
                source_url=source_url,
                document_id=document_id,
                status=status,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="library.html",
                context={
                    "active_page": "library",
                    "materials": load_materials(request.app.state.content_root),
                    "selected_material": None,
                    "selected_material_html": "",
                    "material_types": MATERIAL_TYPES,
                    "material_statuses": MATERIAL_STATUSES,
                    "documents": request.app.state.career.documents(),
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("library").include_query_params(material=material.id, saved="created"),
            status_code=303,
        )

    @workspace_app.post(
        "/library/{material_id}/status", name="change_material_status"
    )
    async def change_material_status(
        request: Request,
        material_id: str,
        status: str = Form(...),
    ) -> HTMLResponse:
        try:
            update_material_status(
                request.app.state.content_root,
                material_id,
                status,
            )
        except (KeyError, ValueError):
            return _not_found(request, "library")
        return RedirectResponse(
            request.url_for("library").include_query_params(
                material=material_id,
                saved="status",
            ),
            status_code=303,
        )

    @workspace_app.post(
        "/library/{material_id}/thought", name="create_material_thought"
    )
    async def create_material_thought(
        request: Request,
        material_id: str,
        body: str = Form(...),
        title: str = Form(default=""),
    ) -> HTMLResponse:
        material = next(
            (
                item
                for item in load_materials(request.app.state.content_root)
                if item.id == material_id
            ),
            None,
        )
        if material is None:
            return _not_found(request, "library")
        source_line = (
            f"\n\n> 材料来源：{material.title}"
            + (f"\n> {material.source_url}" if material.source_url else "")
        )
        try:
            create_item(
                request.app.state.content_root,
                title=title,
                body=f"{body.strip()}{source_line}",
                tags=("阅读笔记",),
                category="材料摘录",
            )
            update_material_status(
                request.app.state.content_root,
                material.id,
                "reading",
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="library.html",
                context={
                    "active_page": "library",
                    "materials": load_materials(request.app.state.content_root),
                    "selected_material": material,
                    "selected_material_html": render_markdown(material.body),
                    "material_types": MATERIAL_TYPES,
                    "material_statuses": MATERIAL_STATUSES,
                    "documents": request.app.state.career.documents(),
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("workspace").include_query_params(
                view="pending", saved="created"
            ),
            status_code=303,
        )

    @workspace_app.get("/search", response_class=HTMLResponse, name="search")
    async def search(request: Request, q: str = Query(default="")) -> HTMLResponse:
        repository: SearchRepository = request.app.state.search
        repository.rebuild(
            items=_collection(request).items,
            knowledge=load_knowledge_store(request.app.state.content_root),
            materials=load_materials(request.app.state.content_root),
            career=request.app.state.career,
            video=request.app.state.video,
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "active_page": "search",
                "query": q,
                "results": repository.search(q) if q.strip() else (),
            },
        )

    @workspace_app.get(
        "/settings/vault-migration",
        response_class=HTMLResponse,
        name="vault_migration",
    )
    async def vault_migration(request: Request) -> HTMLResponse:
        entries = plan_vault_migration(request.app.state.content_root)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="vault_migration.html",
            context={"active_page": "settings", "entries": entries},
        )

    @workspace_app.post("/settings/vault-migration", name="apply_vault_migration")
    async def apply_vault_migration_route(
        request: Request,
        confirmation: str = Form(...),
    ) -> HTMLResponse:
        if confirmation.strip() != "迁移内容":
            return TEMPLATES.TemplateResponse(
                request=request,
                name="vault_migration.html",
                context={
                    "active_page": "settings",
                    "entries": plan_vault_migration(request.app.state.content_root),
                    "error": "请输入“迁移内容”确认。",
                },
                status_code=422,
            )
        entries = plan_vault_migration(request.app.state.content_root)
        try:
            rollback = apply_vault_migration(request.app.state.content_root, entries)
        except (OSError, ValueError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="vault_migration.html",
                context={"active_page": "settings", "entries": entries, "error": str(error)},
                status_code=422,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="vault_migration.html",
            context={
                "active_page": "settings",
                "entries": (),
                "notice": f"迁移完成；回滚目录：{rollback.name if rollback else '无需迁移'}",
            },
        )

    @workspace_app.get("/trash", response_class=HTMLResponse, name="trash")
    async def trash(
        request: Request,
        saved: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        collection = load_items(trash_directory(request.app.state.content_root))
        notices = {
            "restored": "内容已恢复到想法库。",
            "deleted": "内容已永久删除；只能从此前的加密备份恢复。",
        }
        return TEMPLATES.TemplateResponse(
            request=request,
            name="trash.html",
            context={
                "active_page": "trash",
                "items": collection.items,
                "diagnostics": collection.diagnostics,
                "notice": notices.get(saved or ""),
            },
        )

    @workspace_app.post("/trash/{item_id}/restore", name="restore_item")
    async def restore_item(request: Request, item_id: str) -> HTMLResponse:
        try:
            restore_from_trash(request.app.state.content_root, item_id)
        except KeyError:
            return _not_found(request, "settings")
        return RedirectResponse(
            request.url_for("trash").include_query_params(saved="restored"),
            status_code=303,
        )

    @workspace_app.post("/trash/{item_id}/delete", name="delete_item")
    async def delete_item(
        request: Request,
        item_id: str,
        confirmation: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            permanently_delete(
                request.app.state.content_root,
                item_id,
                confirmation,
            )
        except KeyError:
            return _not_found(request, "settings")
        except ValueError as error:
            collection = load_items(trash_directory(request.app.state.content_root))
            return TEMPLATES.TemplateResponse(
                request=request,
                name="trash.html",
                context={
                    "active_page": "trash",
                    "items": collection.items,
                    "diagnostics": collection.diagnostics,
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("trash").include_query_params(saved="deleted"),
            status_code=303,
        )

    @workspace_app.get("/settings", response_class=HTMLResponse, name="settings")
    async def settings(request: Request) -> HTMLResponse:
        client = request.app.state.llm_client
        config = getattr(client, "config", None)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="settings.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "content_root": request.app.state.content_root,
                "llm_enabled": client.enabled,
                "llm_model": getattr(config, "model", "") if config else "",
                "llm_base_url": getattr(config, "base_url", "") if config else "",
                "llm_is_local": urlparse(
                    getattr(config, "base_url", "") if config else "",
                ).hostname
                in {"localhost", "127.0.0.1", "::1"},
            },
        )

    @workspace_app.get(
        "/settings/obsidian",
        response_class=HTMLResponse,
        name="obsidian_settings",
    )
    async def obsidian_settings(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request),
        )

    @workspace_app.post(
        "/settings/obsidian/templates",
        name="initialize_obsidian_templates",
    )
    async def initialize_obsidian_templates(request: Request) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            changed = bridge.initialize_templates()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(
                    request,
                    notice=f"知识模板已就位，更新 {changed} 个模板文件。",
                ),
            )
        except OSError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )

    @workspace_app.post("/settings/obsidian/scan", name="scan_obsidian")
    async def scan_obsidian(request: Request) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            state = bridge.scan()
            notice = (
                f"扫描完成，协调了 {state.external_changes} 个外部修改。"
                if state.external_changes
                else "扫描完成，未发现需要协调的外部修改。"
            )
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, state=state, notice=notice),
            )
        except (OSError, ValueError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )

    @workspace_app.post(
        "/settings/obsidian/rebuild-links",
        name="rebuild_obsidian_links",
    )
    async def rebuild_obsidian_links(request: Request) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            changed = bridge.rebuild_links()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(
                    request,
                    notice=f"已重建原生关系链接，更新 {changed} 个文件。",
                ),
            )
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )

    @workspace_app.post(
        "/settings/obsidian/knowledge-inbox/{draft_id}/import",
        name="import_obsidian_knowledge_inbox",
    )
    async def import_obsidian_knowledge_inbox(
        request: Request,
        draft_id: str,
        expected_revision: str = Form(...),
        title: str = Form(default=""),
        summary: str = Form(default=""),
        subjects: str = Form(default=""),
        concepts: str = Form(default=""),
        source_ids: list[str] = Form(default=[]),
        map_ids: list[str] = Form(default=[]),
        parent_ids: list[str] = Form(default=[]),
    ) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            value = bridge.import_knowledge_inbox(
                draft_id,
                expected_revision=expected_revision,
                title=title,
                summary=summary,
                subjects=tuple(_comma_values(subjects)),
                concepts=tuple(_comma_values(concepts)),
                source_ids=tuple(source_ids),
                map_ids=tuple(map_ids),
                parent_ids=tuple(parent_ids),
            )
            bridge.rebuild_links()
            bridge.scan()
        except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )
        endpoint = "knowledge_card" if isinstance(value, KnowledgeCard) else "knowledge_map"
        parameter = {"card_id": value.id} if isinstance(value, KnowledgeCard) else {"map_id": value.id}
        return RedirectResponse(request.url_for(endpoint, **parameter), status_code=303)

    @workspace_app.post(
        "/settings/obsidian/migration/apply",
        name="apply_obsidian_migration",
    )
    async def apply_obsidian_migration(
        request: Request,
        confirmation: str = Form(...),
    ) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            snapshot = bridge.apply_migration(confirmation)
            bridge.rebuild_links()
            state = bridge.scan()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(
                    request,
                    state=state,
                    notice=f"知识结构已整理；回滚快照保存在 {snapshot.name}。",
                ),
            )
        except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )

    @workspace_app.post(
        "/settings/obsidian/migration/rollback",
        name="rollback_obsidian_migration",
    )
    async def rollback_obsidian_migration(
        request: Request,
        confirmation: str = Form(...),
    ) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            snapshot = bridge.rollback_latest_migration(confirmation)
            state = bridge.scan()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(
                    request,
                    state=state,
                    notice=f"已恢复到 {snapshot.name} 整理前的版本。",
                ),
            )
        except (OSError, ValueError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )

    @workspace_app.post(
        "/settings/obsidian/permissions",
        name="repair_obsidian_permissions",
    )
    async def repair_obsidian_permissions(request: Request) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            changed = bridge.repair_permissions()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(
                    request,
                    notice=f"权限检查完成，修复 {changed} 个路径。",
                ),
            )
        except OSError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )

    @workspace_app.post(
        "/settings/obsidian/inbox/{draft_id}/import",
        name="import_obsidian_inbox",
    )
    async def import_obsidian_inbox(
        request: Request,
        draft_id: str,
        expected_revision: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
    ) -> HTMLResponse:
        bridge: ObsidianBridge = request.app.state.obsidian
        try:
            item = bridge.import_inbox(
                draft_id,
                expected_revision=expected_revision,
                title=title,
                tags=tags,
                category=category,
            )
            bridge.rebuild_links()
            bridge.scan()
        except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="obsidian_settings.html",
                context=_obsidian_context(request, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("idea_detail", item_id=item.id).include_query_params(
                saved="imported",
            ),
            status_code=303,
        )

    @workspace_app.get(
        "/settings/mobile",
        response_class=HTMLResponse,
        name="mobile_settings",
    )
    async def mobile_settings(request: Request) -> HTMLResponse:
        store = request.app.state.mobile_store
        return TEMPLATES.TemplateResponse(
            request=request,
            name="mobile_settings.html",
            context={
                "active_page": "settings",
                "config": store.config(),
                "devices": store.devices(),
            },
        )

    @workspace_app.post("/settings/mobile/config", name="save_mobile_config")
    async def save_mobile_config(
        request: Request,
        enabled: Optional[str] = Form(default=None),
        tailnet_host: str = Form(default=""),
    ) -> HTMLResponse:
        store = request.app.state.mobile_store
        try:
            store.save_config(enabled=enabled == "on", tailnet_host=tailnet_host)
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="mobile_settings.html",
                context={
                    "active_page": "settings",
                    "config": store.config(),
                    "devices": store.devices(),
                    "error": str(error),
                },
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("mobile_settings").include_query_params(saved="config"),
            status_code=303,
        )

    @workspace_app.post(
        "/settings/mobile/pairing-code",
        name="create_mobile_pairing_code",
    )
    async def create_mobile_pairing_code(request: Request) -> HTMLResponse:
        store = request.app.state.mobile_store
        if not store.config().enabled:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="mobile_settings.html",
                context={
                    "active_page": "settings",
                    "config": store.config(),
                    "devices": store.devices(),
                    "error": "请先填写 Tailscale 主机并启用手机同步",
                },
                status_code=422,
            )
        code, expires_at = store.create_pairing_code()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="mobile_settings.html",
            context={
                "active_page": "settings",
                "config": store.config(),
                "devices": store.devices(),
                "pairing_code": code,
                "pairing_expires_at": expires_at,
            },
        )

    @workspace_app.post(
        "/settings/mobile/devices/{device_id}/revoke",
        name="revoke_mobile_device",
    )
    async def revoke_mobile_device(request: Request, device_id: str) -> HTMLResponse:
        try:
            request.app.state.mobile_store.revoke_device(device_id)
        except KeyError:
            return _not_found(request, "settings")
        return RedirectResponse(
            request.url_for("mobile_settings").include_query_params(saved="revoked"),
            status_code=303,
        )

    @workspace_app.get(
        "/settings/backups",
        response_class=HTMLResponse,
        name="backups",
    )
    async def backups(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
            },
        )

    @workspace_app.post("/settings/backups/export", name="export_backup")
    async def export_backup(
        request: Request, password: str = Form(...)
    ) -> FileResponse:
        working = request.app.state.data_root / "working"
        descriptor, path_text = tempfile.mkstemp(
            prefix="yubai-backup-", suffix=".zip", dir=working
        )
        os.close(descriptor)
        path = Path(path_text)
        try:
            create_encrypted_backup(request.app.state.data_root, password, path)
        except ValueError as error:
            path.unlink(missing_ok=True)
            return TEMPLATES.TemplateResponse(
                request=request,
                name="backups.html",
                context={
                    "active_page": "settings",
                    "data_root": request.app.state.data_root,
                    "error": str(error),
                },
                status_code=422,
            )  # type: ignore[return-value]
        filename = f"yubai-workspace-{datetime.now(SHANGHAI):%Y%m%d-%H%M%S}.zip"
        return FileResponse(
            path,
            media_type="application/zip",
            filename=filename,
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    @workspace_app.post(
        "/settings/backups/inspect",
        response_class=HTMLResponse,
        name="inspect_backup",
    )
    async def inspect_backup(
        request: Request,
        password: str = Form(...),
        upload: UploadFile = File(...),
    ) -> HTMLResponse:
        content = await upload.read(200 * 1024 * 1024 + 1)
        if len(content) > 200 * 1024 * 1024:
            error = "备份文件不能超过 200 MB"
            return TEMPLATES.TemplateResponse(
                request=request,
                name="backups.html",
                context={
                    "active_page": "settings",
                    "data_root": request.app.state.data_root,
                    "error": error,
                },
                status_code=422,
            )
        token = f"restore-{os.urandom(12).hex()}.zip"
        path = request.app.state.data_root / "working" / token
        path.write_bytes(content)
        path.chmod(0o600)
        try:
            preview = inspect_encrypted_backup(path, password)
        except ValueError as error:
            path.unlink(missing_ok=True)
            return TEMPLATES.TemplateResponse(
                request=request,
                name="backups.html",
                context={
                    "active_page": "settings",
                    "data_root": request.app.state.data_root,
                    "error": str(error),
                },
                status_code=422,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "preview": preview,
                "restore_token": token,
            },
        )

    @workspace_app.post("/settings/backups/restore", name="restore_backup")
    async def restore_backup(
        request: Request,
        restore_token: str = Form(...),
        password: str = Form(...),
        confirmation: str = Form(...),
    ) -> HTMLResponse:
        if (
            confirmation.strip() != "恢复备份"
            or not restore_token.startswith("restore-")
            or not restore_token.endswith(".zip")
            or Path(restore_token).name != restore_token
        ):
            return _not_found(request, "settings")
        path = request.app.state.data_root / "working" / restore_token
        if not path.is_file():
            return _not_found(request, "settings")
        try:
            rollback = restore_encrypted_backup(
                path, password, request.app.state.data_root
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="backups.html",
                context={
                    "active_page": "settings",
                    "data_root": request.app.state.data_root,
                    "error": str(error),
                },
                status_code=422,
            )
        finally:
            path.unlink(missing_ok=True)
        request.app.state.career = CareerRepository(request.app.state.data_root)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "notice": f"恢复完成；回滚副本保存在 {rollback.name}。",
            },
        )

    @workspace_app.exception_handler(404)
    async def not_found(request: Request, _error: Exception) -> HTMLResponse:
        return _not_found(request)

    return workspace_app


app = create_app()
