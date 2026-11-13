from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.career.domain.resume import RESUME_STATUSES, ResumeAsset, ResumeVersion
from app.career.domain.policies import now as _now
from app.career.infrastructure.sqlite.database import Repository


class ResumeRepository(Repository):
    def __init__(self, connection, resume_assets_root: Path):
        super().__init__(connection)
        self.resume_assets_root = resume_assets_root

    def insert(self, resume: ResumeVersion) -> None:
        self._insert(
            "resumes",
            resume.__dict__
            | {
                "project_ids": json.dumps(resume.project_ids, ensure_ascii=False),
            },
        )

    def insert_asset(self, asset: ResumeAsset) -> None:
        self._insert("resume_assets", asset.__dict__)

    def uses_asset(self, asset_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM resumes WHERE photo_asset_id=? LIMIT 1",
                (asset_id,),
            ).fetchone()
            is not None
        )

    def delete_asset(self, asset_id: str) -> None:
        self.connection.execute("DELETE FROM resume_assets WHERE id=?", (asset_id,))

    def update_structured(self, resume: ResumeVersion, expected_revision: int) -> bool:
        cursor = self.connection.execute(
            """UPDATE resumes SET title=?,target_role=?,notes=?,project_ids=?,
               structured_data=?,source_fingerprint=?,template_key=?,
               revision=revision+1,updated_at=? WHERE id=? AND revision=?""",
            (
                resume.title,
                resume.target_role,
                resume.notes,
                json.dumps(resume.project_ids, ensure_ascii=False),
                resume.structured_data,
                resume.source_fingerprint,
                resume.template_key,
                resume.updated_at,
                resume.id,
                expected_revision,
            ),
        )
        return cursor.rowcount == 1

    def set_photo(
        self, resume_id: str, photo_asset_id: str | None, expected_revision: int
    ) -> bool:
        cursor = self.connection.execute(
            """UPDATE resumes SET photo_asset_id=?,revision=revision+1,updated_at=?
               WHERE id=? AND revision=?""",
            (photo_asset_id, _now(), resume_id, expected_revision),
        )
        return cursor.rowcount == 1

    def resume_asset(self, asset_id: str) -> ResumeAsset | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM resume_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        return ResumeAsset(**dict(row)) if row else None

    def resume_asset_for_source(
        self, source_document_id: str, sha256: str
    ) -> ResumeAsset | None:
        connection = self.connection
        row = connection.execute(
            """SELECT * FROM resume_assets
            WHERE source_document_id=? AND sha256=? LIMIT 1""",
            (source_document_id, sha256.strip().lower()),
        ).fetchone()
        return ResumeAsset(**dict(row)) if row else None

    def resume_photo(self, resume: ResumeVersion) -> ResumeAsset | None:
        return self.resume_asset(resume.photo_asset_id or "")

    def resume_asset_path(self, asset: ResumeAsset) -> Path:
        if Path(asset.stored_name).name != asset.stored_name:
            raise ValueError("简历照片存储路径无效")
        path = (self.resume_assets_root / asset.stored_name).resolve()
        if path.parent != self.resume_assets_root.resolve() or not path.is_file():
            raise FileNotFoundError(asset.id)
        return path

    def resumes(self) -> tuple[ResumeVersion, ...]:
        connection = self.connection
        rows = connection.execute(
            "SELECT * FROM resumes ORDER BY updated_at DESC"
        ).fetchall()
        return tuple(self._resume(row) for row in rows)

    def resume(self, resume_id: str) -> ResumeVersion | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
        return self._resume(row) if row is not None else None

    def primary_resume(self) -> ResumeVersion | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM resumes WHERE is_primary = 1 LIMIT 1"
        ).fetchone()
        return self._resume(row) if row is not None else None

    def primary_resume_for_document(self, document_id: str) -> ResumeVersion | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM resumes WHERE is_primary=1 AND document_id=? LIMIT 1",
            (document_id,),
        ).fetchone()
        return self._resume(row) if row is not None else None

    def update_resume_status(self, resume_id: str, status: str) -> None:
        if status not in RESUME_STATUSES:
            raise ValueError("简历状态无效")
        connection = self.connection
        cursor = connection.execute(
            """UPDATE resumes SET status = ?,
            is_primary = CASE WHEN ? = 'archived' THEN 0 ELSE is_primary END,
            updated_at = ? WHERE id = ?""",
            (status, status, _now(), resume_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(resume_id)

    @staticmethod
    def _resume(row: sqlite3.Row) -> ResumeVersion:
        data = dict(row)
        try:
            project_ids = tuple(json.loads(data.pop("project_ids")))
        except (TypeError, ValueError):
            project_ids = ()
        return ResumeVersion(**data, project_ids=project_ids)
