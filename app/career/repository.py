from __future__ import annotations

from pathlib import Path
import sqlite3

from app.career.application.job_service import JobService
from app.career.application.learning_service import LearningService
from app.career.application.profile_service import ProfileService
from app.career.application.resume_service import ResumeService
from app.career.domain.job import (
    JobOpportunity,
    JobResumeSubmission,
    JobSkillGap,
    JobStageEvent,
)
from app.career.domain.learning import (
    CapabilityDomain,
    JobCapability,
    LearningCampaign,
    LearningPath,
    LearningReference,
    LearningStage,
    LearningStageReference,
    LearningTask,
    Quest,
    QuestEvidence,
    Skill,
)
from app.career.domain.profile import CareerProfile, CareerProject, PrivateDocument
from app.career.domain.resume import ResumeAsset, ResumeVersion, StructuredResume
from app.career.infrastructure.documents import validate_document
from app.career.infrastructure.sqlite.migrations import migrate_career
from app.career.infrastructure.sqlite.unit_of_work import SQLiteUnitOfWork
from app.database import connect_database, snapshot_database
from app.resume_assets import ResumeImage


class CareerRepository:
    """Compatibility facade for desktop routes, background readers and local tools."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.database_path = data_root / "workspace.db"
        self.documents_root = data_root / "documents"
        self.documents_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.resume_assets_root = self.documents_root / "resume-assets"
        self.resume_assets_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.resume_assets_root.chmod(0o700)
        migrate_career(self.database_path, self.data_root)
        self.unit_of_work = SQLiteUnitOfWork(
            self.database_path, self.documents_root, self.resume_assets_root
        )
        self.profile_service = ProfileService(
            self.unit_of_work, self.documents_root, validate_document
        )
        self.resume_service = ResumeService(
            self.unit_of_work,
            self.documents_root,
            self.resume_assets_root,
            self.snapshot,
        )
        self.job_service = JobService(self.unit_of_work)
        self.learning_service = LearningService(self.unit_of_work)

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def snapshot(self, label: str) -> Path:
        safe_label = "".join(
            character for character in label if character.isalnum() or character in "-_"
        )[:80]
        if not safe_label:
            raise ValueError("快照标签无效")
        return snapshot_database(
            self.database_path,
            self.data_root / "working" / "db-migrations",
            safe_label,
        )

    def profile(self) -> CareerProfile:
        with self.unit_of_work() as stores:
            return stores.profile.profile()

    def save_profile(self, **fields: str) -> CareerProfile:
        return self.profile_service.save_profile(**fields)

    def documents(self, kind: str | None = None) -> tuple[PrivateDocument, ...]:
        with self.unit_of_work() as stores:
            return stores.documents.documents(kind)

    def document(self, document_id: str) -> PrivateDocument | None:
        with self.unit_of_work() as stores:
            return stores.documents.document(document_id)

    def document_by_sha256(self, digest: str) -> PrivateDocument | None:
        with self.unit_of_work() as stores:
            return stores.documents.document_by_sha256(digest)

    def document_path(self, document: PrivateDocument) -> Path:
        with self.unit_of_work() as stores:
            return stores.documents.document_path(document)

    def resume_asset(self, asset_id: str) -> ResumeAsset | None:
        with self.unit_of_work() as stores:
            return stores.resumes.resume_asset(asset_id)

    def resume_asset_for_source(
        self, source_document_id: str, sha256: str
    ) -> ResumeAsset | None:
        with self.unit_of_work() as stores:
            return stores.resumes.resume_asset_for_source(source_document_id, sha256)

    def resume_photo(self, resume: ResumeVersion) -> ResumeAsset | None:
        with self.unit_of_work() as stores:
            return stores.resumes.resume_photo(resume)

    def resume_asset_path(self, asset: ResumeAsset) -> Path:
        with self.unit_of_work() as stores:
            return stores.resumes.resume_asset_path(asset)

    def store_resume_asset(
        self, image: ResumeImage | bytes, *, source_document_id: str = ""
    ) -> ResumeAsset:
        return self.resume_service.store_resume_asset(
            image, source_document_id=source_document_id
        )

    def delete_resume_asset_if_unreferenced(self, asset_id: str) -> bool:
        return self.resume_service.delete_resume_asset_if_unreferenced(asset_id)

    def delete_document(self, document_id: str, confirmation: str) -> None:
        return self.profile_service.delete_document(document_id, confirmation)

    def add_document(
        self, *, kind: str, filename: str, content: bytes
    ) -> PrivateDocument:
        return self.profile_service.add_document(
            kind=kind, filename=filename, content=content
        )

    def projects(self) -> tuple[CareerProject, ...]:
        with self.unit_of_work() as stores:
            return stores.projects.projects()

    def project(self, project_id: str) -> CareerProject | None:
        with self.unit_of_work() as stores:
            return stores.projects.project(project_id)

    def add_project(self, **fields: str) -> CareerProject:
        return self.profile_service.add_project(**fields)

    def update_project(self, project_id: str, **fields: str) -> CareerProject:
        return self.profile_service.update_project(project_id, **fields)

    def resumes(self) -> tuple[ResumeVersion, ...]:
        with self.unit_of_work() as stores:
            return stores.resumes.resumes()

    def resume(self, resume_id: str) -> ResumeVersion | None:
        with self.unit_of_work() as stores:
            return stores.resumes.resume(resume_id)

    def primary_resume(self) -> ResumeVersion | None:
        with self.unit_of_work() as stores:
            return stores.resumes.primary_resume()

    def primary_resume_for_document(self, document_id: str) -> ResumeVersion | None:
        with self.unit_of_work() as stores:
            return stores.resumes.primary_resume_for_document(document_id)

    @staticmethod
    def structured_resume(resume: ResumeVersion) -> StructuredResume:
        return ResumeService.structured_resume(resume)

    def resume_source_fingerprint(self, project_ids: tuple[str, ...]) -> str:
        return self.resume_service.resume_source_fingerprint(project_ids)

    def resume_source_is_current(self, resume: ResumeVersion) -> bool:
        return self.resume_service.resume_source_is_current(resume)

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
        return self.resume_service.add_structured_resume(
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
        return self.resume_service.update_structured_resume(
            resume_id,
            structured=structured,
            expected_revision=expected_revision,
            title=title,
            target_role=target_role,
            notes=notes,
            template_key=template_key,
        )

    def update_resume_photo(
        self, resume_id: str, *, expected_revision: int, photo_asset_id: str = ""
    ) -> ResumeVersion:
        return self.resume_service.update_resume_photo(
            resume_id,
            expected_revision=expected_revision,
            photo_asset_id=photo_asset_id,
        )

    def update_resume_status(self, resume_id: str, status: str) -> None:
        return self.resume_service.update_resume_status(resume_id, status)

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
        return self.resume_service.add_resume(
            title=title,
            target_role=target_role,
            document_id=document_id,
            project_ids=project_ids,
            status=status,
            notes=notes,
        )

    def confirmed_skill_names(self, job_id: str) -> tuple[str, ...]:
        return self.job_service.confirmed_skill_names(job_id)

    def jobs(self) -> tuple[JobOpportunity, ...]:
        with self.unit_of_work() as stores:
            return stores.jobs.jobs()

    def job(self, job_id: str) -> JobOpportunity | None:
        with self.unit_of_work() as stores:
            return stores.jobs.job(job_id)

    def add_job(
        self,
        *,
        company: str,
        title: str,
        jd_text: str = "",
        location: str = "",
        source_url: str = "",
        notes: str = "",
        tier: str = "B",
        applied_on: str = "",
        next_action: str = "",
        next_action_on: str = "",
        status: str = "saved",
        creation_token: str = "",
    ) -> JobOpportunity:
        return self.job_service.add_job(
            company=company,
            title=title,
            jd_text=jd_text,
            location=location,
            source_url=source_url,
            notes=notes,
            tier=tier,
            applied_on=applied_on,
            next_action=next_action,
            next_action_on=next_action_on,
            status=status,
            creation_token=creation_token,
        )

    def patch_job(self, job_id: str, changes: dict[str, str]) -> JobOpportunity:
        return self.job_service.patch_job(job_id, changes)

    def update_job(
        self,
        job_id: str,
        *,
        company: str,
        title: str,
        status: str,
        tier: str,
        applied_on: str,
        next_action: str,
        next_action_on: str,
        location: str = "",
        source_url: str = "",
        jd_text: str = "",
        notes: str = "",
        stage_note: str = "",
    ) -> JobOpportunity:
        return self.job_service.update_job(
            job_id,
            company=company,
            title=title,
            status=status,
            tier=tier,
            applied_on=applied_on,
            next_action=next_action,
            next_action_on=next_action_on,
            location=location,
            source_url=source_url,
            jd_text=jd_text,
            notes=notes,
            stage_note=stage_note,
        )

    def update_job_status(
        self, job_id: str, status: str, note: str = ""
    ) -> JobOpportunity:
        return self.job_service.update_job_status(job_id, status, note)

    def job_submissions(
        self, job_id: str | None = None
    ) -> tuple[JobResumeSubmission, ...]:
        with self.unit_of_work() as stores:
            return stores.jobs.job_submissions(job_id)

    def job_submission(self, submission_id: int) -> JobResumeSubmission | None:
        with self.unit_of_work() as stores:
            return stores.jobs.job_submission(submission_id)

    def record_job_submission(self, job_id: str, resume_id: str) -> JobResumeSubmission:
        return self.job_service.record_job_submission(job_id, resume_id)

    def update_job_plan(
        self,
        job_id: str,
        *,
        tier: str,
        applied_on: str,
        next_action: str,
        next_action_on: str,
    ) -> JobOpportunity:
        with self.unit_of_work(write=True) as stores:
            return stores.jobs.update_job_plan(
                job_id,
                tier=tier,
                applied_on=applied_on,
                next_action=next_action,
                next_action_on=next_action_on,
            )

    def add_job_event(self, job_id: str, status: str, note: str = "") -> None:
        with self.unit_of_work(write=True) as stores:
            return stores.jobs.add_job_event(job_id, status, note)

    def job_events(self, job_id: str) -> tuple[JobStageEvent, ...]:
        with self.unit_of_work() as stores:
            return stores.jobs.job_events(job_id)

    def skills(self) -> tuple[Skill, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.skills()

    def skill_by_name(self, name: str) -> Skill | None:
        with self.unit_of_work() as stores:
            return stores.learning.skill_by_name(name)

    def find_or_add_skill(self, *, name: str, category: str = "") -> Skill:
        return self.learning_service.find_or_add_skill(name=name, category=category)

    def add_skill(
        self,
        *,
        name: str,
        category: str = "",
        current_level: int = 0,
        target_level: int = 3,
        notes: str = "",
    ) -> Skill:
        return self.learning_service.add_skill(
            name=name,
            category=category,
            current_level=current_level,
            target_level=target_level,
            notes=notes,
        )

    def set_job_skill_gap(
        self,
        *,
        job_id: str,
        skill_id: str,
        importance: int,
        evidence: str = "",
        gap_note: str = "",
    ) -> None:
        return self.job_service.set_job_skill_gap(
            job_id=job_id,
            skill_id=skill_id,
            importance=importance,
            evidence=evidence,
            gap_note=gap_note,
        )

    def gaps(self) -> tuple[JobSkillGap, ...]:
        with self.unit_of_work() as stores:
            return stores.jobs.gaps()

    def learning_tasks(self) -> tuple[LearningTask, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.learning_tasks()

    def capability_domains(self) -> tuple[CapabilityDomain, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.capability_domains()

    def job_capabilities(self) -> tuple[JobCapability, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.job_capabilities()

    def capability_skill_ids(self) -> dict[str, tuple[str, ...]]:
        with self.unit_of_work() as stores:
            return stores.learning.capability_skill_ids()

    def learning_references(self) -> tuple[LearningReference, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.learning_references()

    def learning_reference(self, reference_id: str) -> LearningReference | None:
        with self.unit_of_work() as stores:
            return stores.learning.learning_reference(reference_id)

    def learning_paths(self) -> tuple[LearningPath, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.learning_paths()

    def learning_path(self, path_id: str) -> LearningPath | None:
        with self.unit_of_work() as stores:
            return stores.learning.learning_path(path_id)

    def learning_stages(self, path_id: str | None = None) -> tuple[LearningStage, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.learning_stages(path_id)

    def learning_stage(self, stage_id: str) -> LearningStage | None:
        with self.unit_of_work() as stores:
            return stores.learning.learning_stage(stage_id)

    def learning_stage_references(
        self, stage_id: str | None = None
    ) -> tuple[LearningStageReference, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.learning_stage_references(stage_id)

    def learning_stage_capability_ids(self) -> dict[str, tuple[str, ...]]:
        with self.unit_of_work() as stores:
            return stores.learning.learning_stage_capability_ids()

    def update_learning_stage(
        self,
        stage_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningStage:
        return self.learning_service.update_learning_stage(
            stage_id,
            status=status,
            commit_sha=commit_sha,
            test_result=test_result,
            reflection=reflection,
        )

    def update_learning_stage_status(
        self, stage_id: str, *, status: str
    ) -> LearningStage:
        return self.learning_service.update_learning_stage_status(
            stage_id, status=status
        )

    def reference_capability_ids(self) -> dict[str, tuple[str, ...]]:
        with self.unit_of_work() as stores:
            return stores.learning.reference_capability_ids()

    def reference_task_ids(self) -> dict[str, tuple[str, ...]]:
        with self.unit_of_work() as stores:
            return stores.learning.reference_task_ids()

    def update_learning_reference(
        self,
        reference_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningReference:
        return self.learning_service.update_learning_reference(
            reference_id,
            status=status,
            commit_sha=commit_sha,
            test_result=test_result,
            reflection=reflection,
        )

    def seed_career_radar(self) -> None:
        return self.learning_service.seed_career_radar()

    def update_learning_task_status(self, task_id: str, status: str) -> None:
        return self.learning_service.update_learning_task_status(task_id, status)

    def add_learning_task(
        self,
        *,
        skill_id: str,
        title: str,
        status: str = "backlog",
        priority: int = 3,
        linked_content_id: str = "",
        linked_project_id: str = "",
        notes: str = "",
    ) -> LearningTask:
        return self.learning_service.add_learning_task(
            skill_id=skill_id,
            title=title,
            status=status,
            priority=priority,
            linked_content_id=linked_content_id,
            linked_project_id=linked_project_id,
            notes=notes,
        )

    def seed_agent_reliability_campaign(self, repository_path: str) -> LearningCampaign:
        with self.unit_of_work(write=True) as stores:
            return stores.learning.seed_agent_reliability_campaign(repository_path)

    def campaigns(self) -> tuple[LearningCampaign, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.campaigns()

    def campaign(self, campaign_id: str) -> LearningCampaign | None:
        with self.unit_of_work() as stores:
            return stores.learning.campaign(campaign_id)

    def quests(self, campaign_id: str) -> tuple[Quest, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.quests(campaign_id)

    def quest(self, quest_id: str) -> Quest | None:
        with self.unit_of_work() as stores:
            return stores.learning.quest(quest_id)

    def quest_evidence(self, quest_id: str) -> tuple[QuestEvidence, ...]:
        with self.unit_of_work() as stores:
            return stores.learning.quest_evidence(quest_id)

    def campaign_xp(self, campaign_id: str) -> int:
        with self.unit_of_work() as stores:
            return stores.learning.campaign_xp(campaign_id)

    def start_quest(self, quest_id: str) -> Quest:
        return self.learning_service.start_quest(quest_id)

    def add_quest_evidence(
        self,
        quest_id: str,
        *,
        commit_sha: str,
        test_result: str,
        reflection: str = "",
        evidence_url: str = "",
    ) -> QuestEvidence:
        return self.learning_service.add_quest_evidence(
            quest_id,
            commit_sha=commit_sha,
            test_result=test_result,
            reflection=reflection,
            evidence_url=evidence_url,
        )

    def clear_quest(self, quest_id: str) -> Quest:
        return self.learning_service.clear_quest(quest_id)
