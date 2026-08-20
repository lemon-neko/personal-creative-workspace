"""SQLite-backed private career cockpit and document vault."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from app.database import (
    WORKSPACE_REGISTRY,
    apply_migrations,
    connect_database,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".png", ".jpg", ".jpeg"}
DOCUMENT_KINDS = {"resume", "certificate", "project", "job", "other"}
JOB_STATUSES = {
    "saved",
    "assessing",
    "applying",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
    "archived",
}
PROJECT_STATUSES = {"draft", "active", "archived"}
RESUME_STATUSES = {"draft", "active", "archived"}
LEARNING_STATUSES = {"backlog", "active", "done", "paused"}
QUEST_STATUSES = {"locked", "available", "active", "cleared"}
CAMPAIGN_STATUSES = {"planned", "active", "completed"}
SCHEMA_VERSION = 2


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


@dataclass(frozen=True)
class JobStageEvent:
    id: int
    job_id: str
    status: str
    note: str
    created_at: str


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


class CareerRepository:
    """Small transaction-oriented repository for one local author."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.database_path = data_root / "workspace.db"
        self.documents_root = data_root / "documents"
        self.documents_root.mkdir(parents=True, exist_ok=True, mode=0o700)
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
                2: f"{CAMPAIGN_SCHEMA}\nPRAGMA user_version = {SCHEMA_VERSION};",
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

    def update_resume_status(self, resume_id: str, status: str) -> None:
        if status not in RESUME_STATUSES:
            raise ValueError("简历状态无效")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE resumes SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), resume_id),
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

    def jobs(self) -> tuple[JobOpportunity, ...]:
        return self._rows("SELECT * FROM jobs ORDER BY updated_at DESC", JobOpportunity)

    def job(self, job_id: str) -> JobOpportunity | None:
        rows = self._rows("SELECT * FROM jobs WHERE id = ?", JobOpportunity, (job_id,))
        return rows[0] if rows else None

    def add_job(
        self,
        *,
        company: str,
        title: str,
        jd_text: str,
        location: str = "",
        source_url: str = "",
        notes: str = "",
    ) -> JobOpportunity:
        if not company.strip() or not title.strip() or not jd_text.strip():
            raise ValueError("公司、岗位和职位描述不能为空")
        stamp = _now()
        job = JobOpportunity(
            _id("job"),
            company.strip()[:160],
            title.strip()[:160],
            location.strip()[:160],
            source_url.strip()[:1000],
            jd_text.strip()[:100_000],
            "saved",
            notes.strip()[:20_000],
            stamp,
            stamp,
        )
        self._insert("jobs", job)
        self.add_job_event(job.id, "saved", "职位已加入工作台")
        return job

    def update_job_status(
        self, job_id: str, status: str, note: str = ""
    ) -> JobOpportunity:
        if status not in JOB_STATUSES:
            raise ValueError("职位状态无效")
        if self.job(job_id) is None:
            raise KeyError(job_id)
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), job_id),
            )
        self.add_job_event(job_id, status, note)
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
