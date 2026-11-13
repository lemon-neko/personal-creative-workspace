from collections.abc import Callable, Iterable

from app.career.application.ports import UnitOfWork
from app.career.domain.job import JobOpportunity, JobResumeSubmission, JobSkillGap


def require_job_description(job: JobOpportunity) -> None:
    if not job.jd_text.strip():
        raise ValueError("请先补充 JD，再分析职位要求。")


class JobService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def record_job_submission(self, job_id: str, resume_id: str) -> JobResumeSubmission:
        with self.uow(write=True) as stores:
            if stores.jobs.job(job_id) is None:
                raise KeyError(job_id)
            resume = stores.resumes.resume(resume_id)
            if resume is None:
                raise ValueError("请选择有效简历")
            if not resume.is_structured or not (
                resume.resume_kind == "master"
                or (resume.resume_kind == "tailored" and resume.job_id == job_id)
            ):
                raise ValueError("只能记录主简历或该岗位的定制简历")
            return stores.jobs.insert_submission(job_id, resume)

    def confirmed_skill_names(self, job_id: str) -> tuple[str, ...]:
        with self.uow() as stores:
            if stores.jobs.job(job_id) is None:
                raise KeyError(job_id)
            skills = {skill.id: skill.name for skill in stores.learning.skills()}
            return tuple(
                skills[gap.skill_id]
                for gap in stores.jobs.gaps()
                if gap.job_id == job_id and gap.skill_id in skills
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
        with self.uow(write=True) as stores:
            if (
                stores.jobs.job(job_id) is None
                or not stores.learning.skill_exists(skill_id)
                or importance not in range(1, 6)
            ):
                raise ValueError("职位、技能或重要度无效")
            stores.jobs.upsert_skill_gap(
                JobSkillGap(
                    job_id,
                    skill_id,
                    importance,
                    evidence.strip()[:5000],
                    gap_note.strip()[:5000],
                )
            )

    def analyze_job_skills(
        self,
        job: JobOpportunity,
        material: str,
        analyze: Callable[[str], Iterable[dict]],
    ) -> tuple[dict, ...]:
        require_job_description(job)
        return tuple(analyze(material))

    def confirm_job_skills(
        self, job_id: str, reviewed: list[tuple[str, str, int, str]]
    ) -> None:
        if not reviewed or len(reviewed) > 30:
            raise ValueError("请至少选择一条技能候选")
        with self.uow(write=True) as stores:
            job = stores.jobs.job(job_id)
            if job is None:
                raise KeyError(job_id)
            require_job_description(job)
            for name, category, importance, requirement in reviewed:
                if (
                    not name.strip()
                    or len(name.strip()) > 120
                    or importance not in range(1, 6)
                ):
                    raise ValueError("技能名称或重要度无效")
                skill = stores.learning.find_or_add_skill(name=name, category=category)
                stores.jobs.upsert_skill_gap(
                    JobSkillGap(
                        job_id, skill.id, importance, "", requirement.strip()[:2000]
                    )
                )

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
        with self.uow(write=True) as stores:
            return stores.jobs.add_job(
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
        with self.uow(write=True) as stores:
            return stores.jobs.patch_job(job_id, changes)

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
        with self.uow(write=True) as stores:
            return stores.jobs.update_job(
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
        with self.uow(write=True) as stores:
            return stores.jobs.update_job_status(job_id, status, note)
