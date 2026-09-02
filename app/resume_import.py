"""Idempotent local DOCX-to-primary-resume import service and CLI."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.career import CareerRepository, PrivateDocument, ResumeVersion
from app.privacy import default_data_root, prepare_private_root
from app.resume_docx import DocxResumeCandidate, parse_resume_docx
from app.resume_studio import StructuredResume


@dataclass(frozen=True)
class ResumeImportResult:
    resume: ResumeVersion | None
    candidate: DocxResumeCandidate
    created: bool
    snapshot: Path | None = None


def preview_document(
    repository: CareerRepository, document: PrivateDocument
) -> DocxResumeCandidate:
    if not document.stored_name.lower().endswith(".docx"):
        raise ValueError("该本地导入流程仅支持 DOCX")
    content = repository.document_path(document).read_bytes()
    if hashlib.sha256(content).hexdigest() != document.sha256:
        raise ValueError("私有文档校验和不一致，已停止导入")
    return parse_resume_docx(content, repository.profile(), repository.projects())


def import_primary_resume(
    repository: CareerRepository,
    document: PrivateDocument,
    *,
    title: str,
    target_role: str,
    structured: StructuredResume | None = None,
    include_photo: bool = True,
) -> ResumeImportResult:
    """Create the one primary resume after a snapshot, or return the existing one."""

    candidate = preview_document(repository, document)
    existing = repository.primary_resume_for_document(document.id)
    if existing is not None:
        return ResumeImportResult(existing, candidate, False)
    snapshot = repository.snapshot("resume-primary-import")
    asset = None
    asset_preexisting = False
    try:
        if include_photo and candidate.portrait is not None:
            digest = hashlib.sha256(candidate.portrait.content).hexdigest()
            asset_preexisting = (
                repository.resume_asset_for_source(document.id, digest) is not None
            )
            asset = repository.store_resume_asset(
                candidate.portrait, source_document_id=document.id
            )
        resume = repository.add_structured_resume(
            title=title,
            target_role=target_role,
            document_id=document.id,
            structured=structured or candidate.resume,
            resume_kind="master",
            status="active",
            is_primary=True,
            template_key="china_single_photo" if asset else "ats_single",
            photo_asset_id=asset.id if asset else "",
        )
    except Exception:
        if asset is not None and not asset_preexisting:
            repository.delete_resume_asset_if_unreferenced(asset.id)
        raise
    return ResumeImportResult(resume, candidate, True, snapshot)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从已有私有 DOCX 导入主简历")
    parser.add_argument("--document-sha", required=True)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    data_root = prepare_private_root(arguments.data_root or default_data_root())
    repository = CareerRepository(data_root)
    document = repository.document_by_sha256(arguments.document_sha)
    if document is None:
        raise SystemExit("未找到校验和匹配的私有简历文档")
    candidate = preview_document(repository, document)
    existing = repository.primary_resume_for_document(document.id)
    if existing is not None:
        print("主简历已经导入；未创建重复记录")
        return
    if not arguments.apply:
        print(
            "导入预览通过："
            f"{len(candidate.resume.work_experience)} 段工作经历，"
            f"{len(candidate.resume.projects)} 个项目，"
            f"照片={'有' if candidate.portrait else '无'}；未写入数据"
        )
        return
    result = import_primary_resume(
        repository,
        document,
        title=f"主简历 · {document.original_name}",
        target_role=candidate.resume.personal_info.get("title", ""),
    )
    print("主简历导入完成" if result.created else "主简历已经存在")


if __name__ == "__main__":
    main()
