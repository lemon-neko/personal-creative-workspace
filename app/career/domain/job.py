from dataclasses import dataclass
from datetime import date


JOB_STATUS_LABELS = {
    "saved": "待投递",
    "assessing": "评估中",
    "applying": "已投递",
    "written_test": "笔试",
    "interview_1": "一面",
    "interview_2": "二面",
    "final_interview": "终面",
    "hr_interview": "HR 面",
    "interviewing": "面试中（未分轮次）",
    "offer": "Offer",
    "rejected": "未通过",
    "withdrawn": "已撤回",
    "archived": "已归档",
}
JOB_STATUSES = set(JOB_STATUS_LABELS)
JOB_INLINE_FIELDS = {
    "company": 160,
    "title": 160,
    "status": 40,
    "applied_on": 10,
    "next_action": 300,
    "next_action_on": 10,
    "notes": 20_000,
}


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
class JobSkillGap:
    job_id: str
    skill_id: str
    importance: int
    evidence: str
    gap_note: str


def validate_job(
    *,
    company: str,
    title: str,
    status: str,
    tier: str,
    applied_on: str,
    next_action_on: str,
) -> None:
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
