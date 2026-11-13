import sqlite3
from contextlib import closing

import pytest

from app.career import CareerRepository


def test_transaction_reuses_connection_rolls_back_and_closes(tmp_path):
    career = CareerRepository(tmp_path)
    with pytest.raises(RuntimeError, match="stop"):
        with career.unit_of_work(write=True) as stores:
            connection = stores.jobs.connection
            assert (
                stores.resumes.connection
                is stores.learning.connection
                is stores.profile.connection
                is connection
            )
            assert connection.in_transaction
            stores.profile.save_profile(facts="synthetic")
            stores.jobs.add_job(company="Example", title="Engineer")
            raise RuntimeError("stop")
    assert not career.jobs() and not career.profile().facts
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_skill_confirmation_rolls_back_earlier_skill_and_gap(tmp_path):
    career = CareerRepository(tmp_path)
    job = career.add_job(company="Example", title="Engineer", jd_text="Synthetic JD")
    with closing(career.connect()) as connection, connection:
        connection.execute("""
            CREATE TRIGGER abort_second_gap BEFORE INSERT ON job_skill_gaps
            WHEN NEW.gap_note = 'abort'
            BEGIN SELECT RAISE(ABORT, 'fixture rejected'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="fixture rejected"):
        career.job_service.confirm_job_skills(
            job.id,
            [
                ("First", "", 2, "keep"),
                ("Second", "", 3, "abort"),
            ],
        )
    assert not career.skills() and not career.gaps()


def test_failed_resume_write_rolls_back_photo_registration_and_file(
    tmp_path, monkeypatch
):
    from app.resume_docx import DocxResumeCandidate
    from app.resume_studio import normalize_structured_resume
    from tests.test_resume_studio import _resume_docx

    career = CareerRepository(tmp_path)
    document = career.add_document(
        kind="resume", filename="sample.docx", content=_resume_docx()
    )
    parsed = career.resume_service.preview_document(document)
    assert parsed.portrait is not None
    candidate = DocxResumeCandidate(
        normalize_structured_resume({}), parsed.portrait, ()
    )
    monkeypatch.setattr(career.resume_service, "preview_document", lambda _: candidate)
    with closing(career.connect()) as connection, connection:
        connection.execute("""
            CREATE TRIGGER abort_resume BEFORE INSERT ON resumes
            BEGIN SELECT RAISE(ABORT, 'fixture rejected'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="fixture rejected"):
        career.resume_service.import_primary_resume(
            document, title="Example", target_role="Engineer"
        )
    assert not career.resumes() and not tuple(career.resume_assets_root.iterdir())
    with closing(career.connect()) as connection:
        assert (
            connection.execute("SELECT count(*) FROM resume_assets").fetchone()[0] == 0
        )
