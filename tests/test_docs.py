from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from app.main import create_app


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_DOCS = {
    ROOT / "README.md",
    ROOT / "PROJECT_STATUS.md",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "FEATURES.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "USER_GUIDE.md",
    ROOT / "docs" / "OPERATIONS.md",
    ROOT / "docs" / "SECURITY.md",
    ROOT / "docs" / "DEVELOPMENT.md",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
TAILNET_HOST = re.compile(r"\b[a-z0-9-]+\.tail[a-z0-9]+\.ts\.net\b", re.I)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def _documents() -> tuple[Path, ...]:
    return tuple(sorted(REQUIRED_DOCS))


def test_documentation_set_and_local_links_exist() -> None:
    assert all(path.is_file() for path in REQUIRED_DOCS)
    for document in _documents():
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "obsidian:")):
                continue
            resolved = (document.parent / unquote(target)).resolve()
            assert resolved.is_file(), f"{document.relative_to(ROOT)} 包含失效链接：{raw_target}"


def test_readme_matches_local_launch_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    launcher = (ROOT / "app" / "__main__.py").read_text(encoding="utf-8")
    mobile_launcher = (ROOT / "app" / "mobile_launcher.py").read_text(encoding="utf-8")

    assert ".venv/bin/python -m app" in readme
    assert "WORKSPACE_DATA_DIR" in readme
    assert "127.0.0.1:8765" in readme and 'host="127.0.0.1"' in launcher
    assert "127.0.0.1:8766" in readme and 'host="127.0.0.1"' in mobile_launcher


def test_documented_core_routes_exist(tmp_path: Path) -> None:
    app = create_app(content_root=tmp_path, enable_scheduler=False)
    routes = {route.path for route in app.routes}
    expected = {
        "/",
        "/ideas",
        "/knowledge",
        "/library",
        "/search",
        "/reviews",
        "/publish",
        "/video",
        "/career",
        "/learning",
        "/models",
        "/settings",
        "/settings/obsidian",
        "/settings/runtime",
        "/settings/search",
        "/settings/mobile",
        "/settings/backups",
        "/trash",
    }
    assert expected <= routes


def test_documentation_contains_no_personal_identifiers_or_secret_examples() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in _documents())
    assert "/Users/yubai/" not in combined
    assert not TAILNET_HOST.search(combined)
    assert not EMAIL.search(combined)
    assert not re.search(r"\bsk-[A-Za-z0-9_-]{12,}\b", combined)


def test_each_document_has_unique_headings() -> None:
    for document in _documents():
        headings = [
            line.lstrip("#").strip()
            for line in document.read_text(encoding="utf-8").splitlines()
            if re.match(r"^#{1,6}\s+\S", line)
        ]
        assert len(headings) == len(set(headings)), (
            f"{document.relative_to(ROOT)} 包含重复标题"
        )
