"""Idempotent local DOCX-to-primary-resume import service and CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.career import CareerRepository, PrivateDocument
from app.career.application.resume_service import ResumeImportResult
from app.privacy import default_data_root, prepare_private_root
from app.resume_docx import DocxResumeCandidate
from app.resume_studio import StructuredResume


def preview_document(
    repository: CareerRepository,
    document: PrivateDocument,
) -> DocxResumeCandidate:
    return repository.resume_service.preview_document(document)


def import_primary_resume(
    repository: CareerRepository,
    document: PrivateDocument,
    *,
    title: str,
    target_role: str,
    structured: StructuredResume | None = None,
    include_photo: bool = True,
) -> ResumeImportResult:
    return repository.resume_service.import_primary_resume(
        document,
        title=title,
        target_role=target_role,
        structured=structured,
        include_photo=include_photo,
    )


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
