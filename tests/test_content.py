from __future__ import annotations

from pathlib import Path

from app.content import load_items, parse_item, render_markdown


def write_item(
    directory: Path,
    name: str,
    front_matter: str,
    body: str = "正文",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"---\n{front_matter}\n---\n\n{body}\n", encoding="utf-8")
    return path


def valid_metadata(
    *,
    item_id: str = "idea-1",
    title: str = "一条想法",
    created_at: str = "2026-07-30T10:00:00+08:00",
    updated_at: str = "2026-07-30T10:00:00+08:00",
    status: str = "draft",
    kind: str = "thought",
    tags: str = "[观察, 路上]",
    category: str = "category: 日常\n",
) -> str:
    return (
        f"id: {item_id}\n"
        f"title: {title}\n"
        f"created_at: '{created_at}'\n"
        f"updated_at: '{updated_at}'\n"
        f"status: {status}\n"
        f"kind: {kind}\n"
        "summary: 一句话摘要\n"
        f"tags: {tags}\n"
        f"{category}"
    ).strip()


def test_parse_valid_content_item(tmp_path: Path) -> None:
    item = parse_item(write_item(tmp_path, "valid.md", valid_metadata()))

    assert item.id == "idea-1"
    assert item.status == "draft"
    assert item.kind == "thought"
    assert item.tags == ("观察", "路上")
    assert item.category == "日常"
    assert item.body == "正文"
    assert item.date_label == "2026-07-30"


def test_load_sorts_newest_and_filters_all_dimensions(tmp_path: Path) -> None:
    write_item(
        tmp_path,
        "older.md",
        valid_metadata(item_id="older", title="散步观察"),
        "路上看见一棵树。",
    )
    write_item(
        tmp_path,
        "newer.md",
        valid_metadata(
            item_id="newer",
            title="一篇文章",
            created_at="2026-07-31T11:00:00+08:00",
            updated_at="2026-07-31T11:00:00+08:00",
            status="published",
            kind="article",
            tags="[写作]",
            category="category: 写作\n",
        ),
        "关于表达的正文。",
    )

    collection = load_items(tmp_path)

    assert [item.id for item in collection.items] == ["newer", "older"]
    assert [item.id for item in collection.published] == ["newer"]
    assert [item.id for item in collection.filter(query="表达")] == ["newer"]
    assert [item.id for item in collection.filter(tag="观察")] == ["older"]
    assert [item.id for item in collection.filter(category="写作")] == ["newer"]
    assert [item.id for item in collection.filter(kind="article")] == ["newer"]
    assert [item.id for item in collection.filter(date_from="2026-07-31")] == [
        "newer",
    ]


def test_bad_files_become_diagnostics_without_hiding_good_items(
    tmp_path: Path,
) -> None:
    write_item(tmp_path, "good.md", valid_metadata())
    write_item(tmp_path, "missing.md", "id: incomplete")
    write_item(
        tmp_path,
        "status.md",
        valid_metadata(item_id="bad-status", status="deleted"),
    )
    write_item(
        tmp_path,
        "kind.md",
        valid_metadata(item_id="bad-kind", kind="topic"),
    )

    collection = load_items(tmp_path)

    assert [item.id for item in collection.items] == ["idea-1"]
    assert len(collection.diagnostics) == 3
    assert any("缺少必填字段" in item.message for item in collection.diagnostics)
    assert any("status" in item.message for item in collection.diagnostics)
    assert any("kind" in item.message for item in collection.diagnostics)


def test_duplicate_ids_are_isolated_as_diagnostic(tmp_path: Path) -> None:
    write_item(tmp_path, "a.md", valid_metadata())
    write_item(tmp_path, "b.md", valid_metadata())

    collection = load_items(tmp_path)

    assert len(collection.items) == 1
    assert "重复" in collection.diagnostics[0].message


def test_markdown_renders_rich_content_and_escapes_raw_html() -> None:
    html = render_markdown(
        "# 标题\n\n[链接](https://example.com)\n\n```python\nprint('ok')\n```"
        "\n\n$$x^2$$\n\n<script>alert('bad')</script>",
    )

    assert "<h1>标题</h1>" in html
    assert '<a href="https://example.com">链接</a>' in html
    assert "<code" in html
    assert "$$x^2$$" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
