from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from app.atomic import atomic_write_bytes, content_lock
from app.career.application.ports import UnitOfWork
from app.career.domain.policies import new_id, now
from app.career.domain.profile import (
    DOCUMENT_KINDS,
    CareerProfile,
    CareerProject,
    PrivateDocument,
)


class ProfileService:
    def __init__(
        self,
        uow: UnitOfWork,
        documents_root: Path,
        validate_document: Callable[[str, bytes], tuple[str, str, str]],
    ):
        self.uow = uow
        self.documents_root = documents_root
        self.validate_document = validate_document

    def save_profile(self, **fields: str) -> CareerProfile:
        with self.uow(write=True) as stores:
            return stores.profile.save_profile(**fields)

    def import_profile(
        self, document_id: str, material: str, analyze: Callable[[str], dict]
    ) -> dict:
        with self.uow() as stores:
            if stores.documents.document(document_id) is None:
                raise KeyError(document_id)
        return analyze(material)

    def add_project(self, **fields: str) -> CareerProject:
        with self.uow(write=True) as stores:
            return stores.projects.add_project(**fields)

    def update_project(self, project_id: str, **fields: str) -> CareerProject:
        with self.uow(write=True) as stores:
            return stores.projects.update_project(project_id, **fields)

    def add_document(
        self, *, kind: str, filename: str, content: bytes
    ) -> PrivateDocument:
        if kind not in DOCUMENT_KINDS:
            raise ValueError("文档类型无效")
        extension, media_type, extracted = self.validate_document(filename, content)
        document_id = new_id("doc")
        document = PrivateDocument(
            id=document_id,
            kind=kind,
            original_name=Path(filename).name[:180],
            stored_name=f"{document_id}{extension}",
            media_type=media_type,
            size=len(content),
            sha256=sha256(content).hexdigest(),
            extracted_text=extracted[:100_000],
            created_at=now(),
        )
        path = self.documents_root / document.stored_name
        with content_lock(self.documents_root):
            try:
                with self.uow(write=True) as stores:
                    atomic_write_bytes(path, content)
                    stores.documents.insert(document)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return document

    def delete_document(self, document_id: str, confirmation: str) -> None:
        if confirmation.strip() != "删除文档":
            raise ValueError("请输入“删除文档”进行确认")
        with content_lock(self.documents_root):
            with self.uow(write=True) as stores:
                document = stores.documents.document(document_id)
                if document is None:
                    raise KeyError(document_id)
                if Path(document.stored_name).name != document.stored_name:
                    raise ValueError("文档存储路径无效")
                stores.documents.delete(document_id)
            (self.documents_root / document.stored_name).unlink(missing_ok=True)
