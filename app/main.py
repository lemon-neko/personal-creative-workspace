"""FastAPI application for 羽白的幻想栈 personal workspace."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.content import ContentCollection, ContentItem, load_items, render_markdown
from app.llm import OpenAICompatibleClient, PolishResult, StyleClient
from app.publishing import (
    PublishingSource,
    WECHAT_RENDERER,
    resolve_publishing_source,
)
from app.workspace import (
    KIND_LABELS,
    SHANGHAI,
    STATUS_LABELS,
    WEEKDAYS,
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
)


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
TEMPLATES = Jinja2Templates(directory=APP_DIR / "templates")
TEMPLATES.env.globals.update(
    kind_labels=KIND_LABELS,
    status_labels=STATUS_LABELS,
)


def _collection(request: Request) -> ContentCollection:
    return load_items(items_directory(request.app.state.content_root))


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="404.html",
        context={"active_page": active_page},
        status_code=404,
    )


def _item_context(item: ContentItem) -> dict:
    return {
        "item": item,
        "item_html": render_markdown(item.body),
        "tags_value": "，".join(item.tags),
    }


def _workspace_context(
    request: Request,
    *,
    saved: str | None = None,
    error: str | None = None,
    form_data: dict | None = None,
) -> dict:
    collection = _collection(request)
    today = datetime.now(SHANGHAI).date()
    today_items = tuple(
        item for item in collection.items if item.created_at.date() == today
    )
    notices = {
        "created": "想法已落进本地 Markdown。先记下来，整理可以晚一点。",
        "article": "候选稿已保存为新的文章草稿，原始想法没有被改动。",
    }
    return {
        "active_page": "workspace",
        "today_items": today_items,
        "recent_items": collection.items[:8],
        "pending_count": len(
            [item for item in collection.items if item.status == "draft"],
        ),
        "published_count": len(collection.published),
        "diagnostics": collection.diagnostics,
        "notice": notices.get(saved or ""),
        "error": error,
        "form_data": form_data or {},
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


def create_app(
    content_root: Path | None = None,
    *,
    enable_scheduler: bool = True,
    llm_client: StyleClient | None = None,
) -> FastAPI:
    """Create the local-first workspace, optionally isolated for tests."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        task = None
        if enable_scheduler:
            summarizer = (
                application.state.llm_client.summarize
                if application.state.llm_client.enabled
                else None
            )
            task = asyncio.create_task(
                run_summary_scheduler(
                    application.state.content_root,
                    summarizer=summarizer,
                ),
            )
        yield
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    workspace_app = FastAPI(
        title="羽白的幻想栈",
        description="本地优先的个人想法工作台",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    workspace_app.state.content_root = content_root or REPO_ROOT / "content"
    workspace_app.state.llm_client = llm_client or OpenAICompatibleClient()
    workspace_app.mount(
        "/static",
        StaticFiles(directory=APP_DIR / "static"),
        name="static",
    )

    @workspace_app.get("/", response_class=HTMLResponse, name="workspace")
    async def workspace(
        request: Request,
        saved: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="workspace.html",
            context=_workspace_context(request, saved=saved),
        )

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
                ),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("workspace").include_query_params(saved="created"),
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
        item = _collection(request).get(item_id)
        if item is None:
            return _not_found(request, "ideas")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="idea_detail.html",
            context={"active_page": "ideas", **_item_context(item)},
        )

    @workspace_app.post("/ideas/{item_id}", name="update_idea")
    async def update_idea(
        request: Request,
        item_id: str,
        body: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
    ) -> HTMLResponse:
        try:
            item = update_item(
                request.app.state.content_root,
                item_id,
                body=body,
                title=title,
                tags=tags,
                category=category,
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
                    **_item_context(current),
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

    @workspace_app.post("/ideas/{item_id}/status", name="change_idea_status")
    async def change_idea_status(
        request: Request,
        item_id: str,
        status: str = Form(...),
    ) -> HTMLResponse:
        try:
            item = set_item_status(request.app.state.content_root, item_id, status)
        except KeyError:
            return _not_found(request, "ideas")
        except ValueError:
            return _not_found(request, "ideas")
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
    async def generate_review(request: Request) -> HTMLResponse:
        client = request.app.state.llm_client
        summarizer = client.summarize if client.enabled else None
        try:
            _, created, used_ai = await asyncio.to_thread(
                save_weekly_review,
                request.app.state.content_root,
                summarizer=summarizer,
            )
        except ValueError as error:
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
        return RedirectResponse(
            request.url_for("reviews").include_query_params(saved=saved),
            status_code=303,
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
        if item is None or resolve_publishing_source(
            request.app.state.content_root,
            item_id,
        ) is None:
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
        try:
            candidate = await asyncio.to_thread(
                client.polish,
                title=item.title,
                body=item.body,
                mode=mode,
            )
        except (RuntimeError, ValueError, httpx.HTTPError) as error:
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
            create_item(
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
            request.url_for("workspace").include_query_params(saved="article"),
            status_code=303,
        )

    @workspace_app.get("/garden", response_class=HTMLResponse, name="garden")
    async def garden(request: Request) -> HTMLResponse:
        collection = _collection(request)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="garden.html",
            context={
                "active_page": "garden",
                "items": collection.published,
            },
        )

    @workspace_app.get(
        "/garden/{item_id}",
        response_class=HTMLResponse,
        name="garden_detail",
    )
    async def garden_detail(request: Request, item_id: str) -> HTMLResponse:
        item = next(
            (item for item in _collection(request).published if item.id == item_id),
            None,
        )
        if item is None:
            return _not_found(request, "garden")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="garden_detail.html",
            context={
                "active_page": "garden",
                "item": item,
                "item_html": render_markdown(item.body),
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
            "deleted": "内容已永久删除，仍可从 Git 历史恢复。",
        }
        return TEMPLATES.TemplateResponse(
            request=request,
            name="trash.html",
            context={
                "active_page": "settings",
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
                    "active_page": "settings",
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
                "content_root": request.app.state.content_root,
                "llm_enabled": client.enabled,
                "llm_model": getattr(config, "model", "") if config else "",
                "llm_base_url": getattr(config, "base_url", "") if config else "",
            },
        )

    @workspace_app.exception_handler(404)
    async def not_found(request: Request, _error: Exception) -> HTMLResponse:
        return _not_found(request)

    return workspace_app


app = create_app()
