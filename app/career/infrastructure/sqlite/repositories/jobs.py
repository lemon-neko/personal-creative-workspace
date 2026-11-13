from __future__ import annotations

from datetime import date
from uuid import UUID

from app.career.domain.job import (
    JOB_INLINE_FIELDS,
    JOB_STATUSES,
    JobOpportunity,
    JobResumeSubmission,
    JobSkillGap,
    JobStageEvent,
    validate_job,
)
from app.career.domain.policies import new_id as _id, now as _now
from app.career.infrastructure.sqlite.database import Repository
from app.career.domain.resume import ResumeVersion


class JobRepository(Repository):
    def jobs(self) -> tuple[JobOpportunity, ...]:
        return self._rows(
            "SELECT * FROM jobs ORDER BY updated_at DESC, rowid DESC", JobOpportunity
        )

    def job(self, job_id: str) -> JobOpportunity | None:
        rows = self._rows("SELECT * FROM jobs WHERE id = ?", JobOpportunity, (job_id,))
        return rows[0] if rows else None

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
        validate_job(
            company=company,
            title=title,
            status=status,
            tier=tier,
            applied_on=applied_on,
            next_action_on=next_action_on,
        )
        stamp = _now()
        try:
            job_id = (
                f"job-inline-{UUID(creation_token).hex}"
                if creation_token
                else _id("job")
            )
        except (ValueError, AttributeError) as error:
            raise ValueError("新记录标识无效，请刷新页面后重试") from error
        job = JobOpportunity(
            job_id,
            company.strip()[:160],
            title.strip()[:160],
            location.strip()[:160],
            source_url.strip()[:1000],
            jd_text.strip()[:100_000],
            status,
            notes.strip()[:20_000],
            stamp,
            stamp,
            tier=tier,
            applied_on=applied_on,
            next_action=next_action.strip()[:300],
            next_action_on=next_action_on,
        )
        data = job.__dict__
        connection = self.connection
        if creation_token:
            existing = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if existing is not None:
                return JobOpportunity(**dict(existing))
        connection.execute(
            f"INSERT INTO jobs({','.join(data)}) VALUES({','.join(':' + key for key in data)})",
            data,
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
        normalized = {
            key: (
                value.strip()
                if key in {"applied_on", "next_action_on", "status"}
                else value.strip()[: JOB_INLINE_FIELDS[key]]
            )
            for key, value in changes.items()
        }
        connection = self.connection
        row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        current = dict(row)
        merged = current | normalized
        validate_job(
            **{
                key: merged[key]
                for key in (
                    "company",
                    "title",
                    "status",
                    "tier",
                    "applied_on",
                    "next_action_on",
                )
            }
        )
        changed = {
            key: value for key, value in normalized.items() if current[key] != value
        }
        if changed:
            stamp = _now()
            connection.execute(
                f"UPDATE jobs SET {','.join(key + '=?' for key in changed)},updated_at=? WHERE id=?",
                (*changed.values(), stamp, job_id),
            )
            if "status" in changed:
                connection.execute(
                    "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                    (job_id, changed["status"], "", stamp),
                )
        saved = connection.execute(
            "SELECT * FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        return JobOpportunity(**dict(saved))

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
        validate_job(
            company=company,
            title=title,
            status=status,
            tier=tier,
            applied_on=applied_on,
            next_action_on=next_action_on,
        )
        stamp = _now()
        connection = self.connection
        old = connection.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if old is None:
            raise KeyError(job_id)
        connection.execute(
            """UPDATE jobs SET company=?,title=?,status=?,tier=?,applied_on=?,
               next_action=?,next_action_on=?,location=?,source_url=?,jd_text=?,notes=?,updated_at=?
               WHERE id=?""",
            (
                company.strip()[:160],
                title.strip()[:160],
                status,
                tier,
                applied_on,
                next_action.strip()[:300],
                next_action_on,
                location.strip()[:160],
                source_url.strip()[:1000],
                jd_text.strip()[:100_000],
                notes.strip()[:20_000],
                stamp,
                job_id,
            ),
        )
        if old["status"] != status:
            connection.execute(
                "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                (job_id, status, stage_note.strip()[:2000], stamp),
            )
        return self.job(job_id)  # type: ignore[return-value]

    def update_job_status(
        self, job_id: str, status: str, note: str = ""
    ) -> JobOpportunity:
        if status not in JOB_STATUSES:
            raise ValueError("职位状态无效")
        connection = self.connection
        old = connection.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if old is None:
            raise KeyError(job_id)
        if old["status"] != status:
            stamp = _now()
            connection.execute(
                "UPDATE jobs SET status=?,updated_at=? WHERE id=?",
                (status, stamp, job_id),
            )
            connection.execute(
                "INSERT INTO job_events(job_id,status,note,created_at) VALUES(?,?,?,?)",
                (job_id, status, note.strip()[:2000], stamp),
            )
        return self.job(job_id)  # type: ignore[return-value]

    def job_submissions(
        self, job_id: str | None = None
    ) -> tuple[JobResumeSubmission, ...]:
        where = " WHERE job_id=?" if job_id is not None else ""
        return self._rows(
            "SELECT * FROM job_resume_submissions" + where + " ORDER BY id DESC",
            JobResumeSubmission,
            (job_id,) if job_id is not None else (),
        )

    def job_submission(self, submission_id: int) -> JobResumeSubmission | None:
        rows = self._rows(
            "SELECT * FROM job_resume_submissions WHERE id=?",
            JobResumeSubmission,
            (submission_id,),
        )
        return rows[0] if rows else None

    def update_job_plan(
        self,
        job_id: str,
        *,
        tier: str,
        applied_on: str,
        next_action: str,
        next_action_on: str,
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
        connection = self.connection
        connection.execute(
            "UPDATE jobs SET tier=?,applied_on=?,next_action=?,next_action_on=?,updated_at=? WHERE id=?",
            (
                tier,
                applied_on,
                next_action.strip()[:300],
                next_action_on,
                _now(),
                job_id,
            ),
        )
        return self.job(job_id)  # type: ignore[return-value]

    def add_job_event(self, job_id: str, status: str, note: str = "") -> None:
        connection = self.connection
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

    def gaps(self) -> tuple[JobSkillGap, ...]:
        return self._rows(
            "SELECT * FROM job_skill_gaps ORDER BY importance DESC", JobSkillGap
        )

    def insert_submission(
        self, job_id: str, resume: ResumeVersion
    ) -> JobResumeSubmission:
        cursor = self.connection.execute(
            """INSERT INTO job_resume_submissions(job_id,resume_id,revision,title,target_role,
               structured_data,template_key,photo_asset_id,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                resume.id,
                resume.revision,
                resume.title,
                resume.target_role,
                resume.structured_data,
                resume.template_key,
                resume.photo_asset_id,
                _now(),
            ),
        )
        return self.job_submission(cursor.lastrowid)  # type: ignore[arg-type,return-value]

    def uses_asset(self, asset_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM job_resume_submissions WHERE photo_asset_id=? LIMIT 1",
                (asset_id,),
            ).fetchone()
            is not None
        )

    def upsert_skill_gap(self, gap: JobSkillGap) -> None:
        self.connection.execute(
            """INSERT INTO job_skill_gaps(job_id,skill_id,importance,evidence,gap_note)
               VALUES(:job_id,:skill_id,:importance,:evidence,:gap_note)
               ON CONFLICT(job_id,skill_id) DO UPDATE SET importance=excluded.importance,
               evidence=excluded.evidence,gap_note=excluded.gap_note""",
            gap.__dict__,
        )
