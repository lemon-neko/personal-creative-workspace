"""Dedicated Tailnet-only FastAPI application for the Android capture PWA."""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.mobile import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    MAX_TOTAL_IMAGE_BYTES,
    MOBILE_SESSION_COOKIE,
    IdeaEditConflict,
    MobileCaptureService,
    MobileSession,
    MobileStore,
    OfflineCapture,
    manifest_payload,
)
from app.mobile_daily import daily_now, read_daily_snapshot
from app.privacy import default_data_root, prepare_private_root
from app.search import SearchRepository


APP_DIR = Path(__file__).resolve().parent
MOBILE_TEMPLATES = Jinja2Templates(directory=APP_DIR / "mobile_templates")
PAIR_CSRF_COOKIE = "pcw_mobile_pair_csrf"


def _is_same_tailnet_origin(origin: str, tailnet_host: str) -> bool:
    """Accept the configured HTTPS origin with an implicit or explicit port 443."""

    try:
        parsed = urlparse(origin)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold().rstrip(".") == tailnet_host
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
    )


class MobileSecurityMiddleware(BaseHTTPMiddleware):
    """Accept only a configured Tailscale Serve proxy on the local loopback."""

    def __init__(self, app, *, store: MobileStore, enforce: bool = True) -> None:
        super().__init__(app)
        self.store = store
        self.enforce = enforce

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self.enforce:
            config = self.store.config()
            host = request.headers.get("host", "").lower().split(":", 1)[0].rstrip(".")
            client = request.client.host if request.client else ""
            if not config.enabled:
                return Response("手机同步尚未启用", status_code=503)
            if not config.tailnet_host or host != config.tailnet_host:
                return Response("拒绝异常 Host", status_code=403)
            if client not in {"127.0.0.1", "::1"}:
                return Response("移动网关只接受本机私网代理", status_code=403)
            forwarded_for = request.headers.get("x-forwarded-for", "")
            try:
                forwarded_ip = ipaddress.ip_address(forwarded_for)
                is_tailnet = forwarded_ip in ipaddress.ip_network(
                    "100.64.0.0/10"
                ) or forwarded_ip in ipaddress.ip_network("fd7a:115c:a1e0::/48")
            except ValueError:
                is_tailnet = False
            if not is_tailnet:
                return Response("拒绝非 Tailnet 客户端", status_code=403)
            if request.headers.get("x-forwarded-proto", "").lower() != "https":
                return Response("移动网关要求 Tailscale HTTPS", status_code=403)
            forwarded_host = request.headers.get("x-forwarded-host", "")
            normalized_forwarded_host = (
                forwarded_host.lower().rstrip(".").removesuffix(":443")
            )
            if forwarded_host and normalized_forwarded_host != config.tailnet_host:
                return Response("拒绝异常代理主机", status_code=403)
            if any(name in request.headers for name in ("forwarded", "x-real-ip")):
                return Response("拒绝异常代理头", status_code=403)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = (
                    request.headers.get("origin")
                    or request.headers.get("referer")
                    or ""
                )
                if (
                    not _is_same_tailnet_origin(origin, config.tailnet_host)
                    and request.url.path != "/pair"
                ):
                    return Response("拒绝跨站请求", status_code=403)

        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        return response


def _session(request: Request) -> MobileSession | None:
    return request.app.state.mobile_store.authenticate(
        request.cookies.get(MOBILE_SESSION_COOKIE, "")
    )


def _require_session(request: Request) -> MobileSession:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="设备尚未配对或会话已失效")
    return session


def _require_mobile_csrf(request: Request, session: MobileSession) -> None:
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


