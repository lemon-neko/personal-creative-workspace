"""Local-only FTS5 index across the private workspace."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.content import ContentItem
from app.knowledge_store import KnowledgeStore
from app.library import SourceMaterial


@dataclass(frozen=True)
class SearchResult:
    id: str
    result_type: str
    title: str
    snippet: str
    url: str
    source_label: str


class SearchRepository:
    def __init__(self, data_root: Path) -> None:
        self.database_path = data_root / "workspace.db"
        with self.connect() as connection:
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS workspace_search USING fts5(
                    item_id UNINDEXED,
                    result_type UNINDEXED,
                    title,
                    body,
                    metadata,
                    url UNINDEXED,
                    source_label UNINDEXED,
                    tokenize='unicode61'
                )""",
            )
        self.database_path.chmod(0o600)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def rebuild(
        self,
        *,
        items: tuple[ContentItem, ...],
        knowledge: KnowledgeStore,
        materials: tuple[SourceMaterial, ...],
        career,
        video,
    ) -> None:
        rows: list[tuple[str, str, str, str, str, str, str]] = []
        kind_labels = {
            "thought": "原始想法",
            "article": "创作产物",
            "weekly-review": "周回顾",
        }
        rows.extend(
            (
                item.id,
                item.kind,
                item.title,
                item.body,
                " ".join((*item.tags, *item.subjects, *item.concepts)),
                f"/ideas/{item.id}",
                kind_labels.get(item.kind, "内容"),
            )
            for item in items
        )
        rows.extend(
            (
                card.id,
                "knowledge-card",
                card.title,
                card.body,
                " ".join((*card.subjects, *card.concepts)),
                f"/knowledge/cards/{card.id}",
                "知识卡",
            )
            for card in knowledge.cards
        )
        rows.extend(
            (
                item.id,
                "knowledge-map",
                item.title,
                item.body,
                item.summary,
                f"/knowledge/maps/{item.id}",
                "学科地图" if item.kind == "subject" else "主题地图",
            )
            for item in knowledge.maps
        )
        rows.extend(
            (
                material.id,
                "material",
                material.title,
                material.body,
                " ".join(filter(None, (material.source_url, material.status))),
                f"/library?material={material.id}",
                "阅读材料",
            )
            for material in materials
        )
        for method_name, result_type, label, url_prefix, fields in (
            ("projects", "career-project", "项目证据", "/career/projects", ("name", "summary", "technologies", "evidence")),
            ("jobs", "career-job", "职位", "/career/jobs", ("company", "title", "jd_text", "notes")),
            ("resumes", "resume", "简历版本", "/career/resumes", ("title", "target_role", "notes")),
            ("skills", "skill", "技能", "/learning", ("name", "category", "notes")),
            ("learning_tasks", "learning-task", "学习任务", "/learning", ("title", "notes")),
        ):
            method = getattr(career, method_name, None)
            if not callable(method):
                continue
            for value in method():
                values = [str(getattr(value, field, "") or "") for field in fields]
                title = " · ".join(part for part in values[:2] if part) or value.id
                rows.append(
                    (
                        value.id,
                        result_type,
                        title,
                        "\n".join(values[2:]),
                        " ".join(values),
                        f"{url_prefix}/{value.id}" if result_type == "career-job" else url_prefix,
                        label,
                    ),
                )
        video_projects = getattr(video, "projects", None)
        if callable(video_projects):
            for project in video_projects():
                rows.append(
                    (
                        project.id,
                        "video-project",
                        project.title,
                        getattr(project, "notes", ""),
                        getattr(project, "status", ""),
                        f"/video?project={project.id}",
                        "视频项目",
                    ),
                )
        with self.connect() as connection:
            connection.execute("DELETE FROM workspace_search")
            connection.executemany(
                "INSERT INTO workspace_search VALUES(?,?,?,?,?,?,?)",
                rows,
            )

    def search(self, query: str, *, limit: int = 30) -> tuple[SearchResult, ...]:
        terms = re.findall(r"[\w\u3400-\u9fff]+", query, flags=re.UNICODE)
        if not terms:
            return ()
        match = " AND ".join(f'"{term}"' for term in terms[:8])
        with self.connect() as connection:
            fts_rows = connection.execute(
                """SELECT item_id, result_type, title,
                snippet(workspace_search, 3, '【', '】', '…', 18) AS snippet,
                url, source_label
                FROM workspace_search WHERE workspace_search MATCH ?
                ORDER BY bm25(workspace_search) LIMIT ?""",
                (match, max(1, min(limit, 100))),
            ).fetchall()
            clauses = [
                "lower(title || ' ' || body || ' ' || metadata) LIKE ?"
                for _ in terms[:8]
            ]
            like_rows = connection.execute(
                f"""SELECT item_id, result_type, title, body, metadata,
                url, source_label FROM workspace_search
                WHERE {' AND '.join(clauses)} LIMIT ?""",
                (*[f"%{term.casefold()}%" for term in terms[:8]], max(1, min(limit, 100))),
            ).fetchall()
        results = [SearchResult(**dict(row)) for row in fts_rows]
        seen = {(value.result_type, value.id) for value in results}
        for row in like_rows:
            key = (str(row["result_type"]), str(row["item_id"]))
            if key in seen:
                continue
            haystack = str(row["body"] or row["metadata"] or "")
            folded = haystack.casefold()
            position = min(
                (
                    folded.find(term.casefold())
                    for term in terms[:8]
                    if folded.find(term.casefold()) >= 0
                ),
                default=0,
            )
            start = max(0, position - 30)
            snippet = haystack[start : start + 120]
            results.append(
                SearchResult(
                    id=str(row["item_id"]),
                    result_type=str(row["result_type"]),
                    title=str(row["title"]),
                    snippet=snippet,
                    url=str(row["url"]),
                    source_label=str(row["source_label"]),
                )
            )
            seen.add(key)
            if len(results) >= limit:
                break
        return tuple(results[:limit])
