"""Shared presentation primitives for desktop routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.content import ContentCollection, load_items
from app.privacy import csrf_token
from app.video import VIDEO_PLATFORMS, VIDEO_STATUS_LABELS, VIDEO_TYPES
from app.workspace import (
    KIND_LABELS,
    STATUS_LABELS,
    items_directory,
    status_labels_for_kind,
)


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
TEMPLATES = Jinja2Templates(directory=APP_DIR / "templates")
TEMPLATES.env.globals.update(
    kind_labels=KIND_LABELS,
    status_labels=STATUS_LABELS,
    content_status_labels=status_labels_for_kind,
    video_status_labels=VIDEO_STATUS_LABELS,
    video_platform_labels=VIDEO_PLATFORMS,
    video_type_labels=VIDEO_TYPES,
    csrf_token=csrf_token,
)

WORKSPACE_VIEWS = {
    "pending": "待整理",
    "organized": "已整理",
    "all": "全部",
}
TEMPLATES.env.globals.update(workspace_view_labels=WORKSPACE_VIEWS)


class SafeStaticFiles(StaticFiles):
    """Serve application assets while blocking legacy/private article images."""

    async def get_response(self, path: str, scope) -> Response:
        if path == "images" or path.startswith("images/"):
            return Response(status_code=404)
        return await super().get_response(path, scope)


def collection(request: Request) -> ContentCollection:
    return load_items(items_directory(request.app.state.content_root))


def not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="404.html",
        context={"active_page": active_page},
        status_code=404,
    )
