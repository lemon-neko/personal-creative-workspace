from app.career import ResumeVersion
from app.career.domain.resume import ResumeVersion as Version, referenced_project_ids
from app.resume_studio import normalize_structured_resume


def test_resume_deduplicates_evidence_ids_and_keeps_legacy_version_type():
    assert Version is ResumeVersion
    structured = normalize_structured_resume(
        {
            "projects": [
                {"name": "First", "project_id": "p1"},
                {"name": "Second", "project_id": "p2"},
                {"name": "Third", "project_id": "p1"},
            ],
        }
    )
    assert referenced_project_ids(structured) == ("p1", "p2")
