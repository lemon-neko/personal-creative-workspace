"""Fixed local origins and private plugin directory."""

from pathlib import Path

LOOPBACK = "127.0.0.1"
WORKBENCH_PORT = 8765
MOBILE_PORT = 8766
DAILY_PORT = 8767
HUB_PORT = 8768
WORKBENCH_ORIGIN = f"http://{LOOPBACK}:{WORKBENCH_PORT}"
DAILY_ORIGIN = f"http://localhost:{DAILY_PORT}"
HUB_URL = f"http://{LOOPBACK}:{HUB_PORT}"


def plugin_root(data_root: Path) -> Path:
    return data_root / "working" / "plugins"
