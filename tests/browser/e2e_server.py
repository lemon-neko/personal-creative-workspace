"""Isolated ASGI applications used by Playwright acceptance tests."""

from __future__ import annotations

import os
from pathlib import Path

from app.main import create_app
from app.mobile_main import create_mobile_app


DATA_ROOT = Path(os.environ["E2E_DATA_ROOT"]).resolve()
CONTENT_ROOT = DATA_ROOT / "content"

desktop_app = create_app(
    content_root=CONTENT_ROOT,
    data_root=DATA_ROOT,
    enable_scheduler=False,
    enforce_security=False,
)
mobile_app = create_mobile_app(
    data_root=DATA_ROOT,
    content_root=CONTENT_ROOT,
    enforce_security=False,
)
