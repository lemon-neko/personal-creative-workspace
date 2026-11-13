"""Serve only the packaged Super Productivity assets on a separate origin."""

import os
import re
import sys
from pathlib import Path

import uvicorn
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from app.daily_plugin import CHALLENGE, HEALTH_ENV, PROOF, health_proof
from app.plugin_paths import DAILY_PORT, LOOPBACK, WORKBENCH_ORIGIN
from app.privacy import FORWARDED_HEADERS


def web_app(directory: Path, *, health_secret: str = ""):
    static = ExceptionMiddleware(StaticFiles(directory=directory, html=True))
    csp = (
        "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
        "connect-src 'self'; worker-src 'self' blob:; media-src 'self' blob: data:; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; "
        f"frame-ancestors {WORKBENCH_ORIGIN};"
    )

    async def app(scope, receive, send):
        headers = dict(scope["headers"])
        if (
            headers.get(b"host") != f"localhost:{DAILY_PORT}".encode()
            or not scope.get("client") or scope["client"][0] != LOOPBACK
            or any(name.encode() in headers for name in FORWARDED_HEADERS)
        ):
            await Response(status_code=403)(scope, receive, send)
            return

        async def secured_send(message):
            if message["type"] == "http.response.start":
                challenge = headers.get(CHALLENGE.encode(), b"")
                if (health_secret and scope["method"] == "HEAD" and scope["path"] == "/"
                    and re.fullmatch(rb"[a-f0-9]{32}", challenge)):
                    proof = health_proof(health_secret, challenge.decode("ascii"))
                    message["headers"].append((PROOF.encode(), proof.encode()))
                message["headers"].extend([
                    (b"content-security-policy", csp.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ])
            await send(message)

        await static(scope, receive, secured_send)

    return app


if __name__ == "__main__":
    uvicorn.run(web_app(Path(sys.argv[1]), health_secret=os.getenv(HEALTH_ENV, "")), host=LOOPBACK, port=DAILY_PORT,
                proxy_headers=False, access_log=False, lifespan="off")
