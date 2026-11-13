from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.career import CareerRepository
from app.career.application.job_service import JobService
from app.career.domain.job import JobOpportunity
from app.resume_studio import normalize_structured_resume


def test_job_service_rejects_blank_jd_without_calling_model():
    analyzer = Mock(return_value=({"name": "SQLite"},))
    service = JobService(Mock())
    job = JobOpportunity("job", "Example", "Engineer", "", "", "", "saved", "", "", "")
    with pytest.raises(ValueError, match="补充 JD"):
        service.analyze_job_skills(job, "preview", analyzer)
    analyzer.assert_not_called()


def test_job_service_uses_one_write_context_for_job_and_resume():
    job_store = Mock()
    resume_store = Mock()
    resume = SimpleNamespace(is_structured=True, resume_kind="tailored", job_id="job")
    resume_store.resume.return_value = resume

    @contextmanager
    def uow(*, write):
        assert write
        yield SimpleNamespace(jobs=job_store, resumes=resume_store)

    result = JobService(uow).record_job_submission("job", "resume")
    assert result is job_store.insert_submission.return_value
    job_store.job.assert_called_once_with("job")
    resume_store.resume.assert_called_once_with("resume")
    job_store.insert_submission.assert_called_once_with("job", resume)


def test_resume_service_checks_document_and_project_before_inserting(tmp_path):
    career = CareerRepository(tmp_path)
    bad = normalize_structured_resume(
        {"projects": [{"name": "Example", "project_id": "missing"}]}
    )
    with pytest.raises(ValueError, match="关联文档不存在"):
        career.resume_service.add_structured_resume(
            title="Example",
            structured=bad,
            resume_kind="master",
            document_id="missing",
        )
    doc = career.add_document(
        kind="resume", filename="sample.txt", content=b"synthetic"
    )
    with pytest.raises(ValueError, match="不存在的项目证据"):
        career.resume_service.add_structured_resume(
            title="Example",
            structured=bad,
            resume_kind="master",
            document_id=doc.id,
        )
    assert career.resumes() == ()
