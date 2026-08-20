"""Local-only runtime configuration and request protections."""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


APP_DATA_FOLDER = "personal-creative-workspace"
CSRF_COOKIE = "pcw_csrf"
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "testserver"}
LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "testclient"}
FORWARDED_HEADERS = {
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
}
LOCAL_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def _is_trusted_local_origin(value: str) -> bool:
    """Accept local web origins and Chrome's opaque ``null`` origin.

    An opaque origin cannot read the HttpOnly CSRF cookie or the token embedded
    in a workspace page. It is therefore safe to accept only after the request
    has already passed the local-only middleware and double-submit token check.
    Explicit non-local web origins remain blocked.
    """

    if value == "null":
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in LOCAL_ORIGIN_HOSTS


def default_data_root() -> Path:
    """Return the private macOS application data directory."""

    configured = os.getenv("WORKSPACE_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / APP_DATA_FOLDER
    )


def prepare_private_root(root: Path) -> Path:
    """Create private runtime directories without relaxing existing permissions."""

    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    for relative in (
        "content",
        "content/sources",
        "content/sources/inbox",
        "content/sources/thoughts",
        "content/sources/materials",
        "content/knowledge/cards",
        "content/knowledge/maps",
        "content/knowledge/indexes",
        "content/knowledge/indexes/obsidian",
        "content/outputs/articles",
        "content/outputs/reviews",
        "content/archive",
        "content/trash",
        "content/assets",
        "documents",
        "video-projects",
        "working",
        "working/model-tasks",
    ):
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    return root


def csrf_token(request: Request) -> str:
    """Expose the double-submit token to Jinja templates."""

    return getattr(request.state, "csrf_token", request.cookies.get(CSRF_COOKIE, ""))


async def require_csrf(request: Request) -> None:
    """Reject state-changing requests without a same-origin CSRF token."""

    if not getattr(request.app.state, "enforce_security", True):
        return
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    expected = request.cookies.get(CSRF_COOKIE, "")
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied:
        form = await request.form()
        supplied = str(form.get("csrf_token", ""))
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")

    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and not _is_trusted_local_origin(origin):
        raise HTTPException(status_code=403, detail="拒绝跨站请求")


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    """Fail closed when the app is reached through a network or proxy."""

    def __init__(self, app, *, enforce: bool = True) -> None:
        super().__init__(app)
        self.enforce = enforce

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if self.enforce:
            raw_host = request.headers.get("host", "").lower()
            host = (
                raw_host[: raw_host.find("]") + 1]
                if raw_host.startswith("[") and "]" in raw_host
                else raw_host.rsplit(":", 1)[0]
            )
            if host not in ALLOWED_HOSTS:
                return Response("仅允许从本机访问", status_code=403)
            client_host = request.client.host if request.client else ""
            if client_host not in LOOPBACK_CLIENTS:
                return Response("仅允许本机客户端访问", status_code=403)
            if any(header in request.headers for header in FORWARDED_HEADERS):
                return Response("本地模式拒绝代理转发请求", status_code=403)

        existing_token = request.cookies.get(CSRF_COOKIE, "")
        request.state.csrf_token = existing_token or secrets.token_urlsafe(32)
        response = await call_next(request)
        if not existing_token:
            response.set_cookie(
                CSRF_COOKIE,
                request.state.csrf_token,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        return response
