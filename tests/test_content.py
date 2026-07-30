from __future__ import annotations

from pathlib import Path

from app.content import load_notes, parse_note, render_markdown


def write_note(directory: Path, name: str, front_matter: str, body: str = "正文") -> Path:
    path = directory / name
    path.write_text(f"---\n{front_matter}\n---\n\n{body}\n", encoding="utf-8")
    return path


def valid_metadata(
    *,
    note_id: str = "note-1",
    title: str = "一条记录",
    note_date: str = "2026-07-30",
    status: str | None = "published",
    tags: str = "[Transformer, NumPy]",
    topic: str = "transformer",
) -> str:
    status_line = f"status: {status}\n" if status else ""
    return (
        f"id: {note_id}\n"
        f"title: {title}\n"
        f"date: {note_date}\n"
        f"{status_line}"
        "summary: 一句话摘要\n"
        f"tags: {tags}\n"
        f"topic: {topic}"
    )


def test_parse_valid_note(tmp_path: Path) -> None:
    note = parse_note(write_note(tmp_path, "valid.md", valid_metadata()))
    assert note.id == "note-1"
    assert note.status == "published"
    assert note.tags == ("Transformer", "NumPy")
    assert note.body == "正文"


def test_missing_status_defaults_to_draft(tmp_path: Path) -> None:
    note = parse_note(write_note(tmp_path, "draft.md", valid_metadata(status=None)))
    assert note.status == "draft"


def test_load_filters_drafts_and_sorts_newest_first(tmp_path: Path) -> None:
    write_note(
        tmp_path,
        "older.md",
        valid_metadata(note_id="older", note_date="2026-07-20"),
    )
    write_note(
        tmp_path,
        "newer.md",
        valid_metadata(note_id="newer", note_date="2026-07-29"),
    )
    write_note(
        tmp_path,
        "draft.md",
        valid_metadata(note_id="draft", note_date="2026-07-30", status="draft"),
    )

    collection = load_notes(tmp_path)
    assert [note.id for note in collection.published] == ["newer", "older"]


def test_filter_by_tag_and_topic(tmp_path: Path) -> None:
    write_note(tmp_path, "transformer.md", valid_metadata())
    write_note(
        tmp_path,
        "python.md",
        valid_metadata(note_id="python", tags="[Python]", topic="python"),
    )

    collection = load_notes(tmp_path)
    assert [note.id for note in collection.filter(tag="NumPy")] == ["note-1"]
    assert [note.id for note in collection.filter(topic="python")] == ["python"]


def test_bad_files_become_diagnostics_without_hiding_good_notes(tmp_path: Path) -> None:
    write_note(tmp_path, "good.md", valid_metadata())
    write_note(tmp_path, "missing.md", "id: incomplete")
    write_note(tmp_path, "status.md", valid_metadata(note_id="bad-status", status="archived"))

    collection = load_notes(tmp_path)
    assert [note.id for note in collection.notes] == ["note-1"]
    assert len(collection.diagnostics) == 2
    assert any("缺少必填字段" in diagnostic.message for diagnostic in collection.diagnostics)
    assert any("draft" in diagnostic.message for diagnostic in collection.diagnostics)


def test_markdown_renders_common_elements_and_keeps_math_delimiters() -> None:
    html = render_markdown(
        "# 标题\n\n[链接](https://example.com)\n\n```python\nprint('ok')\n```\n\n$$x^2$$"
    )
    assert "<h1>标题</h1>" in html
    assert '<a href="https://example.com">链接</a>' in html
    assert "<code" in html
    assert "$$x^2$$" in html


def test_markdown_escapes_raw_html() -> None:
    html = render_markdown("<script>alert('bad')</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
