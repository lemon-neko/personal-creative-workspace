from __future__ import annotations

from pathlib import Path

import pytest

from app import privacy
from tools.security_guards import violations


def test_private_database_canvas_and_deployment_files_are_rejected() -> None:
    problems = violations(
        (
            "workspace.db",
            "notes.sqlite3",
            "content/private.canvas",
            "vercel.json",
        )
    )

    assert any("workspace.db" in problem for problem in problems)
    assert any("notes.sqlite3" in problem for problem in problems)
    assert any("private.canvas" in problem for problem in problems)
    assert any("vercel.json" in problem for problem in problems)


def test_source_and_documentation_files_are_allowed() -> None:
    assert violations(("app/main.py", "README.md", "tests/example.py", ".env.example")) == ()


def test_legacy_content_and_environment_overrides_are_rejected() -> None:
    files = ("content/notes/personal.md", "content/workspace.yaml", ".env.production")
    assert len(violations(files)) == len(files)


def test_source_tree_cannot_be_used_as_private_data_root(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    monkeypatch.setattr(privacy, "__file__", str(source / "app" / "privacy.py"))
    with pytest.raises(ValueError, match="源码仓库之外"):
        privacy.prepare_private_root(source / "runtime")
    assert not source.exists()
