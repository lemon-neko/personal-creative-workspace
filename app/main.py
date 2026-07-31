"""FastAPI application for the personal learning portfolio."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.content import (
    ContentCollection,
    StudyNote,
    load_markdown,
    load_notes,
    render_markdown,
)
from app.publishing import WECHAT_RENDERER, resolve_publishing_source
from app.workspace import (
    FRAGMENT_TAG,
    SUMMARY_TOPIC,
    WEEKDAYS,
    current_week_notes,
    load_workspace_settings,
    next_summary_run,
    run_summary_scheduler,
    save_fragment,
    save_weekly_summary,
    save_workspace_settings,
)


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
TEMPLATES = Jinja2Templates(directory=APP_DIR / "templates")


def _content(request: Request) -> ContentCollection:
    return load_notes(request.app.state.content_root / "notes")


def _published_note(collection: ContentCollection, note_id: str) -> StudyNote | None:
    return next((note for note in collection.published if note.id == note_id), None)


def _filter_context(
    collection: ContentCollection,
    *,
    tag: str | None,
    topic: str | None,
) -> dict:
    published = collection.published
    tags = sorted({note_tag for note in published for note_tag in note.tags})
    topics = sorted({note.topic for note in published})
    return {
        "notes": collection.filter(tag=tag, topic=topic),
        "tags": tags,
        "topics": topics,
        "selected_tag": tag or "",
        "selected_topic": topic or "",
    }


def _workspace_context(
    request: Request,
    *,
    saved: str | None = None,
    error: str | None = None,
    form_data: dict | None = None,
) -> dict:
    collection = _content(request)
    settings = load_workspace_settings(request.app.state.content_root)
    next_run = next_summary_run(settings)
    fragments = tuple(
        note for note in collection.notes if FRAGMENT_TAG in note.tags
    )
    summaries = tuple(
        note for note in collection.notes if note.topic == SUMMARY_TOPIC
    )
    notices = {
        "fragment": "碎片已保存为 Markdown 草稿。",
        "summary": "本周汇总草稿已生成。",
        "existing": "本周汇总已经存在，没有重复生成。",
        "schedule": "定时汇总设置已保存。",
    }
    latest_summary = summaries[0] if summaries else None
    return {
        "active_page": "workspace",
        "diagnostics": collection.diagnostics,
        "fragments": fragments[:8],
        "week_notes": current_week_notes(request.app.state.content_root),
        "latest_summary": latest_summary,
        "latest_summary_html": (
            render_markdown(latest_summary.body) if latest_summary else ""
        ),
        "settings": settings,
        "weekdays": WEEKDAYS,
        "next_run": next_run,
        "notice": notices.get(saved or ""),
        "error": error,
        "form_data": form_data or {},
    }


def create_app(
    content_root: Path | None = None,
    *,
    enable_scheduler: bool = True,
) -> FastAPI:
    """Create an app, optionally pointing tests at an isolated content directory."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        task = None
        if enable_scheduler:
            task = asyncio.create_task(
                run_summary_scheduler(application.state.content_root),
            )
        yield
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    portfolio = FastAPI(
        title="羽白学习手记",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    portfolio.state.content_root = content_root or REPO_ROOT / "content"
    portfolio.mount(
        "/static",
        StaticFiles(directory=APP_DIR / "static"),
        name="static",
    )

    @portfolio.get("/", response_class=HTMLResponse, name="home")
    async def home(request: Request) -> HTMLResponse:
        collection = _content(request)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "active_page": "home",
                "recent_notes": collection.published[:3],
                "diagnostics": collection.diagnostics,
            },
        )

    @portfolio.get("/notes", response_class=HTMLResponse, name="notes")
    async def notes(
        request: Request,
        tag: Optional[str] = Query(default=None),
        topic: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        collection = _content(request)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="notes.html",
            context={
                "active_page": "notes",
                "diagnostics": collection.diagnostics,
                **_filter_context(collection, tag=tag, topic=topic),
            },
        )

    @portfolio.get(
        "/partials/notes",
        response_class=HTMLResponse,
        name="notes_partial",
    )
    async def notes_partial(
        request: Request,
        tag: Optional[str] = Query(default=None),
        topic: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        collection = _content(request)
        response = TEMPLATES.TemplateResponse(
            request=request,
            name="partials/note_list.html",
            context=_filter_context(collection, tag=tag, topic=topic),
        )
        query = request.url.query
        response.headers["HX-Push-Url"] = f"/notes{f'?{query}' if query else ''}"
        return response

    @portfolio.get("/workspace", response_class=HTMLResponse, name="workspace")
    async def workspace(
        request: Request,
        saved: Optional[str] = Query(default=None),
    ) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="workspace.html",
            context=_workspace_context(request, saved=saved),
        )

    @portfolio.post("/workspace/fragments", name="save_fragment")
    async def capture_fragment(
        request: Request,
        title: str = Form(...),
        body: str = Form(...),
        tags: str = Form(default=""),
        topic: str = Form(default="inbox"),
    ) -> HTMLResponse:
        try:
            save_fragment(
                request.app.state.content_root,
                title=title,
                body=body,
                tags=tags,
                topic=topic,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="workspace.html",
                context=_workspace_context(
                    request,
                    error=str(error),
                    form_data={
                        "title": title,
                        "body": body,
                        "tags": tags,
                        "topic": topic,
                    },
                ),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("workspace").include_query_params(saved="fragment"),
            status_code=303,
        )

    @portfolio.post("/workspace/summary", name="generate_summary")
    async def generate_summary(request: Request) -> HTMLResponse:
        try:
            _, created = save_weekly_summary(request.app.state.content_root)
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="workspace.html",
                context=_workspace_context(request, error=str(error)),
                status_code=422,
            )
        saved = "summary" if created else "existing"
        return RedirectResponse(
            request.url_for("workspace").include_query_params(saved=saved),
            status_code=303,
        )

    @portfolio.post("/workspace/schedule", name="save_schedule")
    async def update_schedule(
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
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="workspace.html",
                context=_workspace_context(request, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            request.url_for("workspace").include_query_params(saved="schedule"),
            status_code=303,
        )

    @portfolio.get(
        "/workspace/publish/{source_type}/{source_id}",
        response_class=HTMLResponse,
        name="publish_source",
    )
    async def publish_source(
        request: Request,
        source_type: str,
        source_id: str,
    ) -> HTMLResponse:
        source = resolve_publishing_source(
            request.app.state.content_root,
            source_type,
            source_id,
        )
        if source is None:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="404.html",
                context={"active_page": "workspace"},
                status_code=404,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context={
                "active_page": "workspace",
                "source": source,
                "rendered": WECHAT_RENDERER.render(source),
            },
        )

    @portfolio.get(
        "/notes/{note_id}",
        response_class=HTMLResponse,
        name="note_detail",
    )
    async def note_detail(request: Request, note_id: str) -> HTMLResponse:
        collection = _content(request)
        note = _published_note(collection, note_id)
        if note is None:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="404.html",
                context={"active_page": "notes"},
                status_code=404,
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="note_detail.html",
            context={
                "active_page": "notes",
                "note": note,
                "note_html": render_markdown(note.body),
            },
        )

    @portfolio.get(
        "/topics/transformer",
        response_class=HTMLResponse,
        name="transformer_topic",
    )
    async def transformer_topic(request: Request) -> HTMLResponse:
        topic_path = request.app.state.content_root / "topics" / "transformer.md"
        return TEMPLATES.TemplateResponse(
            request=request,
            name="topic.html",
            context={
                "active_page": "topics",
                "topic_html": render_markdown(load_markdown(topic_path)),
            },
        )

    @portfolio.get("/about", response_class=HTMLResponse, name="about")
    async def about(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="about.html",
            context={"active_page": "about"},
        )

    @portfolio.exception_handler(404)
    async def not_found(request: Request, _error: Exception) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="404.html",
            context={"active_page": ""},
            status_code=404,
        )

    return portfolio


app = create_app()
