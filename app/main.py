"""FastAPI application for the personal learning portfolio."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.content import (
    ContentCollection,
    StudyNote,
    load_markdown,
    load_notes,
    render_markdown,
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


def create_app(content_root: Path | None = None) -> FastAPI:
    """Create an app, optionally pointing tests at an isolated content directory."""

    portfolio = FastAPI(
        title="羽白学习手记",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
