from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

from app.atomic import atomic_write_bytes, content_lock
from app.career.application.ports import CareerStores, UnitOfWork
from app.career.domain.job import JobOpportunity
from app.career.domain.policies import new_id, now
from app.career.domain.profile import PrivateDocument
from app.career.domain.resume import (
    RESUME_STATUSES,
    ResumeAsset,
    ResumeVersion,
    StructuredResume,
    referenced_project_ids,
)
from app.resume_assets import ResumeImage, validate_resume_image
from app.resume_docx import DocxResumeCandidate, parse_resume_docx
from app.resume_studio import (
    RESUME_TEMPLATE_KEYS,
    apply_tailoring_suggestions,
    deserialize_structured_resume,
    normalize_structured_resume,
    serialize_structured_resume,
    source_fingerprint,
    validate_tailoring_suggestions,
)


@dataclass(frozen=True)
class ResumeImportResult:
    resume: ResumeVersion | None
    candidate: DocxResumeCandidate
    created: bool
    snapshot: Path | None = None


class ResumeService:
    def __init__(
        self,
        uow: UnitOfWork,
        documents_root: Path,
        assets_root: Path,
        snapshot: Callable[[str], Path],
    ):
        self.uow = uow
        self.documents_root = documents_root
        self.assets_root = assets_root
        self.snapshot = snapshot

    @staticmethod
    def structured_resume(resume: ResumeVersion) -> StructuredResume:
        if not resume.is_structured:
            raise ValueError("该记录不是结构化简历")
        return deserialize_structured_resume(resume.structured_data)

    @staticmethod
    def _source_fingerprint(
        stores: CareerStores, project_ids: tuple[str, ...], *, require_projects=False
    ) -> str:
        lookup = {project.id: project for project in stores.projects.projects()}
        if require_projects and not set(project_ids) <= lookup.keys():
            raise ValueError("简历引用了不存在的项目证据")
        selected = tuple(
            lookup[project_id] for project_id in project_ids if project_id in lookup
        )
        return source_fingerprint(stores.profile.profile(), selected).digest

    def resume_source_fingerprint(self, project_ids: tuple[str, ...]) -> str:
        with self.uow() as stores:
            return self._source_fingerprint(stores, project_ids)

    def resume_source_is_current(self, resume: ResumeVersion) -> bool:
        return bool(
            resume.is_structured
            and resume.source_fingerprint
            and resume.source_fingerprint
            == self.resume_source_fingerprint(resume.project_ids)
        )

    def add_resume(
        self,
        *,
        title: str,
        target_role: str = "",
        document_id: str = "",
        project_ids: tuple[str, ...] = (),
        status: str = "draft",
        notes: str = "",
    ) -> ResumeVersion:
        if not title.strip():
            raise ValueError("简历名称不能为空")
        if status not in RESUME_STATUSES:
            raise ValueError("简历状态无效")
        with self.uow(write=True) as stores:
            if document_id and stores.documents.document(document_id) is None:
                raise ValueError("关联文档不存在")
            if not set(project_ids) <= {
                project.id for project in stores.projects.projects()
            }:
                raise ValueError("关联项目不存在")
            stamp = now()
            resume = ResumeVersion(
                new_id("resume"),
                title.strip()[:160],
                target_role.strip()[:160],
                document_id or None,
                tuple(project_ids),
                status,
                notes.strip()[:10_000],
                stamp,
                stamp,
            )
            stores.resumes.insert(resume)
            return resume

    def add_structured_resume(
        self,
        *,
        title: str,
        structured: StructuredResume,
        resume_kind: str,
        target_role: str = "",
        document_id: str = "",
        parent_id: str = "",
        job_id: str = "",
        status: str = "draft",
        notes: str = "",
        is_primary: bool = False,
        template_key: str = "ats_single",
        photo_asset_id: str = "",
    ) -> ResumeVersion:
        with self.uow(write=True) as stores:
            return self._add_structured_resume(
                stores,
                title=title,
                structured=structured,
                resume_kind=resume_kind,
                target_role=target_role,
                document_id=document_id,
                parent_id=parent_id,
                job_id=job_id,
                status=status,
                notes=notes,
                is_primary=is_primary,
                template_key=template_key,
                photo_asset_id=photo_asset_id,
            )

    def _add_structured_resume(
        self,
        stores: CareerStores,
        *,
        title: str,
        structured: StructuredResume,
        resume_kind: str,
        target_role: str = "",
        document_id: str = "",
        parent_id: str = "",
        job_id: str = "",
        status: str = "draft",
        notes: str = "",
        is_primary: bool = False,
        template_key: str = "ats_single",
        photo_asset_id: str = "",
    ) -> ResumeVersion:
        if resume_kind not in {"master", "tailored"}:
            raise ValueError("结构化简历类型无效")
        if status not in RESUME_STATUSES:
            raise ValueError("简历状态无效")
        if template_key not in RESUME_TEMPLATE_KEYS:
            raise ValueError("简历模板无效")
        if not title.strip():
            raise ValueError("简历名称不能为空")
        if document_id and stores.documents.document(document_id) is None:
            raise ValueError("关联文档不存在")
        parent = stores.resumes.resume(parent_id) if parent_id else None
        if resume_kind == "tailored" and (
            parent is None or parent.resume_kind != "master"
        ):
            raise ValueError("定制简历必须关联有效主简历")
        if job_id and stores.jobs.job(job_id) is None:
            raise ValueError("关联职位不存在")
        if resume_kind == "tailored" and not job_id:
            raise ValueError("定制简历必须关联目标职位")
        if is_primary and resume_kind != "master":
            raise ValueError("只有主简历可以设为当前主版本")
        existing = stores.resumes.primary_resume() if is_primary else None
        if existing is not None:
            if document_id and existing.document_id == document_id:
                return existing
            raise ValueError("当前已经存在主简历，请先使用现有主简历")
        if photo_asset_id and stores.resumes.resume_asset(photo_asset_id) is None:
            raise ValueError("简历照片不存在")
        if resume_kind == "tailored" and parent is not None and not photo_asset_id:
            photo_asset_id = parent.photo_asset_id or ""

        project_ids = referenced_project_ids(structured)
        fingerprint = self._source_fingerprint(
            stores, project_ids, require_projects=True
        )
        stamp = now()
        resume = ResumeVersion(
            id=new_id("resume"),
            title=title.strip()[:160],
            target_role=target_role.strip()[:160],
            document_id=document_id or None,
            project_ids=project_ids,
            status=status,
            notes=notes.strip()[:10_000],
            created_at=stamp,
            updated_at=stamp,
            resume_kind=resume_kind,
            parent_id=parent_id or None,
            job_id=job_id or None,
            structured_data=serialize_structured_resume(structured),
            source_fingerprint=fingerprint,
            revision=1,
            template_key=template_key,
            is_primary=int(is_primary),
            photo_asset_id=photo_asset_id or None,
        )
        stores.resumes.insert(resume)
        return resume

    def update_structured_resume(
        self,
        resume_id: str,
        *,
        structured: StructuredResume,
        expected_revision: int,
        title: str,
        target_role: str = "",
        notes: str = "",
        template_key: str | None = None,
    ) -> ResumeVersion:
        with self.uow(write=True) as stores:
            current = stores.resumes.resume(resume_id)
            if current is None or not current.is_structured:
                raise KeyError(resume_id)
            if not title.strip():
                raise ValueError("简历名称不能为空")
            template_key = template_key or current.template_key
            if template_key not in RESUME_TEMPLATE_KEYS:
                raise ValueError("简历模板无效")
            project_ids = referenced_project_ids(structured)
            updated = replace(
                current,
                title=title.strip()[:160],
                target_role=target_role.strip()[:160],
                notes=notes.strip()[:10_000],
                project_ids=project_ids,
                structured_data=serialize_structured_resume(structured),
                source_fingerprint=self._source_fingerprint(
                    stores, project_ids, require_projects=True
                ),
                template_key=template_key,
                updated_at=now(),
                revision=current.revision + 1,
            )
            if not stores.resumes.update_structured(updated, expected_revision):
                raise RuntimeError("简历已在其他页面更新，请刷新后合并修改")
            return updated

    def update_resume_photo(
        self, resume_id: str, *, expected_revision: int, photo_asset_id: str = ""
    ) -> ResumeVersion:
        with self.uow(write=True) as stores:
            current = stores.resumes.resume(resume_id)
            if current is None or not current.is_structured:
                raise KeyError(resume_id)
            if photo_asset_id and stores.resumes.resume_asset(photo_asset_id) is None:
                raise ValueError("简历照片不存在")
            if not stores.resumes.set_photo(
                resume_id, photo_asset_id or None, expected_revision
            ):
                raise RuntimeError("简历已在其他页面更新，请刷新后重试")
            return stores.resumes.resume(resume_id)  # type: ignore[return-value]

    def update_resume_status(self, resume_id: str, status: str) -> None:
        with self.uow(write=True) as stores:
            stores.resumes.update_resume_status(resume_id, status)

    def store_resume_asset(
        self, image: ResumeImage | bytes, *, source_document_id: str = ""
    ) -> ResumeAsset:
        validated = (
            image if isinstance(image, ResumeImage) else validate_resume_image(image)
        )
        digest = sha256(validated.content).hexdigest()
        with content_lock(self.documents_root):
            asset_path = None
            try:
                with self.uow(write=True) as stores:
                    if source_document_id:
                        if stores.documents.document(source_document_id) is None:
                            raise ValueError("照片来源文档不存在")
                        existing = stores.resumes.resume_asset_for_source(
                            source_document_id, digest
                        )
                        if existing is not None:
                            return existing
                    asset = self._new_asset(validated, source_document_id, digest)
                    asset_path = self.assets_root / asset.stored_name
                    atomic_write_bytes(asset_path, validated.content)
                    stores.resumes.insert_asset(asset)
            except Exception:
                if asset_path is not None:
                    asset_path.unlink(missing_ok=True)
                raise
        return asset

    @staticmethod
    def _new_asset(image: ResumeImage, document_id: str, digest: str) -> ResumeAsset:
        asset_id = new_id("resume-photo")
        return ResumeAsset(
            asset_id,
            document_id or None,
            f"{asset_id}{image.extension}",
            image.media_type,
            len(image.content),
            digest,
            image.width,
            image.height,
            now(),
        )

    def delete_resume_asset_if_unreferenced(self, asset_id: str) -> bool:
        with content_lock(self.documents_root):
            with self.uow(write=True) as stores:
                asset = stores.resumes.resume_asset(asset_id)
                if (
                    asset is None
                    or stores.resumes.uses_asset(asset_id)
                    or stores.jobs.uses_asset(asset_id)
                ):
                    return False
                path = stores.resumes.resume_asset_path(asset)
                stores.resumes.delete_asset(asset_id)
            path.unlink(missing_ok=True)
        return True

    def preview_document(self, document: PrivateDocument) -> DocxResumeCandidate:
        if not document.stored_name.lower().endswith(".docx"):
            raise ValueError("该本地导入流程仅支持 DOCX")
        with self.uow() as stores:
            content = stores.documents.document_path(document).read_bytes()
            if sha256(content).hexdigest() != document.sha256:
                raise ValueError("私有文档校验和不一致，已停止导入")
            profile = stores.profile.profile()
            projects = stores.projects.projects()
        return parse_resume_docx(content, profile, projects)

    def import_primary_resume(
        self,
        document: PrivateDocument,
        *,
        title: str,
        target_role: str,
        structured: StructuredResume | None = None,
        include_photo: bool = True,
    ) -> ResumeImportResult:
        candidate = self.preview_document(document)
        with content_lock(self.documents_root):
            with self.uow() as stores:
                existing = stores.resumes.primary_resume_for_document(document.id)
            if existing is not None:
                return ResumeImportResult(existing, candidate, False)
            snapshot = self.snapshot("resume-primary-import")
            asset_path = None
            try:
                with self.uow(write=True) as stores:
                    existing = stores.resumes.primary_resume_for_document(document.id)
                    if existing is not None:
                        return ResumeImportResult(existing, candidate, False)
                    asset = None
                    if include_photo and candidate.portrait is not None:
                        portrait = candidate.portrait
                        digest = sha256(portrait.content).hexdigest()
                        asset = stores.resumes.resume_asset_for_source(
                            document.id, digest
                        )
                        if asset is None:
                            if stores.documents.document(document.id) is None:
                                raise ValueError("照片来源文档不存在")
                            asset = self._new_asset(portrait, document.id, digest)
                            asset_path = self.assets_root / asset.stored_name
                            atomic_write_bytes(asset_path, portrait.content)
                            stores.resumes.insert_asset(asset)
                    resume = self._add_structured_resume(
                        stores,
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
                if asset_path is not None:
                    asset_path.unlink(missing_ok=True)
                raise
        return ResumeImportResult(resume, candidate, True, snapshot)

    def import_structured_resume(
        self,
        document: PrivateDocument,
        *,
        title: str,
        target_role: str,
        structured: StructuredResume,
    ) -> ResumeVersion:
        self.snapshot("resume-primary-import")
        return self.add_structured_resume(
            title=title,
            target_role=target_role,
            document_id=document.id,
            structured=structured,
            resume_kind="master",
            status="active",
            is_primary=True,
        )

    def analyze_import(
        self, material: str, analyze: Callable[[str], dict]
    ) -> StructuredResume:
        json.loads(material)
        candidate = normalize_structured_resume(analyze(material)["resume"])
        with self.uow() as stores:
            if not set(referenced_project_ids(candidate)) <= {
                project.id for project in stores.projects.projects()
            }:
                raise ValueError("模型返回了虚构的项目证据 ID")
        return candidate

    def analyze_tailoring(
        self,
        resume: ResumeVersion,
        material: str,
        analyze: Callable[[str], dict],
    ):
        payload = analyze(material)
        json.loads(material)
        return validate_tailoring_suggestions(
            payload["suggestions"],
            self.structured_resume(resume),
            {"career-profile", *resume.project_ids},
        )

    def tailor_resume(
        self,
        resume: ResumeVersion,
        job: JobOpportunity,
        raw_suggestions: list[dict] | None = None,
    ) -> ResumeVersion:
        with self.uow(write=True) as stores:
            current = stores.resumes.resume(resume.id)
            target = stores.jobs.job(job.id)
            if current is None or current.resume_kind != "master" or target is None:
                raise KeyError(
                    resume.id
                    if current is None or current.resume_kind != "master"
                    else job.id
                )
            structured = self.structured_resume(current)
            if raw_suggestions is not None:
                if not target.jd_text.strip():
                    raise ValueError("请先补充 JD，再进行岗位分析或模型定制。")
                suggestions = validate_tailoring_suggestions(
                    raw_suggestions,
                    structured,
                    {"career-profile", *current.project_ids},
                )
                structured = apply_tailoring_suggestions(structured, suggestions)
            return self._add_structured_resume(
                stores,
                title=f"{target.company} · {target.title}",
                target_role=target.title,
                structured=structured,
                resume_kind="tailored",
                parent_id=current.id,
                job_id=target.id,
                photo_asset_id=current.photo_asset_id or "",
            )