def create_mobile_app(
    *,
    data_root: Path | None = None,
    content_root: Path | None = None,
    enforce_security: bool = True,
) -> FastAPI:
    resolved_data_root = (data_root or default_data_root()).expanduser().resolve()
    prepare_private_root(resolved_data_root)
    resolved_content_root = (content_root or resolved_data_root / "content").resolve()
    store = MobileStore(resolved_data_root)
    service = MobileCaptureService(
        resolved_data_root,
        resolved_content_root,
        store,
        SearchRepository(resolved_data_root),
    )
    mobile_app = FastAPI(
        title="羽白工作台",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    mobile_app.state.data_root = resolved_data_root
    mobile_app.state.content_root = resolved_content_root
    mobile_app.state.mobile_store = store
    mobile_app.state.mobile_service = service
    mobile_app.add_middleware(
        MobileSecurityMiddleware, store=store, enforce=enforce_security
    )
    mobile_app.mount(
        "/mobile-assets",
        StaticFiles(directory=APP_DIR / "mobile_static"),
        name="mobile_assets",
    )

    @mobile_app.get("/", response_class=HTMLResponse)
    async def mobile_home(request: Request) -> HTMLResponse:
        if _session(request) is not None:
            now = daily_now()
            snapshot = read_daily_snapshot(resolved_data_root, now.date())
            return MOBILE_TEMPLATES.TemplateResponse(
                request=request, name="daily.html",
                context={"paired": True, "active_page": "daily", "snapshot": snapshot, "today": now.date()},
            )
        pair_csrf = request.cookies.get(PAIR_CSRF_COOKIE, "") or secrets.token_urlsafe(
            32
        )
        response = MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "paired": False,
                "pair_csrf": pair_csrf,
                "active_page": "capture",
            },
        )
        response.set_cookie(
            PAIR_CSRF_COOKIE,
            pair_csrf,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=10 * 60,
            path="/pair",
        )
        return response

    @mobile_app.get("/capture", response_class=HTMLResponse)
    async def mobile_capture(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/", status_code=303)
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request, name="index.html", context={"paired": True, "active_page": "capture"},
        )

    @mobile_app.get("/offline", response_class=HTMLResponse)
    async def offline(request: Request) -> HTMLResponse:
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="offline.html",
            context={"paired": True, "active_page": "capture"},
        )

    def paired_or_redirect(request: Request) -> MobileSession | RedirectResponse:
        session = _session(request)
        if session is None:
            return RedirectResponse("/", status_code=303)
        return session

    def idea_snapshot_payload(item) -> dict[str, object]:
        return {
            "id": item.id,
            "title": item.title,
            "body": item.body,
            "summary": item.summary,
            "tags": list(item.tags),
            "category": item.category,
            "status": item.status,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "revision": item.revision,
        }

    def idea_page(
        request: Request, item_id: str = "", *, edit_shell: bool = False
    ) -> Response:
        if isinstance(paired_or_redirect(request), RedirectResponse):
            return RedirectResponse("/", status_code=303)
        if (
            item_id
            and not item_id.startswith("local--")
            and service.idea(item_id) is None
        ):
            return MOBILE_TEMPLATES.TemplateResponse(
                request=request,
                name="idea_404.html",
                context={"paired": True, "active_page": "capture"},
                status_code=404,
            )
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="idea_edit.html" if item_id or edit_shell else "ideas.html",
            context={
                "paired": True,
                "active_page": "capture",
                "idea_id": item_id,
            },
        )

    @mobile_app.get("/ideas", response_class=HTMLResponse)
    async def mobile_ideas(request: Request) -> Response:
        return idea_page(request)

    @mobile_app.get("/ideas/_shell", response_class=HTMLResponse)
    async def mobile_idea_offline_shell(request: Request) -> Response:
        return idea_page(request, "", edit_shell=True)

    @mobile_app.get("/ideas/{item_id}", response_class=HTMLResponse)
    async def mobile_idea_detail(request: Request, item_id: str) -> Response:
        return idea_page(request, item_id)

    @mobile_app.get("/manifest.webmanifest")
    async def manifest() -> Response:
        return Response(manifest_payload(), media_type="application/manifest+json")

    @mobile_app.get("/service-worker.js")
    async def service_worker() -> Response:
        path = APP_DIR / "mobile_static" / "service-worker.js"
        return Response(
            path.read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    @mobile_app.post("/pair")
    async def pair_device(
        request: Request,
        code: str = Form(...),
        device_name: str = Form(default="Android 设备"),
        csrf_token: str = Form(...),
    ) -> Response:
        expected_csrf = request.cookies.get(PAIR_CSRF_COOKIE, "")
        if (
            not expected_csrf
            or not csrf_token
            or not hmac.compare_digest(expected_csrf, csrf_token)
        ):
            return Response("配对请求校验失败，请刷新页面重试", status_code=403)
        try:
            _, token = store.pair(code, device_name)
        except (PermissionError, ValueError) as error:
            return MOBILE_TEMPLATES.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "paired": False,
                    "error": str(error),
                    "pair_csrf": csrf_token,
                },
                status_code=422,
            )
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(PAIR_CSRF_COOKIE, path="/pair")
        response.set_cookie(
            MOBILE_SESSION_COOKIE,
            token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=180 * 24 * 60 * 60,
            path="/",
        )
        return response

    @mobile_app.get("/api/session")
    async def session_info(request: Request) -> JSONResponse:
        session = _require_session(request)
        return JSONResponse(
            {
                "paired": True,
                "csrf_token": session.csrf_token,
                "max_images": MAX_IMAGES,
                "max_image_bytes": MAX_IMAGE_BYTES,
                "max_total_image_bytes": MAX_TOTAL_IMAGE_BYTES,
            }
        )

    @mobile_app.get("/api/recent")
    async def recent(request: Request) -> JSONResponse:
        _require_session(request)
        items = service.recent()
        return JSONResponse(
            {
                "items": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "summary": item.summary,
                        "created_at": item.created_at.isoformat(),
                        "tags": list(item.tags),
                        "category": item.category,
                    }
                    for item in items
                ]
            }
        )

    @mobile_app.get("/api/ideas/snapshot")
    async def ideas_snapshot(request: Request) -> JSONResponse:
        _require_session(request)
        return JSONResponse({"items": [idea_snapshot_payload(item) for item in service.ideas()]})

    async def read_images(images: list[UploadFile]) -> list[bytes]:
        if len(images) > MAX_IMAGES:
            raise HTTPException(status_code=422, detail="图片数量超过限制")
        payloads: list[bytes] = []
        total = 0
        for upload in images:
            data = await upload.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="单张图片超过 10 MB")
            total += len(data)
            if total > MAX_TOTAL_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="图片总大小超过 25 MB")
            payloads.append(data)
        return payloads

    async def save_mobile_idea(
        request: Request,
        item_id: str,
        operation_key: str,
        expected_revision: str,
        body: str,
        title: str,
        tags: str,
        category: str,
        images: list[UploadFile],
    ) -> JSONResponse:
        session = _require_session(request)
        _require_mobile_csrf(request, session)
        payloads = await read_images(images)
        try:
            receipt = service.update_idea(
                item_id,
                operation_key=operation_key,
                expected_revision=expected_revision,
                body=body,
                title=title,
                tags=tags,
                category=category,
                images=payloads,
            )
        except IdeaEditConflict as error:
            return JSONResponse(
                {
                    "detail": str(error),
                    "current": idea_snapshot_payload(error.current),
                },
                status_code=409,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="随想不存在或已归档") from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        current = service.idea(item_id)
        if current is None:
            raise HTTPException(status_code=404, detail="随想不存在或已归档")
        return JSONResponse(
            {
                "operation_key": receipt.operation_key,
                "content_id": receipt.content_id,
                "revision": receipt.revision,
                "applied": receipt.applied,
                "image_count": receipt.image_count,
                "item": idea_snapshot_payload(current),
            }
        )

    @mobile_app.post("/api/ideas/{item_id}")
    async def update_mobile_idea(
        request: Request,
        item_id: str,
        operation_key: str = Form(...),
        expected_revision: str = Form(...),
        body: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
        images: list[UploadFile] = File(default=[]),
    ) -> JSONResponse:
        return await save_mobile_idea(
            request,
            item_id,
            operation_key,
            expected_revision,
            body,
            title,
            tags,
            category,
            images,
        )

    @mobile_app.post("/api/ideas/{item_id}/resolve")
    async def resolve_mobile_idea(
        request: Request,
        item_id: str,
        operation_key: str = Form(...),
        expected_revision: str = Form(...),
        body: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
        images: list[UploadFile] = File(default=[]),
    ) -> JSONResponse:
        return await save_mobile_idea(
            request,
            item_id,
            operation_key,
            expected_revision,
            body,
            title,
            tags,
            category,
            images,
        )

    @mobile_app.post("/api/captures")
    async def create_capture(
        request: Request,
        idempotency_key: str = Form(...),
        body: str = Form(...),
        title: str = Form(default=""),
        tags: str = Form(default=""),
        category: str = Form(default=""),
        created_at: str = Form(default=""),
        images: list[UploadFile] = File(default=[]),
    ) -> JSONResponse:
        session = _require_session(request)
        _require_mobile_csrf(request, session)
        payloads = await read_images(images)
        try:
            normalized_time = (
                f"{created_at[:-1]}+00:00" if created_at.endswith("Z") else created_at
            )
            captured_at = (
                datetime.fromisoformat(normalized_time) if normalized_time else None
            )
            receipt = service.create_capture(
                OfflineCapture(
                    idempotency_key, body, title, tags, category, captured_at
                ),
                payloads,
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(
            {
                "content_id": receipt.content_id,
                "created": receipt.created,
                "image_count": receipt.image_count,
            },
            status_code=201 if receipt.created else 200,
        )

    @mobile_app.post("/api/session/revoke")
    async def revoke_session(request: Request) -> JSONResponse:
        session = _require_session(request)
        _require_mobile_csrf(request, session)
        store.revoke_session(session.id)
        response = JSONResponse({"revoked": True})
        response.delete_cookie(MOBILE_SESSION_COOKIE, path="/")
        return response

    return mobile_app


def main() -> None:
    os.umask(0o077)
    uvicorn.run(
        "app.mobile_asgi:app",
        host="127.0.0.1",
        port=8766,
        reload=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
