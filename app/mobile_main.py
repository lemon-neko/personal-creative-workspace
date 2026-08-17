"""Dedicated Tailnet-only FastAPI application for the Android capture PWA."""

from __future__ import annotations

import hmac
import os
import ipaddress
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
    MobileCaptureService,
    MobileSession,
    MobileStore,
    OfflineCapture,
    manifest_payload,
)
from app.mobile_knowledge import (
    CARD_STATUS_LABELS,
    CARD_TYPE_LABELS,
    active_cards,
    cards_for_map,
    child_maps,
    latest_knowledge_update,
    relation_projections,
    render_mobile_markdown,
    source_summaries,
)
from app.knowledge_store import load_knowledge_store
from app.privacy import default_data_root, prepare_private_root


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
    service = MobileCaptureService(resolved_data_root, resolved_content_root, store)
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
        session = _session(request)
        pair_csrf = request.cookies.get(PAIR_CSRF_COOKIE, "") or secrets.token_urlsafe(
            32
        )
        response = MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "paired": session is not None,
                "pair_csrf": pair_csrf,
                "active_page": "capture",
            },
        )
        if session is None:
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

    @mobile_app.get("/offline", response_class=HTMLResponse)
    async def offline(request: Request) -> HTMLResponse:
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="offline.html",
            context={"paired": False, "active_page": "capture"},
        )

    def paired_or_redirect(request: Request) -> MobileSession | RedirectResponse:
        session = _session(request)
        if session is None:
            return RedirectResponse("/", status_code=303)
        return session

    def knowledge_not_found(request: Request) -> HTMLResponse:
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge_404.html",
            context={"paired": True, "active_page": "knowledge"},
            status_code=404,
        )

    @mobile_app.get("/knowledge", response_class=HTMLResponse)
    async def mobile_knowledge(request: Request) -> Response:
        if isinstance(paired_or_redirect(request), RedirectResponse):
            return RedirectResponse("/", status_code=303)
        knowledge = load_knowledge_store(resolved_content_root)
        cards = active_cards(knowledge)
        subjects = tuple(item for item in knowledge.maps if item.kind == "subject")
        topics = tuple(item for item in knowledge.maps if item.kind == "topic")
        subject_rows = tuple(
            {
                "map": item,
                "children": child_maps(knowledge, item.id),
                "card_count": len(cards_for_map(knowledge, item)),
            }
            for item in subjects
        )
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge.html",
            context={
                "paired": True,
                "active_page": "knowledge",
                "subjects": subject_rows,
                "topics": topics,
                "cards": cards,
                "recent_cards": cards[:12],
                "latest_update": latest_knowledge_update(knowledge),
                "diagnostic_count": len(knowledge.diagnostics),
                "card_type_labels": CARD_TYPE_LABELS,
            },
        )

    @mobile_app.get("/knowledge/maps/{map_id}", response_class=HTMLResponse)
    async def mobile_knowledge_map(request: Request, map_id: str) -> Response:
        if isinstance(paired_or_redirect(request), RedirectResponse):
            return RedirectResponse("/", status_code=303)
        knowledge = load_knowledge_store(resolved_content_root)
        item = knowledge.map(map_id)
        if item is None:
            return knowledge_not_found(request)
        maps = {candidate.id: candidate for candidate in knowledge.maps}
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge_map.html",
            context={
                "paired": True,
                "active_page": "knowledge",
                "item": item,
                "parents": tuple(
                    maps[parent_id]
                    for parent_id in item.parent_ids
                    if parent_id in maps
                ),
                "children": child_maps(knowledge, item.id),
                "cards": cards_for_map(knowledge, item),
                "body_html": render_mobile_markdown(
                    item.body,
                    source=item.source,
                    content_root=resolved_content_root,
                    store=knowledge,
                )
                if item.body
                else "",
                "card_type_labels": CARD_TYPE_LABELS,
            },
        )

    @mobile_app.get("/knowledge/cards/{card_id}", response_class=HTMLResponse)
    async def mobile_knowledge_card(request: Request, card_id: str) -> Response:
        if isinstance(paired_or_redirect(request), RedirectResponse):
            return RedirectResponse("/", status_code=303)
        knowledge = load_knowledge_store(resolved_content_root)
        card = knowledge.card(card_id)
        if card is None:
            return knowledge_not_found(request)
        maps = {item.id: item for item in knowledge.maps}
        replacement = knowledge.card(card.superseded_by) if card.superseded_by else None
        return MOBILE_TEMPLATES.TemplateResponse(
            request=request,
            name="knowledge_card.html",
            context={
                "paired": True,
                "active_page": "knowledge",
                "card": card,
                "body_html": render_mobile_markdown(
                    card.body,
                    source=card.source,
                    content_root=resolved_content_root,
                    store=knowledge,
                ),
                "maps": tuple(
                    maps[map_id] for map_id in card.map_ids if map_id in maps
                ),
                "sources": source_summaries(resolved_content_root, card),
                "relations": relation_projections(
                    resolved_content_root, knowledge, card
                ),
                "replacement": replacement,
                "card_type_labels": CARD_TYPE_LABELS,
                "card_status_labels": CARD_STATUS_LABELS,
            },
        )

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
