"""Local-only FTS5 index across the private workspace."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.database import (
    WORKSPACE_REGISTRY,
    apply_migrations,
    connect_database,
)

from app.content import ContentItem
from app.knowledge_store import KnowledgeStore
from app.library import SourceMaterial


SHANGHAI = ZoneInfo("Asia/Shanghai")


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
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="search",
            snapshot_root=data_root / "working" / "db-migrations",
            migrations={
                1: """CREATE VIRTUAL TABLE IF NOT EXISTS workspace_search USING fts5(
                    item_id UNINDEXED,
                    result_type UNINDEXED,
                    title,
                    body,
                    metadata,
                    url UNINDEXED,
                    source_label UNINDEXED,
                    tokenize='unicode61'
                );""",
                2: """CREATE TABLE IF NOT EXISTS workspace_search_state (
                    item_id TEXT NOT NULL,
                    result_type TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    PRIMARY KEY(item_id, result_type)
                );
                CREATE TABLE IF NOT EXISTS workspace_search_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    last_synced_at TEXT NOT NULL DEFAULT '',
                    total_rows INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO workspace_search_meta(singleton) VALUES(1);""",
            },
        )

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def rows(
        self,
        *,
        items: tuple[ContentItem, ...],
        knowledge: KnowledgeStore,
        materials: tuple[SourceMaterial, ...],
        career,
        video,
    ) -> tuple[tuple[str, str, str, str, str, str, str], ...]:
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
        return tuple(rows)

    @staticmethod
    def _revision(row: tuple[str, str, str, str, str, str, str]) -> str:
        return hashlib.sha256(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    def rebuild(self, **sources) -> None:
        rows = self.rows(**sources)
        now = datetime.now(SHANGHAI).replace(microsecond=0).isoformat()
        with self.connect() as connection:
            connection.execute("DELETE FROM workspace_search")
            connection.execute("DELETE FROM workspace_search_state")
            connection.executemany(
                "INSERT INTO workspace_search VALUES(?,?,?,?,?,?,?)",
                rows,
            )
            connection.executemany(
                "INSERT INTO workspace_search_state VALUES(?,?,?)",
                ((row[0], row[1], self._revision(row)) for row in rows),
            )
            connection.execute(
                "UPDATE workspace_search_meta SET last_synced_at=?, total_rows=? WHERE singleton=1",
                (now, len(rows)),
            )

    def sync(self, **sources) -> dict[str, int]:
        rows = self.rows(**sources)
        desired = {(row[0], row[1]): (row, self._revision(row)) for row in rows}
        changed = 0
        removed = 0
        now = datetime.now(SHANGHAI).replace(microsecond=0).isoformat()
        with self.connect() as connection:
            existing = {
                (str(row["item_id"]), str(row["result_type"])): str(
                    row["revision"]
                )
                for row in connection.execute(
                    "SELECT item_id,result_type,revision FROM workspace_search_state"
                )
            }
            for key in existing.keys() - desired.keys():
                connection.execute(
                    "DELETE FROM workspace_search WHERE item_id=? AND result_type=?",
                    key,
                )
                connection.execute(
                    "DELETE FROM workspace_search_state WHERE item_id=? AND result_type=?",
                    key,
                )
                removed += 1
            for key, (row, revision) in desired.items():
                if existing.get(key) == revision:
                    continue
                connection.execute(
                    "DELETE FROM workspace_search WHERE item_id=? AND result_type=?",
                    key,
                )
                connection.execute(
                    "INSERT INTO workspace_search VALUES(?,?,?,?,?,?,?)",
                    row,
                )
                connection.execute(
                    """INSERT INTO workspace_search_state VALUES(?,?,?)
                    ON CONFLICT(item_id,result_type) DO UPDATE SET revision=excluded.revision""",
                    (key[0], key[1], revision),
                )
                changed += 1
            connection.execute(
                "UPDATE workspace_search_meta SET last_synced_at=?, total_rows=? WHERE singleton=1",
                (now, len(rows)),
            )
        return {"changed": changed, "removed": removed, "total": len(rows)}

    def status(self) -> dict[str, str | int]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT last_synced_at,total_rows FROM workspace_search_meta WHERE singleton=1"
            ).fetchone()
        return {
            "last_synced_at": str(row["last_synced_at"] if row else ""),
            "total_rows": int(row["total_rows"] if row else 0),
        }

    def search(self, query: str, *, limit: int = 30) -> tuple[SearchResult, ...]:
        terms = re.findall(r"[\w\u3400-\u9fff]+", query, flags=re.UNICODE)
        if not terms:
            return ()
        match = " AND ".join(f'"{term}"' for term in terms[:8])
        with self.connect() as connection:
            fts_rows = connection.execute(
                """SELECT item_id AS id, result_type, title,
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
