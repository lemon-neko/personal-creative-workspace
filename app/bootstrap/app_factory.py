from __future__ import annotations

from functools import partial
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.bootstrap.config import WorkspaceAppConfig
from app.bootstrap.container import AppContainer, build_container
from app.bootstrap.dependencies import WorkspaceState, get_container
from app.bootstrap.lifespan import refresh_search_index, workspace_lifespan
from app.llm import StyleClient
from app.bootstrap.routes import register_plugins
from app.privacy import LocalOnlyMiddleware, require_csrf
from app.web import APP_DIR, SafeStaticFiles, not_found as render_not_found


def create_workspace_app(
    content_root: Path | None = None,
    *,
    data_root: Path | None = None,
    enable_scheduler: bool = True,
    llm_client: StyleClient | None = None,
    enforce_security: bool | None = None,
) -> FastAPI:
    """Create the local-first workspace, optionally isolated for tests."""

    config = WorkspaceAppConfig.resolve(
        content_root,
        data_root=data_root,
        enable_scheduler=enable_scheduler,
        enforce_security=enforce_security,
    )
    container = build_container(config, llm_client=llm_client)
    application = FastAPI(
        title="羽白工作台",
        description="本地优先的个人想法工作台",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=partial(workspace_lifespan, enable_scheduler=config.enable_scheduler),
        dependencies=[Depends(require_csrf)],
    )
    application.state = WorkspaceState({
        "container": container,
        "enforce_security": config.enforce_security,
        "plugin_runtime": None,
        "search_sync_error": "",
    })
    application.add_middleware(LocalOnlyMiddleware, enforce=config.enforce_security)

    @application.middleware("http")
    async def update_search_after_write(request: Request, call_next):
        response = await call_next(request)
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and response.status_code < 400
            and request.url.path != "/settings/search/rebuild"
            and not request.url.path.startswith(("/workflow/", "/settings/runtime/plugins/"))
        ):
            await refresh_search_index(request.app)
        return response

    application.mount("/static", SafeStaticFiles(directory=APP_DIR / "static"), name="static")

    @application.get("/assets/{asset_name}", name="private_asset")
    async def private_asset(
        request: Request,
        asset_name: str,
        container: AppContainer = Depends(get_container),
    ) -> FileResponse:
        if Path(asset_name).name != asset_name or Path(asset_name).suffix.lower() not in {
            ".png", ".jpg", ".jpeg", ".webp",
        }:
            return render_not_found(request)  # type: ignore[return-value]
        path = container.content_root / "assets" / asset_name
        if not path.is_file():
            return render_not_found(request)  # type: ignore[return-value]
        return FileResponse(path)

    register_plugins(application)

    @application.exception_handler(404)
    async def not_found(request: Request, _error: Exception) -> HTMLResponse:
        return render_not_found(request)

    return application
