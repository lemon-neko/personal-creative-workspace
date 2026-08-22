from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import yaml

from app.main import create_app


ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = ROOT / "docs"
ROOT_DOCS = {
    ROOT / "README.md",
    ROOT / "PROJECT_STATUS.md",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
}
REQUIRED_INDEXES = {
    DOCS_ROOT / "README.md",
    DOCS_ROOT / "features" / "README.md",
    DOCS_ROOT / "architecture" / "README.md",
    DOCS_ROOT / "guides" / "README.md",
    DOCS_ROOT / "operations" / "README.md",
    DOCS_ROOT / "development" / "README.md",
    DOCS_ROOT / "changes" / "README.md",
    DOCS_ROOT / "changes" / "TEMPLATE.md",
}
REQUIRED_FEATURES = {
    "workspace-content.md",
    "knowledge-obsidian.md",
    "publishing-video.md",
    "career-learning.md",
    "assistant.md",
    "model-cost.md",
    "mobile-pwa.md",
    "privacy-recovery.md",
}
REQUIRED_ARCHITECTURE = {
    "content-model.md",
    "private-vault-folders.md",
    "storage.md",
}
REQUIRED_CHANGE_FIELDS = {
    "date",
    "status",
    "type",
    "areas",
    "interfaces",
    "data_migration",
    "compatibility",
    "rollback",
    "verification",
    "commit",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
TAILNET_HOST = re.compile(r"\b[a-z0-9-]+\.tail[a-z0-9]+\.ts\.net\b", re.I)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _documents() -> tuple[Path, ...]:
    docs = set(DOCS_ROOT.rglob("*.md"))
    return tuple(sorted(ROOT_DOCS | docs))


def test_documentation_set_and_local_links_exist() -> None:
    assert all(path.is_file() for path in ROOT_DOCS | REQUIRED_INDEXES)
    assert {
        path.name for path in (DOCS_ROOT / "features").glob("*.md")
    } >= REQUIRED_FEATURES | {"README.md"}
    assert {
        path.name for path in (DOCS_ROOT / "architecture").glob("*.md")
    } >= REQUIRED_ARCHITECTURE | {"README.md"}

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
        "/articles",
        "/knowledge",
        "/library",
        "/search",
        "/reviews",
        "/publish",
        "/video",
        "/career",
        "/learning",
        "/assistant",
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


def test_feature_index_covers_every_feature_document() -> None:
    index = (DOCS_ROOT / "features" / "README.md").read_text(encoding="utf-8")
    for filename in REQUIRED_FEATURES:
        assert f"({filename})" in index


def test_change_records_have_required_metadata_and_are_indexed() -> None:
    change_index = (DOCS_ROOT / "changes" / "README.md").read_text(
        encoding="utf-8"
    )
    records = sorted((DOCS_ROOT / "changes").glob("[0-9][0-9][0-9][0-9]/*.md"))
    assert records

    for record in records:
        text = record.read_text(encoding="utf-8")
        match = FRONT_MATTER.match(text)
        assert match, f"{record.relative_to(ROOT)} 缺少 YAML front matter"
        metadata = yaml.safe_load(match.group(1))
        assert isinstance(metadata, dict)
        assert REQUIRED_CHANGE_FIELDS <= metadata.keys()
        assert metadata["status"] == "completed"
        assert metadata["type"] in {
            "baseline",
            "feature",
            "fix",
            "refactor",
            "docs",
            "security",
            "migration",
        }
        assert isinstance(metadata["areas"], list) and metadata["areas"]
        assert isinstance(metadata["interfaces"], list) and metadata["interfaces"]
        assert isinstance(metadata["verification"], list) and metadata["verification"]
        assert record.name in change_index
