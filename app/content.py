"""Markdown-backed content model for the learning portfolio."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from markdown_it import MarkdownIt


VALID_STATUSES = {"draft", "published"}
REQUIRED_FIELDS = {"id", "title", "date", "summary", "tags", "topic"}
MARKDOWN = (
    MarkdownIt(
        "commonmark",
        {
            "html": False,
            "linkify": True,
            "typographer": True,
        },
    )
    .enable("table")
    .enable("strikethrough")
)


@dataclass(frozen=True)
class StudyNote:
    """A validated learning note."""

    id: str
    title: str
    date: date
    status: str
    summary: str
    tags: tuple[str, ...]
    topic: str
    body: str
    source: Path


@dataclass(frozen=True)
class ContentDiagnostic:
    """A content error that should be shown without stopping the site."""

    source: Path
    message: str


@dataclass(frozen=True)
class ContentCollection:
    """Notes and non-fatal diagnostics from one loading pass."""

    notes: tuple[StudyNote, ...]
    diagnostics: tuple[ContentDiagnostic, ...]

    @property
    def published(self) -> tuple[StudyNote, ...]:
        return tuple(note for note in self.notes if note.status == "published")

    def filter(
        self,
        *,
        status: str | None = "published",
        tag: str | None = None,
        topic: str | None = None,
    ) -> tuple[StudyNote, ...]:
        notes: Iterable[StudyNote] = self.notes
        if status is not None:
            notes = (note for note in notes if note.status == status)
        if tag:
            notes = (note for note in notes if tag in note.tags)
        if topic:
            notes = (note for note in notes if note.topic == topic)
        return tuple(notes)


def _split_front_matter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("缺少 YAML front matter 起始标记 `---`")

    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError("缺少 YAML front matter 结束标记 `---`") from error

    return "\n".join(lines[1:end]), "\n".join(lines[end + 1 :]).strip()


def _required_text(metadata: dict, field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{field}` 必须是非空文本")
    return value.strip()


def parse_note(path: Path) -> StudyNote:
    """Parse and validate one Markdown note."""

    front_matter, body = _split_front_matter(path.read_text(encoding="utf-8"))
    metadata = yaml.safe_load(front_matter)
    if not isinstance(metadata, dict):
        raise TypeError("front matter 必须是键值映射")

    missing = sorted(REQUIRED_FIELDS - metadata.keys())
    if missing:
        raise ValueError(f"缺少必填字段：{', '.join(missing)}")

    raw_status = metadata.get("status", "draft")
    if raw_status not in VALID_STATUSES:
        raise ValueError("`status` 只能是 `draft` 或 `published`")

    raw_date = metadata["date"]
    if isinstance(raw_date, date):
        parsed_date = raw_date
    elif isinstance(raw_date, str):
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError as error:
            raise ValueError("`date` 必须使用 YYYY-MM-DD 格式") from error
    else:
        raise TypeError("`date` 必须使用 YYYY-MM-DD 格式")

    raw_tags = metadata["tags"]
    if not isinstance(raw_tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in raw_tags):
        raise ValueError("`tags` 必须是文本列表")

    if not body:
        raise ValueError("Markdown 正文不能为空")

    return StudyNote(
        id=_required_text(metadata, "id"),
        title=_required_text(metadata, "title"),
        date=parsed_date,
        status=raw_status,
        summary=_required_text(metadata, "summary"),
        tags=tuple(tag.strip() for tag in raw_tags),
        topic=_required_text(metadata, "topic"),
        body=body,
        source=path,
    )


def load_notes(directory: Path) -> ContentCollection:
    """Load every note, keeping bad files as diagnostics instead of failing."""

    notes: list[StudyNote] = []
    diagnostics: list[ContentDiagnostic] = []
    seen_ids: dict[str, Path] = {}

    for path in sorted(directory.glob("*.md")) if directory.exists() else []:
        try:
            note = parse_note(path)
            if note.id in seen_ids:
                raise ValueError(f"`id` 与 {seen_ids[note.id].name} 重复：{note.id}")
            seen_ids[note.id] = path
            notes.append(note)
        except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
            diagnostics.append(ContentDiagnostic(path, str(error)))

    notes.sort(key=lambda note: (note.date, note.id), reverse=True)
    return ContentCollection(tuple(notes), tuple(diagnostics))


def load_markdown(path: Path) -> str:
    """Read a plain Markdown document used by a topic page."""

    return path.read_text(encoding="utf-8").strip()


def render_markdown(markdown: str) -> str:
    """Render repository-authored Markdown with raw HTML disabled."""

    return MARKDOWN.render(markdown)
