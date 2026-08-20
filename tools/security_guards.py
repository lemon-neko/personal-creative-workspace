"""Fail CI when private data or unsafe deployment defaults enter Git."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_PATTERNS = (
    "content/items/",
    "content/trash/",
    "content/knowledge/",
    "content/sources/",
    "content/outputs/",
    "content/archive/",
    "content/assets/",
    "content/legacy-items-",
    "private_data/",
    "documents/",
    "video-projects/",
    "working/",
    "backups/",
    "app/static/images/",
    "workspace.db",
    "mobile.db",
    "mobile.secret",
)
SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".canvas",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".aes",
}
DEPLOYMENT_FILES = {
    "vercel.json",
    "render.yaml",
    "railway.json",
    "fly.toml",
    "Procfile",
}


def tracked_files() -> tuple[str, ...]:
    output = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
    )
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def violations(files: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for name in files:
        path = Path(name)
        if any(name.startswith(prefix) for prefix in PRIVATE_PATTERNS):
            found.append(f"私有数据被 Git 跟踪：{name}")
        if path.name == ".env" or path.suffix.lower() in SENSITIVE_SUFFIXES:
            found.append(f"敏感或私有文件被 Git 跟踪：{name}")
        if path.name in DEPLOYMENT_FILES:
            found.append(f"本地专用项目不应包含公网部署配置：{name}")
    return tuple(found)


def main() -> None:
    problems = violations(tracked_files())
    if problems:
        raise SystemExit("\n".join(problems))
    print("security guard passed: no private data or deployment config is tracked")


if __name__ == "__main__":
    main()
