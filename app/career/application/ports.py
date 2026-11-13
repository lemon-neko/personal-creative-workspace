from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from app.career.domain.job import JobOpportunity, JobResumeSubmission, JobSkillGap
from app.career.domain.learning import (
    LearningReference,
    LearningStage,
    LearningTask,
    Quest,
    QuestEvidence,
    Skill,
)
from app.career.domain.profile import CareerProfile, CareerProject, PrivateDocument
from app.career.domain.resume import ResumeAsset, ResumeVersion


class ProfileStore(Protocol):
    def profile(self) -> CareerProfile: ...
    def save_profile(self, **fields: str) -> CareerProfile: ...


class DocumentStore(Protocol):
    def document(self, document_id: str) -> PrivateDocument | None: ...
    def document_path(self, document: PrivateDocument) -> Path: ...
    def insert(self, document: PrivateDocument) -> None: ...
    def delete(self, document_id: str) -> None: ...


class ProjectStore(Protocol):
    def projects(self) -> tuple[CareerProject, ...]: ...
    def add_project(self, **fields: str) -> CareerProject: ...
    def update_project(self, project_id: str, **fields: str) -> CareerProject: ...


class ResumeStore(Protocol):
    def resume(self, resume_id: str) -> ResumeVersion | None: ...
    def primary_resume(self) -> ResumeVersion | None: ...
    def primary_resume_for_document(self, document_id: str) -> ResumeVersion | None: ...
    def resume_asset(self, asset_id: str) -> ResumeAsset | None: ...
    def resume_asset_for_source(
        self, source_document_id: str, sha256: str
    ) -> ResumeAsset | None: ...
    def resume_asset_path(self, asset: ResumeAsset) -> Path: ...
    def insert(self, resume: ResumeVersion) -> None: ...
    def insert_asset(self, asset: ResumeAsset) -> None: ...
    def update_structured(
        self, resume: ResumeVersion, expected_revision: int
    ) -> bool: ...
    def update_resume_status(self, resume_id: str, status: str) -> None: ...
    def set_photo(
        self, resume_id: str, photo_asset_id: str | None, expected_revision: int
    ) -> bool: ...
    def uses_asset(self, asset_id: str) -> bool: ...
    def delete_asset(self, asset_id: str) -> None: ...


class JobStore(Protocol):
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
    ) -> JobOpportunity: ...
    def patch_job(self, job_id: str, changes: dict[str, str]) -> JobOpportunity: ...
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
    ) -> JobOpportunity: ...
    def update_job_status(
        self, job_id: str, status: str, note: str = ""
    ) -> JobOpportunity: ...
    def job(self, job_id: str) -> JobOpportunity | None: ...
    def insert_submission(
        self, job_id: str, resume: ResumeVersion
    ) -> JobResumeSubmission: ...
    def uses_asset(self, asset_id: str) -> bool: ...
    def gaps(self) -> tuple[JobSkillGap, ...]: ...
    def upsert_skill_gap(self, gap: JobSkillGap) -> None: ...


class LearningStore(Protocol):
    def add_skill(
        self,
        *,
        name: str,
        category: str = "",
        current_level: int = 0,
        target_level: int = 3,
        notes: str = "",
    ) -> Skill: ...
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
    ) -> LearningTask: ...
    def update_learning_task_status(self, task_id: str, status: str) -> None: ...
    def update_learning_stage(
        self,
        stage_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningStage: ...
    def update_learning_stage_status(
        self, stage_id: str, *, status: str
    ) -> LearningStage: ...
    def update_learning_reference(
        self,
        reference_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningReference: ...
    def skills(self) -> tuple[Skill, ...]: ...
    def skill_exists(self, skill_id: str) -> bool: ...
    def find_or_add_skill(self, *, name: str, category: str = "") -> Skill: ...
    def quest(self, quest_id: str) -> Quest | None: ...
    def quest_evidence(self, quest_id: str) -> tuple[QuestEvidence, ...]: ...
    def mark_quest_started(self, quest_id: str) -> None: ...
    def insert_quest_evidence(self, evidence: QuestEvidence) -> None: ...
    def mark_quest_cleared(self, quest: Quest) -> None: ...
    def seed_career_radar(self) -> None: ...


class CareerStores(Protocol):
    @property
    def profile(self) -> ProfileStore: ...
    @property
    def documents(self) -> DocumentStore: ...
    @property
    def projects(self) -> ProjectStore: ...
    @property
    def resumes(self) -> ResumeStore: ...
    @property
    def jobs(self) -> JobStore: ...
    @property
    def learning(self) -> LearningStore: ...


class UnitOfWork(Protocol):
    def __call__(
        self, *, write: bool = False
    ) -> AbstractContextManager[CareerStores]: ...
