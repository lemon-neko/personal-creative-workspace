"""FastAPI application for 羽白工作台."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from app.assistant import AssistantRepository
from app.income import IncomeRepository
from app.career import CareerRepository
from app.content import (
    load_items,
)
from app.database import initialize_mobile_database, initialize_workspace_database
from app.knowledge_store import (
    load_knowledge_store,
)
from app.library import load_materials
from app.llm import OpenAICompatibleClient, StyleClient
from app.model_gateway import (
    ModelGateway,
    ModelTaskStore,
)
from app.mobile import MobileStore
from app.obsidian import ObsidianBridge
from app.routers.system import router as system_router
from app.routers.creation import router as creation_router
from app.routers.career_learning import router as career_learning_router
from app.routers.knowledge_models import router as knowledge_models_router
from app.routers.workspace_content import router as workspace_content_router
from app.routers.assistant import router as assistant_router
from app.routers.income import router as income_router
from app.routers.wechat import router as wechat_router
from app.routers.resumes import router as resumes_router
from app.privacy import (
    LocalOnlyMiddleware,
    default_data_root,
    prepare_private_root,
    require_csrf,
)
from app.search import SearchRepository
from app.video import (
    VideoProjectRepository,
)
from app.wechat import WechatPublisher
from app.web import (
    APP_DIR,
    REPO_ROOT,
    SafeStaticFiles,
    not_found as _not_found,
)
from app.workspace import (
    items_directory,
    run_summary_scheduler,
)


__all__ = ["REPO_ROOT", "create_app"]


def _search_sources(application: FastAPI) -> dict:
    return {
        "items": load_items(items_directory(application.state.content_root)).items,
        "knowledge": load_knowledge_store(application.state.content_root),
        "materials": load_materials(application.state.content_root),
        "career": application.state.career,
        "video": application.state.video,
    }


def _sync_search_index(application: FastAPI) -> dict[str, int]:
    result = application.state.search.sync(**_search_sources(application))
    application.state.search_sync_error = ""
    return result


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
        tasks = []
        try:
            await asyncio.to_thread(_sync_search_index, application)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            application.state.search_sync_error = str(error)
        if enable_scheduler:
            tasks.append(asyncio.create_task(
                run_summary_scheduler(
                    application.state.content_root,
                    summarizer=None,
                ),
            ))
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
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
    initialize_workspace_database(resolved_data_root)
    initialize_mobile_database(resolved_data_root)
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
    workspace_app.state.assistant = AssistantRepository(resolved_data_root)
    workspace_app.state.income = IncomeRepository(resolved_data_root)
    workspace_app.state.wechat = WechatPublisher(
        resolved_data_root,
        workspace_app.state.content_root,
    )
    workspace_app.state.search_sync_error = ""
    workspace_app.state.mobile_store = MobileStore(resolved_data_root)
    workspace_app.state.obsidian = ObsidianBridge(
        resolved_data_root,
        workspace_app.state.content_root,
    )
    workspace_app.state.career.seed_career_radar()
    workspace_app.add_middleware(
        LocalOnlyMiddleware,
        enforce=workspace_app.state.enforce_security,
    )

    @workspace_app.middleware("http")
    async def update_search_after_write(request: Request, call_next):
        response = await call_next(request)
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and response.status_code < 400
            and request.url.path != "/settings/search/rebuild"
        ):
            try:
                await asyncio.to_thread(_sync_search_index, request.app)
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                request.app.state.search_sync_error = str(error)
        return response
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

    workspace_app.include_router(workspace_content_router)
    workspace_app.include_router(assistant_router)
    workspace_app.include_router(income_router)
    workspace_app.include_router(knowledge_models_router)

    workspace_app.include_router(creation_router)
    workspace_app.include_router(wechat_router)
    workspace_app.include_router(resumes_router)
    workspace_app.include_router(career_learning_router)
    workspace_app.include_router(system_router)

    @workspace_app.exception_handler(404)
    async def not_found(request: Request, _error: Exception) -> HTMLResponse:
        return _not_found(request)

    return workspace_app
