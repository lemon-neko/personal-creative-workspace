"""Safe local launcher: ``python -m app``."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    os.umask(0o077)
    uvicorn.run(
        "app.asgi:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
