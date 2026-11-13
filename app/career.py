"""SQLite-backed private career cockpit and document vault."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from app.database import (
    WORKSPACE_REGISTRY,
    apply_migrations,
    connect_database,
    snapshot_database,
)
from app.resume_assets import ResumeImage, validate_resume_image
from app.resume_studio import (
    RESUME_TEMPLATE_KEYS,
    StructuredResume,
    deserialize_structured_resume,
    serialize_structured_resume,
    source_fingerprint,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".png", ".jpg", ".jpeg"}
DOCUMENT_KINDS = {"resume", "certificate", "project", "job", "other"}
JOB_STATUS_LABELS = {
    "saved": "待投递", "assessing": "评估中", "applying": "已投递",
    "written_test": "笔试", "interview_1": "一面", "interview_2": "二面",
    "final_interview": "终面", "hr_interview": "HR 面",
    "interviewing": "面试中（未分轮次）", "offer": "Offer",
    "rejected": "未通过", "withdrawn": "已撤回", "archived": "已归档",
}
JOB_STATUSES = set(JOB_STATUS_LABELS)
JOB_INLINE_FIELDS = {
    "company": 160, "title": 160, "status": 40, "applied_on": 10,
    "next_action": 300, "next_action_on": 10, "notes": 20_000,
}
PROJECT_STATUSES = {"draft", "active", "archived"}
RESUME_STATUSES = {"draft", "active", "archived"}
LEARNING_STATUSES = {"backlog", "active", "done", "paused"}
QUEST_STATUSES = {"locked", "available", "active", "cleared"}
CAMPAIGN_STATUSES = {"planned", "active", "completed", "archived"}
REFERENCE_STATUSES = {"backlog", "reading", "building", "verified", "paused"}
LEARNING_PATH_STATUSES = {"active", "completed", "archived"}
LEARNING_STAGE_STATUSES = REFERENCE_STATUSES
SCHEMA_VERSION = 8


def _now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class CareerProfile:
    target_roles: str = ""
    contact: str = ""
    education: str = ""
    experience: str = ""
    certifications: str = ""
    skills: str = ""
    facts: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class PrivateDocument:
    id: str
    kind: str
    original_name: str
    stored_name: str
    media_type: str
    size: int
    sha256: str
    extracted_text: str
    created_at: str


@dataclass(frozen=True)
class ResumeAsset:
    id: str
    source_document_id: str | None
    stored_name: str
    media_type: str
    size: int
    sha256: str
    width: int
    height: int
    created_at: str


@dataclass(frozen=True)
class CareerProject:
    id: str
    name: str
    role: str
    timeframe: str
    summary: str
    technologies: str
    challenge: str
    actions: str
    outcome: str
    evidence: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ResumeVersion:
    id: str
    title: str
    target_role: str
    document_id: str | None
    project_ids: tuple[str, ...]
    status: str
    notes: str
    created_at: str
    updated_at: str
    resume_kind: str = "legacy"
    parent_id: str | None = None
    job_id: str | None = None
    structured_data: str = ""
    source_fingerprint: str = ""
    revision: int = 0
    template_key: str = "ats_single"
    is_primary: int = 0
    photo_asset_id: str | None = None

    @property
    def is_structured(self) -> bool:
        return self.resume_kind in {"master", "tailored"} and bool(
            self.structured_data
        )


@dataclass(frozen=True)
class JobOpportunity:
    id: str
    company: str
    title: str
    location: str
    source_url: str
    jd_text: str
    status: str
    notes: str
    created_at: str
    updated_at: str
    captured_at: str = ""
    is_primary: int = 0
    capability_summary: str = ""
    tier: str = "B"
    applied_on: str = ""
    next_action: str = ""
    next_action_on: str = ""


@dataclass(frozen=True)
class JobStageEvent:
    id: int
    job_id: str
    status: str
    note: str
    created_at: str


@dataclass(frozen=True)
class JobResumeSubmission:
    id: int
    job_id: str
    resume_id: str | None
    revision: int
    title: str
    target_role: str
    structured_data: str
    template_key: str
    photo_asset_id: str | None
    recorded_at: str


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    current_level: int
    target_level: int
    notes: str


@dataclass(frozen=True)
class JobSkillGap:
    job_id: str
    skill_id: str
    importance: int
    evidence: str
    gap_note: str


@dataclass(frozen=True)
class LearningTask:
    id: str
    skill_id: str
    title: str
    status: str
    priority: int
    linked_content_id: str
    linked_project_id: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CapabilityDomain:
    id: str
    title: str
    priority: str
    summary: str
    sort_order: int


@dataclass(frozen=True)
class JobCapability:
    job_id: str
    capability_id: str
    requirement_summary: str
    importance: int


@dataclass(frozen=True)
class LearningReference:
    id: str
    name: str
    repo_url: str
    snapshot_date: str
    week: int
    study_focus: str
    target_modules: str
    deliverable: str
    acceptance_command: str
    status: str
    commit_sha: str
    test_result: str
    reflection: str
    is_optional: int
    created_at: str
    updated_at: str
    archived_at: str


@dataclass(frozen=True)
class LearningPath:
    id: str
    title: str
    summary: str
    status: str
    source_title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LearningStage:
    id: str
    path_id: str
    stage_order: int
    title: str
    objective: str
    focus: str
    deliverable: str
    acceptance_command: str
    status: str
    commit_sha: str
    test_result: str
    reflection: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LearningStageReference:
    id: str
    stage_id: str
    name: str
    repo_url: str
    role: str
    target_modules: str
    sort_order: int


@dataclass(frozen=True)
class LearningCampaign:
    id: str
    name: str
    description: str
    repository_path: str
    status: str
    total_xp: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Quest:
    id: str
    campaign_id: str
    code: str
    title: str
    description: str
    stage_order: int
    prerequisite_id: str | None
    pass_criteria: str
    xp: int
    status: str
    started_at: str | None
    completed_at: str | None
    learning_task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestEvidence:
    id: str
    quest_id: str
    commit_sha: str
    test_result: str
    reflection: str
    evidence_url: str
    created_at: str


@dataclass(frozen=True)
class LLMDisclosure:
    purpose: str
    source_ids: tuple[str, ...]
    outbound_text: str
    target: str


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS profile (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    target_roles TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '', experience TEXT NOT NULL DEFAULT '',
    certifications TEXT NOT NULL DEFAULT '', skills TEXT NOT NULL DEFAULT '',
    facts TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE, media_type TEXT NOT NULL, size INTEGER NOT NULL,
    sha256 TEXT NOT NULL, extracted_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT '',
    timeframe TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
    technologies TEXT NOT NULL DEFAULT '', challenge TEXT NOT NULL DEFAULT '',
    actions TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, target_role TEXT NOT NULL DEFAULT '',
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    project_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
    jd_text TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category TEXT NOT NULL DEFAULT '', current_level INTEGER NOT NULL DEFAULT 0,
    target_level INTEGER NOT NULL DEFAULT 3, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS job_skill_gaps (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    importance INTEGER NOT NULL DEFAULT 3, evidence TEXT NOT NULL DEFAULT '',
    gap_note TEXT NOT NULL DEFAULT '', PRIMARY KEY(job_id, skill_id)
);
CREATE TABLE IF NOT EXISTS learning_tasks (
    id TEXT PRIMARY KEY, skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    title TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 3,
    linked_content_id TEXT NOT NULL DEFAULT '', linked_project_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


CAMPAIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_campaigns (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    repository_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
    total_xp INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quests (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES learning_campaigns(id) ON DELETE CASCADE,
    code TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    stage_order INTEGER NOT NULL, prerequisite_id TEXT REFERENCES quests(id),
    pass_criteria TEXT NOT NULL, xp INTEGER NOT NULL, status TEXT NOT NULL,
    started_at TEXT, completed_at TEXT,
    UNIQUE(campaign_id, code), UNIQUE(campaign_id, stage_order)
);
CREATE TABLE IF NOT EXISTS quest_learning_tasks (
    quest_id TEXT NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    learning_task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY(quest_id, learning_task_id)
);
CREATE TABLE IF NOT EXISTS quest_evidence (
    id TEXT PRIMARY KEY, quest_id TEXT NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL, test_result TEXT NOT NULL,
    reflection TEXT NOT NULL DEFAULT '', evidence_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


CAREER_RADAR_SCHEMA = """
ALTER TABLE jobs ADD COLUMN captured_at TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN capability_summary TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS career_radar_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    baseline_version TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capability_domains (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, priority TEXT NOT NULL,
    summary TEXT NOT NULL, sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS job_capabilities (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    requirement_summary TEXT NOT NULL, importance INTEGER NOT NULL,
    PRIMARY KEY(job_id, capability_id)
);
CREATE TABLE IF NOT EXISTS capability_skills (
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY(capability_id, skill_id)
);
CREATE TABLE IF NOT EXISTS learning_references (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, repo_url TEXT NOT NULL,
    snapshot_date TEXT NOT NULL, week INTEGER NOT NULL,
    study_focus TEXT NOT NULL, target_modules TEXT NOT NULL,
    deliverable TEXT NOT NULL, acceptance_command TEXT NOT NULL,
    status TEXT NOT NULL, commit_sha TEXT NOT NULL DEFAULT '',
    test_result TEXT NOT NULL DEFAULT '', reflection TEXT NOT NULL DEFAULT '',
    is_optional INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_reference_capabilities (
    reference_id TEXT NOT NULL REFERENCES learning_references(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    PRIMARY KEY(reference_id, capability_id)
);
CREATE TABLE IF NOT EXISTS learning_reference_tasks (
    reference_id TEXT NOT NULL REFERENCES learning_references(id) ON DELETE CASCADE,
    learning_task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY(reference_id, learning_task_id)
);
"""


LEARNING_PATH_SCHEMA = """
ALTER TABLE learning_references ADD COLUMN archived_at TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS learning_paths (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','completed','archived')),
    source_title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_stages (
    id TEXT PRIMARY KEY,
    path_id TEXT NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    stage_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    focus TEXT NOT NULL,
    deliverable TEXT NOT NULL,
    acceptance_command TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('backlog','reading','building','verified','paused')),
    commit_sha TEXT NOT NULL DEFAULT '',
    test_result TEXT NOT NULL DEFAULT '',
    reflection TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(path_id, stage_order)
);
CREATE TABLE IF NOT EXISTS learning_stage_references (
    id TEXT PRIMARY KEY,
    stage_id TEXT NOT NULL REFERENCES learning_stages(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    role TEXT NOT NULL,
    target_modules TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    UNIQUE(stage_id, repo_url)
);
CREATE TABLE IF NOT EXISTS learning_stage_capabilities (
    stage_id TEXT NOT NULL REFERENCES learning_stages(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    PRIMARY KEY(stage_id, capability_id)
);
CREATE INDEX IF NOT EXISTS ix_learning_stages_path_order
    ON learning_stages(path_id, stage_order);
PRAGMA user_version = 6;
"""


RESUME_STUDIO_SCHEMA = """
ALTER TABLE resumes ADD COLUMN resume_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE resumes ADD COLUMN parent_id TEXT REFERENCES resumes(id) ON DELETE SET NULL;
ALTER TABLE resumes ADD COLUMN job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE resumes ADD COLUMN structured_data TEXT NOT NULL DEFAULT '';
ALTER TABLE resumes ADD COLUMN source_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE resumes ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE resumes ADD COLUMN template_key TEXT NOT NULL DEFAULT 'ats_single';
ALTER TABLE resumes ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_resumes_primary
    ON resumes(is_primary) WHERE is_primary = 1;
PRAGMA user_version = 4;
"""


RESUME_PHOTO_SCHEMA = """
CREATE TABLE IF NOT EXISTS resume_assets (
    id TEXT PRIMARY KEY,
    source_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    stored_name TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_document_id, sha256)
);
ALTER TABLE resumes ADD COLUMN photo_asset_id TEXT
    REFERENCES resume_assets(id) ON DELETE SET NULL;
PRAGMA user_version = 5;
"""


class CareerRepository:
    """Small transaction-oriented repository for one local author."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.database_path = data_root / "workspace.db"
        self.documents_root = data_root / "documents"
        self.documents_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.resume_assets_root = self.documents_root / "resume-assets"
        self.resume_assets_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.resume_assets_root.chmod(0o700)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def _initialize(self) -> None:
        legacy_version = 0
        if self.database_path.exists():
            with sqlite3.connect(self.database_path) as connection:
                legacy_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="career",
            snapshot_root=self.data_root / "working" / "db-migrations",
            legacy_version=legacy_version,
            migrations={
                1: f"{SCHEMA}\nPRAGMA user_version = 1;",
                2: f"{CAMPAIGN_SCHEMA}\nPRAGMA user_version = 2;",
                3: f"{CAREER_RADAR_SCHEMA}\nPRAGMA user_version = 3;",
                4: RESUME_STUDIO_SCHEMA,
                5: RESUME_PHOTO_SCHEMA,
                6: LEARNING_PATH_SCHEMA,
                7: """ALTER TABLE jobs ADD COLUMN tier TEXT NOT NULL DEFAULT 'B';
                ALTER TABLE jobs ADD COLUMN applied_on TEXT NOT NULL DEFAULT '';
                ALTER TABLE jobs ADD COLUMN next_action TEXT NOT NULL DEFAULT '';
                ALTER TABLE jobs ADD COLUMN next_action_on TEXT NOT NULL DEFAULT '';
                PRAGMA user_version = 7;""",
                8: """CREATE TABLE job_resume_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    resume_id TEXT REFERENCES resumes(id) ON DELETE SET NULL,
                    revision INTEGER NOT NULL, title TEXT NOT NULL,
                    target_role TEXT NOT NULL, structured_data TEXT NOT NULL,
                    template_key TEXT NOT NULL,
                    photo_asset_id TEXT REFERENCES resume_assets(id) ON DELETE SET NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX ix_job_resume_submissions_job ON job_resume_submissions(job_id,id);
                PRAGMA user_version = 8;""",
            },
        )

    def profile(self) -> CareerProfile:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profile WHERE singleton = 1"
            ).fetchone()
        if row is None:
            return CareerProfile()
        data = dict(row)
        data.pop("singleton", None)
        return CareerProfile(**data)

    def save_profile(self, **fields: str) -> CareerProfile:
        allowed = {
            "target_roles",
            "contact",
            "education",
            "experience",
            "certifications",
            "skills",
            "facts",
        }
        cleaned = {key: str(fields.get(key, "")).strip()[:20_000] for key in allowed}
        cleaned["updated_at"] = _now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO profile(singleton,target_roles,contact,education,experience,certifications,skills,facts,updated_at)
                VALUES(1,:target_roles,:contact,:education,:experience,:certifications,:skills,:facts,:updated_at)
                ON CONFLICT(singleton) DO UPDATE SET target_roles=excluded.target_roles, contact=excluded.contact,
                education=excluded.education, experience=excluded.experience, certifications=excluded.certifications,
                skills=excluded.skills, facts=excluded.facts, updated_at=excluded.updated_at""",
                cleaned,
            )
        return self.profile()

    def documents(self, kind: str | None = None) -> tuple[PrivateDocument, ...]:
        sql = "SELECT * FROM documents"
        params: tuple[str, ...] = ()
        if kind:
            sql += " WHERE kind = ?"
            params = (kind,)
        sql += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(PrivateDocument(**dict(row)) for row in rows)

    def document(self, document_id: str) -> PrivateDocument | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return PrivateDocument(**dict(row)) if row else None

    def document_by_sha256(self, digest: str) -> PrivateDocument | None:
        with self.connect() as connection:
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

    def resume_asset(self, asset_id: str) -> ResumeAsset | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM resume_assets WHERE id = ?", (asset_id,)
            ).fetchone()
        return ResumeAsset(**dict(row)) if row else None

    def resume_asset_for_source(
        self, source_document_id: str, sha256: str
    ) -> ResumeAsset | None:
        with self.connect() as connection:
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

    def store_resume_asset(
        self,
        image: ResumeImage | bytes,
        *,
        source_document_id: str = "",
    ) -> ResumeAsset:
        validated = image if isinstance(image, ResumeImage) else validate_resume_image(image)
        if source_document_id and self.document(source_document_id) is None:
            raise ValueError("照片来源文档不存在")
        digest = hashlib.sha256(validated.content).hexdigest()
        if source_document_id:
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM resume_assets WHERE source_document_id=? AND sha256=?",
                    (source_document_id, digest),
                ).fetchone()
            if row is not None:
                return ResumeAsset(**dict(row))
        asset_id = _id("resume-photo")
        stored_name = f"{asset_id}{validated.extension}"
        final_path = self.resume_assets_root / stored_name
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.resume_assets_root, prefix=".resume-photo-", delete=False
            ) as handle:
                temporary_name = handle.name
                handle.write(validated.content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary = Path(temporary_name)
            temporary.chmod(0o600)
            os.replace(temporary, final_path)
            final_path.chmod(0o600)
            asset = ResumeAsset(
                id=asset_id,
                source_document_id=source_document_id or None,
                stored_name=stored_name,
                media_type=validated.media_type,
                size=len(validated.content),
                sha256=digest,
                width=validated.width,
                height=validated.height,
                created_at=_now(),
            )
            self._insert("resume_assets", asset)
            return asset
        except Exception:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

    def delete_resume_asset_if_unreferenced(self, asset_id: str) -> bool:
        """Keep photos referenced by either a live resume or a submitted snapshot."""

        asset = self.resume_asset(asset_id)
        if asset is None:
            return False
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            referenced = connection.execute(
                """SELECT 1 FROM resumes WHERE photo_asset_id=?
                   UNION ALL SELECT 1 FROM job_resume_submissions WHERE photo_asset_id=? LIMIT 1""",
                (asset_id, asset_id),
            ).fetchone()
            if referenced is not None:
                return False
            connection.execute("DELETE FROM resume_assets WHERE id=?", (asset_id,))
        self.resume_asset_path(asset).unlink(missing_ok=True)
        return True

    def delete_document(self, document_id: str, confirmation: str) -> None:
        if confirmation.strip() != "删除文档":
            raise ValueError("请输入“删除文档”进行确认")
        document = self.document(document_id)
        if document is None:
            raise KeyError(document_id)
        if Path(document.stored_name).name != document.stored_name:
            raise ValueError("文档存储路径无效")
        with self.connect() as connection:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        (self.documents_root / document.stored_name).unlink(missing_ok=True)

    def add_document(
        self, *, kind: str, filename: str, content: bytes
    ) -> PrivateDocument:
        if kind not in DOCUMENT_KINDS:
            raise ValueError("文档类型无效")
        extension, media_type, extracted = validate_document(filename, content)
        document_id = _id("doc")
        stored_name = f"{document_id}{extension}"
        path = self.documents_root / stored_name
        path.write_bytes(content)
        path.chmod(0o600)
        document = PrivateDocument(
            id=document_id,
            kind=kind,
            original_name=Path(filename).name[:180],
            stored_name=stored_name,
            media_type=media_type,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            extracted_text=extracted[:100_000],
            created_at=_now(),
        )
        try:
            with self.connect() as connection:
                connection.execute(
                    """INSERT INTO documents(id,kind,original_name,stored_name,media_type,size,sha256,extracted_text,created_at)
                    VALUES(:id,:kind,:original_name,:stored_name,:media_type,:size,:sha256,:extracted_text,:created_at)""",
                    document.__dict__,
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return document

    def projects(self) -> tuple[CareerProject, ...]:
        return self._rows(
            "SELECT * FROM projects ORDER BY updated_at DESC", CareerProject
        )

    def project(self, project_id: str) -> CareerProject | None:
        rows = self._rows(
            "SELECT * FROM projects WHERE id = ?", CareerProject, (project_id,)
        )
        return rows[0] if rows else None

    def add_project(self, **fields: str) -> CareerProject:
        name = str(fields.get("name", "")).strip()
        status = str(fields.get("status", "draft"))
        if not name:
            raise ValueError("项目名称不能为空")
        if status not in PROJECT_STATUSES:
            raise ValueError("项目状态无效")
        stamp = _now()
        project = CareerProject(
            id=_id("project"),
            name=name[:160],
            role=str(fields.get("role", "")).strip()[:160],
            timeframe=str(fields.get("timeframe", "")).strip()[:160],
            summary=str(fields.get("summary", "")).strip()[:10_000],
            technologies=str(fields.get("technologies", "")).strip()[:2000],
            challenge=str(fields.get("challenge", "")).strip()[:10_000],
            actions=str(fields.get("actions", "")).strip()[:10_000],
            outcome=str(fields.get("outcome", "")).strip()[:10_000],
            evidence=str(fields.get("evidence", "")).strip()[:10_000],
            status=status,
            created_at=stamp,
            updated_at=stamp,
        )
        self._insert("projects", project)
        return project

    def update_project(self, project_id: str, **fields: str) -> CareerProject:
        current = self.project(project_id)
        if current is None:
            raise KeyError(project_id)
        status = str(fields.get("status", current.status))
        name = str(fields.get("name", current.name)).strip()
        if status not in PROJECT_STATUSES or not name:
            raise ValueError("项目名称或状态无效")
        values = {
            "id": project_id,
            "name": name[:160],
            "role": str(fields.get("role", current.role)).strip()[:160],
            "timeframe": str(fields.get("timeframe", current.timeframe)).strip()[:160],
            "summary": str(fields.get("summary", current.summary)).strip()[:10_000],
            "technologies": str(
                fields.get("technologies", current.technologies)
            ).strip()[:2000],
            "challenge": str(fields.get("challenge", current.challenge)).strip()[
                :10_000
            ],
            "actions": str(fields.get("actions", current.actions)).strip()[:10_000],
            "outcome": str(fields.get("outcome", current.outcome)).strip()[:10_000],
            "evidence": str(fields.get("evidence", current.evidence)).strip()[:10_000],
            "status": status,
            "updated_at": _now(),
        }
        assignments = ",".join(f"{key}=:{key}" for key in values if key != "id")
        with self.connect() as connection:
            connection.execute(
                f"UPDATE projects SET {assignments} WHERE id=:id", values
            )
        return self.project(project_id)  # type: ignore[return-value]

    def resumes(self) -> tuple[ResumeVersion, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM resumes ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(self._resume(row) for row in rows)

    def resume(self, resume_id: str) -> ResumeVersion | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM resumes WHERE id = ?", (resume_id,)
            ).fetchone()
        return self._resume(row) if row is not None else None

    def primary_resume(self) -> ResumeVersion | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM resumes WHERE is_primary = 1 LIMIT 1"
            ).fetchone()
        return self._resume(row) if row is not None else None

    def primary_resume_for_document(self, document_id: str) -> ResumeVersion | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM resumes WHERE is_primary=1 AND document_id=? LIMIT 1",
                (document_id,),
            ).fetchone()
        return self._resume(row) if row is not None else None

    @staticmethod
    def structured_resume(resume: ResumeVersion) -> StructuredResume:
        if not resume.is_structured:
            raise ValueError("该记录不是结构化简历")
        return deserialize_structured_resume(resume.structured_data)

    def resume_source_fingerprint(
        self, project_ids: tuple[str, ...]
    ) -> str:
        project_lookup = {project.id: project for project in self.projects()}
        selected = tuple(
            project_lookup[project_id]
            for project_id in project_ids
            if project_id in project_lookup
        )
        return source_fingerprint(self.profile(), selected).digest

    def resume_source_is_current(self, resume: ResumeVersion) -> bool:
        if not resume.is_structured or not resume.source_fingerprint:
            return False
        return resume.source_fingerprint == self.resume_source_fingerprint(
            resume.project_ids
        )

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
        if resume_kind not in {"master", "tailored"}:
            raise ValueError("结构化简历类型无效")
        if status not in RESUME_STATUSES:
            raise ValueError("简历状态无效")
        if template_key not in RESUME_TEMPLATE_KEYS:
            raise ValueError("简历模板无效")
        if not title.strip():
            raise ValueError("简历名称不能为空")
        if document_id and self.document(document_id) is None:
            raise ValueError("关联文档不存在")
        parent = self.resume(parent_id) if parent_id else None
        if resume_kind == "tailored" and (
            parent is None or parent.resume_kind != "master"
        ):
            raise ValueError("定制简历必须关联有效主简历")
        if job_id and self.job(job_id) is None:
            raise ValueError("关联职位不存在")
        if resume_kind == "tailored" and not job_id:
            raise ValueError("定制简历必须关联目标职位")
        if is_primary and resume_kind != "master":
            raise ValueError("只有主简历可以设为当前主版本")
        existing_primary = self.primary_resume() if is_primary else None
        if existing_primary is not None:
            if document_id and existing_primary.document_id == document_id:
                return existing_primary
            raise ValueError("当前已经存在主简历，请先使用现有主简历")
        if photo_asset_id and self.resume_asset(photo_asset_id) is None:
            raise ValueError("简历照片不存在")
        if resume_kind == "tailored" and parent is not None and not photo_asset_id:
            photo_asset_id = parent.photo_asset_id or ""

        project_ids = tuple(
            dict.fromkeys(
                str(row.get("project_id", ""))
                for row in structured.projects
                if str(row.get("project_id", ""))
            )
        )
        known_projects = {project.id for project in self.projects()}
        if not set(project_ids) <= known_projects:
            raise ValueError("简历引用了不存在的项目证据")
        stamp = _now()
        resume = ResumeVersion(
            id=_id("resume"),
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
            source_fingerprint=self.resume_source_fingerprint(project_ids),
            revision=1,
            template_key=template_key,
            is_primary=int(is_primary),
            photo_asset_id=photo_asset_id or None,
        )
        payload = resume.__dict__ | {
            "project_ids": json.dumps(resume.project_ids, ensure_ascii=False)
        }
        self._insert("resumes", payload)
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
        current = self.resume(resume_id)
        if current is None or not current.is_structured:
            raise KeyError(resume_id)
        if not title.strip():
            raise ValueError("简历名称不能为空")
        template_key = template_key or current.template_key
        if template_key not in RESUME_TEMPLATE_KEYS:
            raise ValueError("简历模板无效")
        project_ids = tuple(
            dict.fromkeys(
                str(row.get("project_id", ""))
                for row in structured.projects
                if str(row.get("project_id", ""))
            )
        )
        known_projects = {project.id for project in self.projects()}
        if not set(project_ids) <= known_projects:
            raise ValueError("简历引用了不存在的项目证据")
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE resumes SET title=?,target_role=?,notes=?,project_ids=?,
                structured_data=?,source_fingerprint=?,template_key=?,
                revision=revision+1,updated_at=?
                WHERE id=? AND revision=?""",
                (
                    title.strip()[:160],
                    target_role.strip()[:160],
                    notes.strip()[:10_000],
                    json.dumps(project_ids, ensure_ascii=False),
                    serialize_structured_resume(structured),
                    self.resume_source_fingerprint(project_ids),
                    template_key,
                    _now(),
                    resume_id,
                    expected_revision,
                ),
            )
        if cursor.rowcount != 1:
            if self.resume(resume_id) is None:
                raise KeyError(resume_id)
            raise RuntimeError("简历已在其他页面更新，请刷新后合并修改")
        return self.resume(resume_id)  # type: ignore[return-value]

    def update_resume_photo(
        self,
        resume_id: str,
        *,
        expected_revision: int,
        photo_asset_id: str = "",
    ) -> ResumeVersion:
        current = self.resume(resume_id)
        if current is None or not current.is_structured:
            raise KeyError(resume_id)
        if photo_asset_id and self.resume_asset(photo_asset_id) is None:
            raise ValueError("简历照片不存在")
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE resumes SET photo_asset_id=?,revision=revision+1,updated_at=?
                WHERE id=? AND revision=?""",
                (photo_asset_id or None, _now(), resume_id, expected_revision),
            )
        if cursor.rowcount != 1:
            if self.resume(resume_id) is None:
                raise KeyError(resume_id)
            raise RuntimeError("简历已在其他页面更新，请刷新后重试")
        return self.resume(resume_id)  # type: ignore[return-value]

    def update_resume_status(self, resume_id: str, status: str) -> None:
        if status not in RESUME_STATUSES:
            raise ValueError("简历状态无效")
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE resumes SET status = ?,
                is_primary = CASE WHEN ? = 'archived' THEN 0 ELSE is_primary END,
                updated_at = ? WHERE id = ?""",
                (status, status, _now(), resume_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(resume_id)

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
        if document_id and self.document(document_id) is None:
            raise ValueError("关联文档不存在")
        known_projects = {project.id for project in self.projects()}
        if not set(project_ids) <= known_projects:
            raise ValueError("关联项目不存在")
        stamp = _now()
        resume = ResumeVersion(
            _id("resume"),
            title.strip()[:160],
            target_role.strip()[:160],
            document_id or None,
            tuple(project_ids),
            status,
            notes.strip()[:10_000],
            stamp,
            stamp,
        )
        payload = resume.__dict__ | {
            "project_ids": json.dumps(resume.project_ids, ensure_ascii=False)
        }
        self._insert("resumes", payload)
        return resume

    def confirmed_skill_names(self, job_id: str) -> tuple[str, ...]:
        if self.job(job_id) is None:
            raise KeyError(job_id)
        skills = {skill.id: skill.name for skill in self.skills()}
        return tuple(
            skills[gap.skill_id]
            for gap in self.gaps()
            if gap.job_id == job_id and gap.skill_id in skills
        )

    def jobs(self) -> tuple[JobOpportunity, ...]:
        return self._rows("SELECT * FROM jobs ORDER BY updated_at DESC, rowid DESC", JobOpportunity)

    def job(self, job_id: str) -> JobOpportunity | None:
        rows = self._rows("SELECT * FROM jobs WHERE id = ?", JobOpportunity, (job_id,))
        return rows[0] if rows else None

    @staticmethod
    def _validate_job(*, company: str, title: str, status: str, tier: str,
                      applied_on: str, next_action_on: str) -> None:
        if not company.strip() or not title.strip():
            raise ValueError("公司和岗位不能为空")
        if status not in JOB_STATUSES:
            raise ValueError("职位状态无效")
        if tier not in {"A", "B", "C"}:
            raise ValueError("岗位档位只能是 A、B 或 C")
        for value in (applied_on, next_action_on):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as error:
                    raise ValueError("日期格式无效") from error

    def add_job(
        self, *, company: str, title: str, jd_text: str = "",
        location: str = "", source_url: str = "", notes: str = "",
        tier: str = "B", applied_on: str = "", next_action: str = "",
        next_action_on: str = "", status: str = "saved",
        creation_token: str = "",
    ) -> JobOpportunity:
        self._validate_job(company=company, title=title, status=status, tier=tier,
                           applied_on=applied_on, next_action_on=next_action_on)
        stamp = _now()
        try:
            job_id = f"job-inline-{UUID(creation_token).hex}" if creation_token else _id("job")
        except (ValueError, AttributeError) as error:
            raise ValueError("新记录标识无效，请刷新页面后重试") from error
        job = JobOpportunity(
            job_id, company.strip()[:160], title.strip()[:160],
            location.strip()[:160], source_url.strip()[:1000], jd_text.strip()[:100_000],
            status, notes.strip()[:20_000], stamp, stamp,
            tier=tier, applied_on=applied_on, next_action=next_action.strip()[:300],
            next_action_on=next_action_on,
        )
        data = job.__dict__
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if creation_token:
                existing = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if existing is not None:
                    return JobOpportunity(**dict(existing))
            connection.execute(
                f"INSERT INTO jobs({','.join(data)}) VALUES({','.join(':'+key for key in data)})", data
            )
            connection.execute(
                "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                (job.id, status, "职位已加入工作台", stamp),
            )
        return job

    def patch_job(self, job_id: str, changes: dict[str, str]) -> JobOpportunity:
        """Update only table fields, preserving all other current values under one lock."""
        if not changes or set(changes) - JOB_INLINE_FIELDS.keys():
            raise ValueError("只能修改投递表中的字段")
        if any(not isinstance(value, str) for value in changes.values()):
            raise ValueError("字段内容必须是文本")
        normalized = {key: (value.strip() if key in {"applied_on", "next_action_on", "status"}
                            else value.strip()[:JOB_INLINE_FIELDS[key]]) for key, value in changes.items()}
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            current = dict(row)
            merged = current | normalized
            self._validate_job(**{key: merged[key] for key in (
                "company", "title", "status", "tier", "applied_on", "next_action_on",
            )})
            changed = {key: value for key, value in normalized.items() if current[key] != value}
            if changed:
                stamp = _now()
                connection.execute(
                    f"UPDATE jobs SET {','.join(key+'=?' for key in changed)},updated_at=? WHERE id=?",
                    (*changed.values(), stamp, job_id),
                )
                if "status" in changed:
                    connection.execute(
                        "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                        (job_id, changed["status"], "", stamp),
                    )
            saved = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return JobOpportunity(**dict(saved))

    def update_job(self, job_id: str, *, company: str, title: str, status: str,
                   tier: str, applied_on: str, next_action: str, next_action_on: str,
                   location: str = "", source_url: str = "", jd_text: str = "",
                   notes: str = "", stage_note: str = "") -> JobOpportunity:
        self._validate_job(company=company, title=title, status=status, tier=tier,
                           applied_on=applied_on, next_action_on=next_action_on)
        stamp = _now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if old is None:
                raise KeyError(job_id)
            connection.execute(
                """UPDATE jobs SET company=?,title=?,status=?,tier=?,applied_on=?,
                   next_action=?,next_action_on=?,location=?,source_url=?,jd_text=?,notes=?,updated_at=?
                   WHERE id=?""",
                (company.strip()[:160], title.strip()[:160], status, tier, applied_on,
                 next_action.strip()[:300], next_action_on, location.strip()[:160],
                 source_url.strip()[:1000], jd_text.strip()[:100_000], notes.strip()[:20_000], stamp, job_id),
            )
            if old["status"] != status:
                connection.execute(
                    "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                    (job_id, status, stage_note.strip()[:2000], stamp),
                )
        return self.job(job_id)  # type: ignore[return-value]

    def update_job_status(self, job_id: str, status: str, note: str = "") -> JobOpportunity:
        if status not in JOB_STATUSES:
            raise ValueError("职位状态无效")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if old is None:
                raise KeyError(job_id)
            if old["status"] != status:
                stamp = _now()
                connection.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?", (status, stamp, job_id))
                connection.execute(
                    "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                    (job_id, status, note.strip()[:2000], stamp),
                )
        return self.job(job_id)  # type: ignore[return-value]

    def job_submissions(self, job_id: str | None = None) -> tuple[JobResumeSubmission, ...]:
        where = " WHERE job_id=?" if job_id is not None else ""
        return self._rows("SELECT * FROM job_resume_submissions" + where + " ORDER BY id DESC",
                          JobResumeSubmission, (job_id,) if job_id is not None else ())

    def job_submission(self, submission_id: int) -> JobResumeSubmission | None:
        rows = self._rows("SELECT * FROM job_resume_submissions WHERE id=?",
                          JobResumeSubmission, (submission_id,))
        return rows[0] if rows else None

    def record_job_submission(self, job_id: str, resume_id: str) -> JobResumeSubmission:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
                raise KeyError(job_id)
            row = connection.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
            if row is None:
                raise ValueError("请选择有效简历")
            resume = self._resume(row)
            if not resume.is_structured or not (
                resume.resume_kind == "master" or
                (resume.resume_kind == "tailored" and resume.job_id == job_id)
            ):
                raise ValueError("只能记录主简历或该岗位的定制简历")
            cursor = connection.execute(
                """INSERT INTO job_resume_submissions(job_id,resume_id,revision,title,target_role,
                   structured_data,template_key,photo_asset_id,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (job_id, resume.id, resume.revision, resume.title, resume.target_role,
                 resume.structured_data, resume.template_key, resume.photo_asset_id, _now()),
            )
            submission_id = cursor.lastrowid
        return self.job_submission(submission_id)  # type: ignore[arg-type,return-value]

    def update_job_plan(
        self, job_id: str, *, tier: str, applied_on: str,
        next_action: str, next_action_on: str,
    ) -> JobOpportunity:
        if tier not in {"A", "B", "C"}:
            raise ValueError("岗位档位只能是 A、B 或 C")
        if self.job(job_id) is None:
            raise KeyError(job_id)
        for value in (applied_on, next_action_on):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as error:
                    raise ValueError("日期格式无效") from error
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET tier=?,applied_on=?,next_action=?,next_action_on=?,updated_at=? WHERE id=?",
                (tier, applied_on, next_action.strip()[:300], next_action_on, _now(), job_id),
            )
        return self.job(job_id)  # type: ignore[return-value]

    def add_job_event(self, job_id: str, status: str, note: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                (job_id, status, note.strip()[:2000], _now()),
            )

    def job_events(self, job_id: str) -> tuple[JobStageEvent, ...]:
        return self._rows(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY id DESC",
            JobStageEvent,
            (job_id,),
        )

    def skills(self) -> tuple[Skill, ...]:
        return self._rows("SELECT * FROM skills ORDER BY name COLLATE NOCASE", Skill)

    def skill_by_name(self, name: str) -> Skill | None:
        rows = self._rows(
            "SELECT * FROM skills WHERE name = ? COLLATE NOCASE",
            Skill,
            (name.strip(),),
        )
        return rows[0] if rows else None

    def find_or_add_skill(self, *, name: str, category: str = "") -> Skill:
        existing = self.skill_by_name(name)
        return existing or self.add_skill(name=name, category=category)

    def add_skill(
        self,
        *,
        name: str,
        category: str = "",
        current_level: int = 0,
        target_level: int = 3,
        notes: str = "",
    ) -> Skill:
        if (
            not name.strip()
            or current_level not in range(6)
            or target_level not in range(6)
        ):
            raise ValueError("技能名称或等级无效")
        skill = Skill(
            _id("skill"),
            name.strip()[:120],
            category.strip()[:120],
            current_level,
            target_level,
            notes.strip()[:5000],
        )
        try:
            self._insert("skills", skill)
        except sqlite3.IntegrityError as error:
            raise ValueError("该技能已经存在") from error
        return skill

    def set_job_skill_gap(
        self,
        *,
        job_id: str,
        skill_id: str,
        importance: int,
        evidence: str = "",
        gap_note: str = "",
    ) -> None:
        if (
            self.job(job_id) is None
            or skill_id not in {skill.id for skill in self.skills()}
            or importance not in range(1, 6)
        ):
            raise ValueError("职位、技能或重要度无效")
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO job_skill_gaps(job_id,skill_id,importance,evidence,gap_note) VALUES(?,?,?,?,?)
                ON CONFLICT(job_id,skill_id) DO UPDATE SET importance=excluded.importance,evidence=excluded.evidence,gap_note=excluded.gap_note""",
                (
                    job_id,
                    skill_id,
                    importance,
                    evidence.strip()[:5000],
                    gap_note.strip()[:5000],
                ),
            )

    def gaps(self) -> tuple[JobSkillGap, ...]:
        return self._rows(
            "SELECT * FROM job_skill_gaps ORDER BY importance DESC", JobSkillGap
        )

    def learning_tasks(self) -> tuple[LearningTask, ...]:
        return self._rows(
            "SELECT * FROM learning_tasks ORDER BY priority DESC, updated_at DESC",
            LearningTask,
        )

    def capability_domains(self) -> tuple[CapabilityDomain, ...]:
        return self._rows(
            "SELECT * FROM capability_domains ORDER BY sort_order", CapabilityDomain
        )

    def job_capabilities(self) -> tuple[JobCapability, ...]:
        return self._rows(
            "SELECT * FROM job_capabilities ORDER BY importance DESC, capability_id",
            JobCapability,
        )

    def capability_skill_ids(self) -> dict[str, tuple[str, ...]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT capability_id,skill_id FROM capability_skills ORDER BY skill_id"
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["capability_id"], []).append(row["skill_id"])
        return {key: tuple(values) for key, values in result.items()}

    def learning_references(self) -> tuple[LearningReference, ...]:
        return self._rows(
            "SELECT * FROM learning_references ORDER BY is_optional, week, name",
            LearningReference,
        )

    def learning_reference(self, reference_id: str) -> LearningReference | None:
        rows = self._rows(
            "SELECT * FROM learning_references WHERE id = ?",
            LearningReference,
            (reference_id,),
        )
        return rows[0] if rows else None

    def learning_paths(self) -> tuple[LearningPath, ...]:
        return self._rows(
            "SELECT * FROM learning_paths ORDER BY created_at, id",
            LearningPath,
        )

    def learning_path(self, path_id: str) -> LearningPath | None:
        rows = self._rows(
            "SELECT * FROM learning_paths WHERE id = ?",
            LearningPath,
            (path_id,),
        )
        return rows[0] if rows else None

    def learning_stages(self, path_id: str | None = None) -> tuple[LearningStage, ...]:
        if path_id:
            return self._rows(
                "SELECT * FROM learning_stages WHERE path_id = ? ORDER BY stage_order",
                LearningStage,
                (path_id,),
            )
        return self._rows(
            "SELECT * FROM learning_stages ORDER BY path_id, stage_order",
            LearningStage,
        )

    def learning_stage(self, stage_id: str) -> LearningStage | None:
        rows = self._rows(
            "SELECT * FROM learning_stages WHERE id = ?",
            LearningStage,
            (stage_id,),
        )
        return rows[0] if rows else None

    def learning_stage_references(
        self, stage_id: str | None = None,
    ) -> tuple[LearningStageReference, ...]:
        if stage_id:
            return self._rows(
                "SELECT * FROM learning_stage_references WHERE stage_id = ? ORDER BY sort_order, name",
                LearningStageReference,
                (stage_id,),
            )
        return self._rows(
            "SELECT * FROM learning_stage_references ORDER BY stage_id, sort_order, name",
            LearningStageReference,
        )

    def learning_stage_capability_ids(self) -> dict[str, tuple[str, ...]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT stage_id,capability_id FROM learning_stage_capabilities ORDER BY capability_id"
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["stage_id"], []).append(row["capability_id"])
        return {key: tuple(values) for key, values in result.items()}

    def update_learning_stage(
        self,
        stage_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningStage:
        if status not in LEARNING_STAGE_STATUSES:
            raise ValueError("学习阶段状态无效")
        stage = self.learning_stage(stage_id)
        if stage is None:
            raise KeyError(stage_id)
        with self.connect() as connection:
            connection.execute(
                """UPDATE learning_stages
                SET status=?,commit_sha=?,test_result=?,reflection=?,updated_at=?
                WHERE id=?""",
                (
                    status,
                    commit_sha.strip()[:120],
                    test_result.strip()[:20_000],
                    reflection.strip()[:20_000],
                    _now(),
                    stage_id,
                ),
            )
        return self.learning_stage(stage_id)  # type: ignore[return-value]

    def update_learning_stage_status(
        self,
        stage_id: str,
        *,
        status: str,
    ) -> LearningStage:
        """Update only roadmap progress without touching preserved evidence."""

        if status not in LEARNING_STAGE_STATUSES:
            raise ValueError("学习阶段状态无效")
        if self.learning_stage(stage_id) is None:
            raise KeyError(stage_id)
        with self.connect() as connection:
            connection.execute(
                "UPDATE learning_stages SET status=?,updated_at=? WHERE id=?",
                (status, _now(), stage_id),
            )
        return self.learning_stage(stage_id)  # type: ignore[return-value]

    def reference_capability_ids(self) -> dict[str, tuple[str, ...]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT reference_id,capability_id FROM learning_reference_capabilities ORDER BY capability_id"
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["reference_id"], []).append(row["capability_id"])
        return {key: tuple(values) for key, values in result.items()}

    def reference_task_ids(self) -> dict[str, tuple[str, ...]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT reference_id,learning_task_id FROM learning_reference_tasks ORDER BY learning_task_id"
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["reference_id"], []).append(row["learning_task_id"])
        return {key: tuple(values) for key, values in result.items()}

    def update_learning_reference(
        self,
        reference_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningReference:
        if status not in REFERENCE_STATUSES:
            raise ValueError("研读状态无效")
        if self.learning_reference(reference_id) is None:
            raise KeyError(reference_id)
        values = (
            status,
            commit_sha.strip()[:120],
            test_result.strip()[:20_000],
            reflection.strip()[:20_000],
            _now(),
            reference_id,
        )
        with self.connect() as connection:
            connection.execute(
                """UPDATE learning_references
                SET status=?,commit_sha=?,test_result=?,reflection=?,updated_at=?
                WHERE id=?""",
                values,
            )
        return self.learning_reference(reference_id)  # type: ignore[return-value]

    def seed_career_radar(self) -> None:
        """Install the dated manual baseline without resetting mutable progress."""

        from app.career_radar import (
            BASELINE_VERSION,
            CAPABILITY_DOMAINS,
            CAPABILITY_SKILL_NAMES,
            JOB_CAPABILITIES,
            JOB_SNAPSHOTS,
            LEARNING_PATH,
            LEARNING_STAGES,
            REFERENCE_PROJECTS,
            SNAPSHOT_DATE,
        )

        stamp = _now()
        with self.connect() as connection:
            state = connection.execute(
                "SELECT baseline_version FROM career_radar_state WHERE singleton=1"
            ).fetchone()
            first_application = state is None
            if first_application:
                connection.execute(
                    "UPDATE learning_campaigns SET status='archived',updated_at=? WHERE id='agent-reliability-arena'",
                    (stamp,),
                )
                connection.execute(
                    "UPDATE learning_tasks SET status='paused',updated_at=? WHERE status IN ('backlog','active')",
                    (stamp,),
                )

            for capability_id, title, priority, summary, sort_order in CAPABILITY_DOMAINS:
                connection.execute(
                    """INSERT INTO capability_domains(id,title,priority,summary,sort_order)
                    VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,priority=excluded.priority,
                    summary=excluded.summary,sort_order=excluded.sort_order""",
                    (capability_id, title, priority, summary, sort_order),
                )

            for snapshot in JOB_SNAPSHOTS:
                connection.execute(
                    """INSERT INTO jobs(
                    id,company,title,location,source_url,jd_text,status,notes,
                    created_at,updated_at,captured_at,is_primary,capability_summary)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    company=excluded.company,title=excluded.title,
                    source_url=excluded.source_url,jd_text=excluded.jd_text,
                    captured_at=excluded.captured_at,is_primary=excluded.is_primary,
                    capability_summary=excluded.capability_summary""",
                    (
                        snapshot["id"], snapshot["company"], snapshot["title"], "",
                        snapshot["source_url"], snapshot["jd_text"], "saved", "",
                        stamp, stamp, SNAPSHOT_DATE, snapshot["is_primary"],
                        snapshot["capability_summary"],
                    ),
                )
                for capability_id, requirement in JOB_CAPABILITIES[snapshot["id"]].items():
                    connection.execute(
                        """INSERT INTO job_capabilities(job_id,capability_id,requirement_summary,importance)
                        VALUES(?,?,?,?) ON CONFLICT(job_id,capability_id) DO UPDATE SET
                        requirement_summary=excluded.requirement_summary,importance=excluded.importance""",
                        (snapshot["id"], capability_id, requirement, 5 if snapshot["is_primary"] else 3),
                    )

            skill_ids: dict[str, str] = {}
            existing = {
                row["name"].casefold(): row["id"]
                for row in connection.execute("SELECT id,name FROM skills").fetchall()
            }
            for names in CAPABILITY_SKILL_NAMES.values():
                for name in names:
                    skill_id = existing.get(name.casefold())
                    if skill_id is None:
                        skill_id = f"radar-skill-{hashlib.sha256(name.encode()).hexdigest()[:10]}"
                        connection.execute(
                            """INSERT OR IGNORE INTO skills(id,name,category,current_level,target_level,notes)
                            VALUES(?,?,?,?,?,?)""",
                            (skill_id, name, "岗位雷达", 0, 3, "由 2026-08-21 岗位基线关联。"),
                        )
                    skill_ids[name] = skill_id
            for capability_id, names in CAPABILITY_SKILL_NAMES.items():
                for name in names:
                    connection.execute(
                        "INSERT OR IGNORE INTO capability_skills(capability_id,skill_id) VALUES(?,?)",
                        (capability_id, skill_ids[name]),
                    )

            for reference in REFERENCE_PROJECTS:
                connection.execute(
                    """INSERT INTO learning_references(
                    id,name,repo_url,snapshot_date,week,study_focus,target_modules,
                    deliverable,acceptance_command,status,commit_sha,test_result,
                    reflection,is_optional,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,'backlog','','','',?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,repo_url=excluded.repo_url,
                    snapshot_date=excluded.snapshot_date,week=excluded.week,
                    study_focus=excluded.study_focus,target_modules=excluded.target_modules,
                    deliverable=excluded.deliverable,
                    acceptance_command=excluded.acceptance_command,is_optional=excluded.is_optional""",
                    (
                        reference["id"], reference["name"], reference["repo_url"],
                        SNAPSHOT_DATE, reference["week"], reference["study_focus"],
                        reference["target_modules"], reference["deliverable"],
                        reference["acceptance_command"], reference.get("is_optional", 0),
                        stamp, stamp,
                    ),
                )
                for capability_id in reference["capabilities"]:
                    connection.execute(
                        "INSERT OR IGNORE INTO learning_reference_capabilities(reference_id,capability_id) VALUES(?,?)",
                        (reference["id"], capability_id),
                    )
                if reference.get("is_optional"):
                    continue
                task_id = f"radar-week-{reference['week']}"
                connection.execute(
                    """INSERT INTO learning_tasks(
                    id,skill_id,title,status,priority,linked_content_id,
                    linked_project_id,notes,created_at,updated_at)
                    VALUES(?,?,?,'backlog',5,'','',?,?,?) ON CONFLICT(id) DO UPDATE SET
                    skill_id=excluded.skill_id,title=excluded.title,
                    priority=excluded.priority,notes=excluded.notes""",
                    (
                        task_id, skill_ids[reference["skill"]],
                        f"第 {reference['week']} 周：{reference['name']}",
                        reference["deliverable"], stamp, stamp,
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO learning_reference_tasks(reference_id,learning_task_id) VALUES(?,?)",
                    (reference["id"], task_id),
                )

            # The original four-week route remains readable as history.  Its
            # mutable evidence is deliberately untouched.
            connection.execute(
                """UPDATE learning_references
                SET archived_at=CASE WHEN archived_at='' THEN ? ELSE archived_at END
                WHERE archived_at=''""",
                (stamp,),
            )

            connection.execute(
                """INSERT INTO learning_paths(
                id,title,summary,status,source_title,created_at,updated_at)
                VALUES(?,?,?,'active',?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,summary=excluded.summary,
                source_title=excluded.source_title,updated_at=excluded.updated_at""",
                (
                    LEARNING_PATH["id"],
                    LEARNING_PATH["title"],
                    LEARNING_PATH["summary"],
                    LEARNING_PATH["source_title"],
                    stamp,
                    stamp,
                ),
            )
            for stage in LEARNING_STAGES:
                connection.execute(
                    """INSERT INTO learning_stages(
                    id,path_id,stage_order,title,objective,focus,deliverable,
                    acceptance_command,status,commit_sha,test_result,reflection,
                    created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,'backlog','','','',?,?)
                    ON CONFLICT(id) DO UPDATE SET
                    path_id=excluded.path_id,stage_order=excluded.stage_order,
                    title=excluded.title,objective=excluded.objective,
                    focus=excluded.focus,deliverable=excluded.deliverable,
                    acceptance_command=excluded.acceptance_command""",
                    (
                        stage["id"],
                        LEARNING_PATH["id"],
                        stage["order"],
                        stage["title"],
                        stage["objective"],
                        stage["focus"],
                        stage["deliverable"],
                        stage["acceptance_command"],
                        stamp,
                        stamp,
                    ),
                )
                for sort_order, reference in enumerate(stage["references"], start=1):
                    connection.execute(
                        """INSERT INTO learning_stage_references(
                        id,stage_id,name,repo_url,role,target_modules,sort_order)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        stage_id=excluded.stage_id,name=excluded.name,
                        repo_url=excluded.repo_url,role=excluded.role,
                        target_modules=excluded.target_modules,
                        sort_order=excluded.sort_order""",
                        (
                            reference["id"],
                            stage["id"],
                            reference["name"],
                            reference["repo_url"],
                            reference["role"],
                            reference["target_modules"],
                            sort_order,
                        ),
                    )
                for capability_id in stage["capabilities"]:
                    connection.execute(
                        """INSERT OR IGNORE INTO learning_stage_capabilities(
                        stage_id,capability_id) VALUES(?,?)""",
                        (stage["id"], capability_id),
                    )

            connection.execute(
                """INSERT INTO career_radar_state(singleton,baseline_version,applied_at)
                VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET baseline_version=excluded.baseline_version""",
                (BASELINE_VERSION, stamp),
            )

    def update_learning_task_status(self, task_id: str, status: str) -> None:
        if status not in LEARNING_STATUSES:
            raise ValueError("学习任务状态无效")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE learning_tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), task_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(task_id)

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
        if skill_id not in {skill.id for skill in self.skills()} or not title.strip():
            raise ValueError("技能或学习任务标题无效")
        if status not in LEARNING_STATUSES or priority not in range(1, 6):
            raise ValueError("学习任务状态或优先级无效")
        stamp = _now()
        task = LearningTask(
            _id("task"),
            skill_id,
            title.strip()[:200],
            status,
            priority,
            linked_content_id.strip()[:160],
            linked_project_id.strip()[:160],
            notes.strip()[:10_000],
            stamp,
            stamp,
        )
        self._insert("learning_tasks", task)
        return task

    def seed_agent_reliability_campaign(self, repository_path: str) -> LearningCampaign:
        """Create the public-project quest map once and only link existing tasks."""

        campaign_id = "agent-reliability-arena"
        stamp = _now()
        quests = (
            (
                "prologue",
                "序章：点火",
                "建立 Monorepo、Compose、CI 与架构边界。",
                "一条命令启动；前后端健康检查和 CI 全绿。",
                50,
            ),
            (
                "lv1",
                "Lv.1：召唤 Agent",
                "打通模型适配器、最小 Agent、LangGraph Agent 与假模型。",
                "基础工具循环可运行；超时、步数和非法输出有测试。",
                100,
            ),
            (
                "lv2",
                "Lv.2：副本工厂",
                "完成场景规范、隔离工具网关和 12 个虚构副本。",
                "副本可重复初始化；Run 无法越过沙箱。",
                120,
            ),
            (
                "lv3",
                "Lv.3：时间观测者",
                "建立可回放 Trace、指标、SSE 与轨迹界面。",
                "每次工具调用可顺序回放；敏感字段完成脱敏。",
                120,
            ),
            (
                "lv4",
                "Lv.4：裁判系统",
                "完成确定性评分、三次重复、方差与失败分类。",
                "冻结 Run 重算一致；Judge 不修改核心分。",
                140,
            ),
            (
                "lv5",
                "Lv.5：竞技场开门",
                "完成并行锦标赛、排行榜、Run 对比和恢复。",
                "2 Runtime × 2 模型 × 12 场景 × 3 次可执行。",
                140,
            ),
            (
                "lv6",
                "Lv.6：暗黑副本",
                "覆盖注入、越界、秘密外泄和权限升级。",
                "受保护秘密零泄漏；危险动作等待人工决策。",
                140,
            ),
            (
                "lv7",
                "Lv.7：铸甲",
                "补齐迁移、幂等、健康检查、容器与恢复测试。",
                "Worker 重启可恢复；重复请求不生成重复 Run。",
                90,
            ),
            (
                "boss",
                "Boss：公开赛",
                "发布 v0.1.0、冻结榜单、Pages、README 与演示。",
                "面试官两分钟理解价值；仓库无密钥与私人数据。",
                100,
            ),
        )
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO learning_campaigns(id,name,description,repository_path,status,total_xp,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET repository_path=excluded.repository_path,updated_at=excluded.updated_at""",
                (
                    campaign_id,
                    "Agent Reliability Arena",
                    "30 个工作日构建工具型 Agent 可靠性竞技场。XP 只由验收证据获得。",
                    repository_path.strip()[:1000],
                    "active",
                    1000,
                    stamp,
                    stamp,
                ),
            )
            prerequisite_id = None
            for stage_order, (code, title, description, pass_criteria, xp) in enumerate(
                quests, 1
            ):
                quest_id = f"ara-{code}"
                initial_status = "available" if stage_order == 1 else "locked"
                connection.execute(
                    """INSERT INTO quests(id,campaign_id,code,title,description,stage_order,prerequisite_id,pass_criteria,xp,status)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""",
                    (
                        quest_id,
                        campaign_id,
                        code,
                        title,
                        description,
                        stage_order,
                        prerequisite_id,
                        pass_criteria,
                        xp,
                        initial_status,
                    ),
                )
                prerequisite_id = quest_id

            task_links = {
                "ara-lv1": ("LangGraph",),
                "ara-lv2": ("MCP", "pgvector"),
                "ara-lv3": ("流式 API",),
                "ara-lv4": ("固定评测集",),
                "ara-lv5": ("长任务队列",),
                "ara-lv6": ("Prompt Injection",),
                "ara-lv7": ("容器化 Agent",),
            }
            task_rows = connection.execute(
                "SELECT id,title FROM learning_tasks"
            ).fetchall()
            for quest_id, fragments in task_links.items():
                for task in task_rows:
                    if any(
                        fragment.lower() in task["title"].lower()
                        for fragment in fragments
                    ):
                        connection.execute(
                            "INSERT OR IGNORE INTO quest_learning_tasks(quest_id,learning_task_id) VALUES(?,?)",
                            (quest_id, task["id"]),
                        )
        return self.campaign(campaign_id)  # type: ignore[return-value]

    def campaigns(self) -> tuple[LearningCampaign, ...]:
        return self._rows(
            "SELECT * FROM learning_campaigns ORDER BY updated_at DESC",
            LearningCampaign,
        )

    def campaign(self, campaign_id: str) -> LearningCampaign | None:
        rows = self._rows(
            "SELECT * FROM learning_campaigns WHERE id = ?",
            LearningCampaign,
            (campaign_id,),
        )
        return rows[0] if rows else None

    def quests(self, campaign_id: str) -> tuple[Quest, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM quests WHERE campaign_id = ? ORDER BY stage_order",
                (campaign_id,),
            ).fetchall()
            links = connection.execute(
                "SELECT quest_id,learning_task_id FROM quest_learning_tasks WHERE quest_id IN (SELECT id FROM quests WHERE campaign_id = ?)",
                (campaign_id,),
            ).fetchall()
        task_ids: dict[str, list[str]] = {}
        for link in links:
            task_ids.setdefault(link["quest_id"], []).append(link["learning_task_id"])
        return tuple(
            Quest(**dict(row), learning_task_ids=tuple(task_ids.get(row["id"], ())))
            for row in rows
        )

    def quest(self, quest_id: str) -> Quest | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM quests WHERE id = ?", (quest_id,)
            ).fetchone()
            links = connection.execute(
                "SELECT learning_task_id FROM quest_learning_tasks WHERE quest_id = ? ORDER BY learning_task_id",
                (quest_id,),
            ).fetchall()
        return (
            Quest(
                **dict(row),
                learning_task_ids=tuple(link["learning_task_id"] for link in links),
            )
            if row
            else None
        )

    def quest_evidence(self, quest_id: str) -> tuple[QuestEvidence, ...]:
        return self._rows(
            "SELECT * FROM quest_evidence WHERE quest_id = ? ORDER BY created_at DESC",
            QuestEvidence,
            (quest_id,),
        )

    def campaign_xp(self, campaign_id: str) -> int:
        with self.connect() as connection:
            value = connection.execute(
                "SELECT COALESCE(SUM(xp),0) FROM quests WHERE campaign_id = ? AND status = 'cleared'",
                (campaign_id,),
            ).fetchone()[0]
        return int(value)

    def start_quest(self, quest_id: str) -> Quest:
        quest = self.quest(quest_id)
        if quest is None:
            raise KeyError(quest_id)
        if quest.status != "available":
            raise ValueError("只有已解锁关卡可以开始")
        if quest.prerequisite_id:
            prerequisite = self.quest(quest.prerequisite_id)
            if prerequisite is None or prerequisite.status != "cleared":
                raise ValueError("请先通关前置关卡")
        with self.connect() as connection:
            connection.execute(
                "UPDATE quests SET status='active',started_at=? WHERE id=?",
                (_now(), quest_id),
            )
        return self.quest(quest_id)  # type: ignore[return-value]

    def add_quest_evidence(
        self,
        quest_id: str,
        *,
        commit_sha: str,
        test_result: str,
        reflection: str = "",
        evidence_url: str = "",
    ) -> QuestEvidence:
        quest = self.quest(quest_id)
        if quest is None:
            raise KeyError(quest_id)
        if quest.status != "active":
            raise ValueError("请先开始关卡再提交证据")
        clean_sha = commit_sha.strip()
        clean_result = test_result.strip()
        if not clean_sha or not clean_result:
            raise ValueError("Commit SHA 和测试结果不能为空")
        evidence = QuestEvidence(
            id=_id("evidence"),
            quest_id=quest_id,
            commit_sha=clean_sha[:120],
            test_result=clean_result[:20_000],
            reflection=reflection.strip()[:20_000],
            evidence_url=evidence_url.strip()[:1000],
            created_at=_now(),
        )
        self._insert("quest_evidence", evidence)
        return evidence

    def clear_quest(self, quest_id: str) -> Quest:
        quest = self.quest(quest_id)
        if quest is None:
            raise KeyError(quest_id)
        if quest.status != "active" or not self.quest_evidence(quest_id):
            raise ValueError("关卡进行中且已有验收证据时才能确认通关")
        stamp = _now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE quests SET status='cleared',completed_at=? WHERE id=?",
                (stamp, quest_id),
            )
            connection.execute(
                "UPDATE quests SET status='available' WHERE prerequisite_id=? AND status='locked'",
                (quest_id,),
            )
            remaining = connection.execute(
                "SELECT count(*) FROM quests WHERE campaign_id=? AND status!='cleared'",
                (quest.campaign_id,),
            ).fetchone()[0]
            if remaining == 0:
                connection.execute(
                    "UPDATE learning_campaigns SET status='completed',updated_at=? WHERE id=?",
                    (stamp, quest.campaign_id),
                )
        return self.quest(quest_id)  # type: ignore[return-value]

    def _rows(self, sql: str, cls, params: tuple = ()) -> tuple:
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(cls(**dict(row)) for row in rows)

    def _insert(self, table: str, item) -> None:
        data = item if isinstance(item, dict) else item.__dict__
        columns = ",".join(data)
        placeholders = ",".join(f":{key}" for key in data)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO {table}({columns}) VALUES({placeholders})", data
            )

    @staticmethod
    def _resume(row: sqlite3.Row) -> ResumeVersion:
        data = dict(row)
        try:
            project_ids = tuple(json.loads(data.pop("project_ids")))
        except (TypeError, ValueError):
            project_ids = ()
        return ResumeVersion(**data, project_ids=project_ids)


def validate_document(filename: str, content: bytes) -> tuple[str, str, str]:
    """Validate an upload by extension and signature; return extracted local text."""

    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("文件不能为空且不能超过 20 MB")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 PDF、DOCX、Markdown、TXT、PNG 和 JPEG")

    media_type = mimetypes.types_map.get(extension, "application/octet-stream")
    extracted = ""
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("PDF 文件签名无效")
        media_type = "application/pdf"
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 200:
                raise ValueError("PDF 页数不能超过 200 页")
            extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            extracted = ""
        except Exception as error:
            raise ValueError("PDF 无法安全解析") from error
    elif extension == ".docx":
        if not content.startswith(b"PK"):
            raise ValueError("DOCX 文件签名无效")
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if (
                    sum(item.file_size for item in archive.infolist())
                    > MAX_DOCX_EXPANDED_BYTES
                ):
                    raise ValueError("DOCX 解压后体积过大")
                names = set(archive.namelist())
                if "word/document.xml" not in names or any(
                    name.endswith("vbaProject.bin") for name in names
                ):
                    raise ValueError("DOCX 结构无效或包含宏")
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                extracted = " ".join(text for text in root.itertext() if text.strip())
        except (zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise ValueError("DOCX 无法安全解析") from error
    elif extension in {".md", ".txt"}:
        try:
            extracted = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("文本文件必须使用 UTF-8 编码") from error
        media_type = "text/markdown" if extension == ".md" else "text/plain"
    elif extension == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG 文件签名无效")
        media_type = "image/png"
    else:
        if not content.startswith(b"\xff\xd8\xff"):
            raise ValueError("JPEG 文件签名无效")
        media_type = "image/jpeg"
    return extension, media_type, extracted
