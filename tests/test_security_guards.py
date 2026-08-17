from __future__ import annotations

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
    assert violations(("app/main.py", "README.md", "tests/example.py")) == ()
