from __future__ import annotations

from pathlib import Path

from app.career.domain.profile import PrivateDocument
from app.career.infrastructure.sqlite.database import Repository


class DocumentRepository(Repository):
    def __init__(self, connection, documents_root: Path):
        super().__init__(connection)
        self.documents_root = documents_root

    def documents(self, kind: str | None = None) -> tuple[PrivateDocument, ...]:
        sql = "SELECT * FROM documents"
        params: tuple[str, ...] = ()
        if kind:
            sql += " WHERE kind = ?"
            params = (kind,)
        sql += " ORDER BY created_at DESC"
        connection = self.connection
        rows = connection.execute(sql, params).fetchall()
        return tuple(PrivateDocument(**dict(row)) for row in rows)

    def document(self, document_id: str) -> PrivateDocument | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return PrivateDocument(**dict(row)) if row else None

    def document_by_sha256(self, digest: str) -> PrivateDocument | None:
        connection = self.connection
        row = connection.execute(
            "SELECT * FROM documents WHERE sha256 = ? ORDER BY created_at LIMIT 1",
            (digest.strip().lower(),),
        ).fetchone()
        return PrivateDocument(**dict(row)) if row else None

    def document_path(self, document: PrivateDocument) -> Path:
        if Path(document.stored_name).name != document.stored_name:
            raise ValueError("文档存储路径无效")
        path = (self.documents_root / document.stored_name).resolve()
        if path.parent != self.documents_root.resolve() or not path.is_file():
            raise FileNotFoundError(document.id)
        return path

    def delete(self, document_id: str) -> None:
        self.connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def insert(self, document: PrivateDocument) -> None:
        self._insert("documents", document.__dict__)
