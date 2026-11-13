import pytest

from app.career.domain.job import JOB_STATUS_LABELS, validate_job


def test_job_keeps_legacy_interview_status_and_rejects_invalid_calendar_date():
    assert JOB_STATUS_LABELS["interviewing"] == "面试中（未分轮次）"
    fields = dict(
        company="Example",
        title="Engineer",
        status="interviewing",
        tier="A",
        next_action_on="",
    )
    validate_job(**fields, applied_on="2028-02-29")
    with pytest.raises(ValueError, match="日期格式无效"):
        validate_job(**fields, applied_on="2027-02-29")
