from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.career.infrastructure.sqlite import migrations as career_migrations
from app.career import JOB_STATUS_LABELS, SCHEMA_VERSION, CareerRepository
from app.main import create_app
from app.resume_studio import normalize_structured_resume
from tests.test_resume_studio import _png


def _master(repository):
    return repository.add_structured_resume(
        title="虚构主简历", resume_kind="master", is_primary=True,
        structured=normalize_structured_resume({"personal_info": {"name": "测试候选人"},
                                                "summary": "投递时的原始内容", "skills": ["Python"]}),
    )


def _fields(job, **changes):
    fields = {key: getattr(job, key) for key in (
        "company", "title", "status", "tier", "applied_on", "next_action", "next_action_on",
        "location", "source_url", "jd_text", "notes",
    )}
    return fields | changes


def _table(html):
    return html.split('<section id="applications"', 1)[1].split("</section>", 1)[0]


def test_job_updates_are_atomic_and_only_changed_stages_emit_events(tmp_path):
    repository = CareerRepository(tmp_path)
    job = repository.add_job(company="同一公司", title="后端")
    other = repository.add_job(company="同一公司", title="Agent")
    assert job.id != other.id and job.jd_text == "" and job.status == "saved"
    for status in JOB_STATUS_LABELS:
        previous = repository.job(job.id)
        count = len(repository.job_events(job.id))
        updated = repository.update_job(job.id, **_fields(previous, status=status), stage_note="手动推进")
        assert updated.status == status and updated.applied_on == ""
        assert len(repository.job_events(job.id)) == count + int(previous.status != status)
    count = len(repository.job_events(job.id))
    repository.update_job_status(job.id, "archived", "重复保存")
    assert len(repository.job_events(job.id)) == count
    before = repository.job(job.id)
    for changes in ({"applied_on": "2026-02-30"}, {"next_action_on": "bad"},
                    {"status": "hired"}, {"tier": "D"}, {"company": " "}, {"title": ""}):
        with pytest.raises(ValueError):
            repository.update_job(job.id, **_fields(before, **changes))
        assert repository.job(job.id) == before
    with repository.connect() as connection:
        connection.execute("""CREATE TRIGGER fail_stage BEFORE INSERT ON job_events
                           BEGIN SELECT RAISE(ABORT, 'stage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        repository.update_job(job.id, **_fields(before, status="interview_1", company="应回滚"))
    assert repository.job(job.id) == before
    with pytest.raises(sqlite3.IntegrityError):
        repository.add_job(company="应回滚", title="新增失败")
    assert len(repository.jobs()) == 2


def test_career_table_filters_editing_errors_and_legacy_redirects(tmp_path):
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    repository = client.app.state.career
    added = client.post("/career/jobs", data={"company": "青禾", "title": "Agent 工程师"}, follow_redirects=True)
    assert added.status_code == 200
    job = next(row for row in repository.jobs() if row.company == "青禾")
    archived = repository.add_job(company="归档公司", title="历史岗位", status="archived")
    repository.add_job(company="其他公司", title="设计")
    assert archived.id not in str(_table(client.get("/career").text))
    assert archived.id in str(_table(client.get("/career?status=all").text))
    assert job.id in str(_table(client.get("/career?q=Agent").text))
    assert job.id not in str(_table(client.get("/career?q=设计").text))
    for path, fragment in (("/career/resumes", "#resumes"), ("/career/jobs?q=青禾", "#applications")):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302 and response.headers["location"].endswith(fragment)
    page = client.get(f"/career?edit={job.id}&q=青禾")
    assert 'data-autosave-field' in page.text and 'class="career-edit-link"' not in page.text
    response = client.post(f"/career/jobs/{job.id}/update", data=_fields(
        job, status="interview_2", next_action="准备项目介绍", filter_q="青禾", filter_status="saved",
    ), follow_redirects=False)
    assert response.status_code == 303
    assert "q=" in response.headers["location"] and "status=saved" in response.headers["location"]
    assert repository.job(job.id).status == "interview_2"
    failed = client.post(f"/career/jobs/{job.id}/update", data=_fields(
        job, company="保留输入", next_action_on="bad", filter_status="offer",
    ))
    assert failed.status_code == 422 and 'value="保留输入"' in failed.text
    assert "保存失败" in failed.text and f'id="job-{job.id}"' in failed.text
    assert repository.job(job.id).company == "青禾"
    failed_new = client.post("/career/jobs", data={"company": "保留公司", "title": "", "notes": "保留备注"})
    assert failed_new.status_code == 422 and "保留备注" in failed_new.text
    assert client.post("/career/jobs/missing/update", data=_fields(job)).status_code == 404
    assert 'id="supporting-materials" class="career-section career-support"><summary>' in page.text
    assert "求职驾驶舱" not in page.text
    # Untrusted content is escaped and never used as an external redirect target.
    client.post(f"/career/jobs/{job.id}/update", data=_fields(job, notes='<script>evil()</script>'))
    assert '<script>evil()</script>' not in client.get("/career").text


def test_submitted_resume_content_and_photo_survive_source_edits(tmp_path):
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    repository = client.app.state.career
    job = repository.add_job(company="星桥", title="平台工程师")
    other = repository.add_job(company="其他", title="前端")
    master = _master(repository)
    asset = repository.store_resume_asset(_png(80, 100))
    master = repository.update_resume_photo(master.id, expected_revision=master.revision, photo_asset_id=asset.id)
    tailored = repository.add_structured_resume(
        title="平台定制版", structured=repository.structured_resume(master), resume_kind="tailored",
        parent_id=master.id, job_id=job.id,
    )
    response = client.post(f"/career/jobs/{job.id}/submissions", data={"resume_id": master.id})
    assert response.status_code == 200
    first = repository.job_submissions(job.id)[0]
    repository.update_structured_resume(
        master.id, expected_revision=master.revision, title="修改后的主简历",
        structured=normalize_structured_resume({"summary": "修改后的正文"}),
    )
    latest = repository.resume(master.id)
    repository.update_resume_photo(master.id, expected_revision=latest.revision, photo_asset_id="")
    repository.update_resume_photo(tailored.id, expected_revision=tailored.revision, photo_asset_id="")
    # The snapshot alone keeps its photo alive.
    assert not repository.delete_resume_asset_if_unreferenced(asset.id)
    assert repository.resume_asset_path(asset).exists()
    page = client.get(f"/career/jobs/{job.id}/submissions/{first.id}")
    assert page.status_code == 200 and "投递时的原始内容" in page.text
    assert "修改后的正文" not in page.text and "只读" in page.text
    assert client.get(f"/career/jobs/{job.id}/submissions/{first.id}/photo").content == _png(80, 100)
    assert client.get(f"/career/jobs/{other.id}/submissions/{first.id}").status_code == 404
    assert client.get(f"/career/jobs/{other.id}/submissions/{first.id}/photo").status_code == 404
    before = repository.resume(master.id)
    client.post(f"/career/jobs/{job.id}/update", data=_fields(job, notes="普通修改"))
    assert len(repository.job_submissions(job.id)) == 1
    assert repository.resume(master.id) == before
    client.post(f"/career/jobs/{job.id}/submissions", data={"resume_id": tailored.id})
    assert len(repository.job_submissions(job.id)) == 2
    assert repository.job_submission(first.id) == first
    invalid = client.post(f"/career/jobs/{other.id}/submissions", data={"resume_id": tailored.id})
    assert invalid.status_code == 422 and repository.job_submissions(other.id) == ()
    assert client.post(f"/career/jobs/{job.id}/submissions", data={"resume_id": "missing"}).status_code == 422
    assert client.post("/career/jobs/missing/submissions", data={"resume_id": master.id}).status_code == 404
    assert not (tmp_path / "static").exists()


def test_blank_jd_manual_tailoring_and_model_boundaries(tmp_path):
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    repository = client.app.state.career
    job = repository.add_job(company="山海", title="应用工程师")
    master = _master(repository)
    prefix = f"/career/resumes/{master.id}"
    match = client.get(f"{prefix}/match/{job.id}")
    assert match.status_code == 200 and "请先补充 JD" in match.text
    assert "关键词覆盖率" not in match.text
    assert client.get(f"{prefix}/tailor?job_id={job.id}", follow_redirects=False).status_code == 302
    for suffix, fields in (("preview", {"job_id": job.id}),
                           (f"run/{job.id}", {"outbound_text": "{}"}),
                           (f"manual/{job.id}", {}), (f"confirm/{job.id}", {})):
        response = client.post(f"{prefix}/tailor/{suffix}", data=fields)
        assert response.status_code == 422 and "请先补充 JD" in response.text
    copied = client.post(f"{prefix}/tailor/copy", data={"job_id": job.id})
    assert copied.status_code == 200
    assert repository.resume(master.id) == master
    assert any(row.job_id == job.id and row.resume_kind == "tailored" for row in repository.resumes())


def test_v7_migration_preserves_records_and_rolls_back_failed_v8(tmp_path, monkeypatch):
    migrate = career_migrations.apply_migrations

    def only_v7(*args, **kwargs):
        kwargs["migrations"] = {key: sql for key, sql in kwargs["migrations"].items() if key <= 7}
        return migrate(*args, **kwargs)

    monkeypatch.setattr(career_migrations, "apply_migrations", only_v7)
    repository = CareerRepository(tmp_path)
    job = repository.add_job(company="历史公司", title="历史岗位", status="interviewing")

    def fail_v8(*args, **kwargs):
        kwargs["migrations"][8] += "\nINSERT INTO nonexistent_table VALUES(1);"
        return migrate(*args, **kwargs)

    monkeypatch.setattr(career_migrations, "apply_migrations", fail_v8)
    with pytest.raises(sqlite3.OperationalError):
        CareerRepository(tmp_path)
    with repository.connect() as connection:
        assert connection.execute("SELECT version FROM schema_migrations WHERE subsystem='career'").fetchone()[0] == 7
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='job_resume_submissions'").fetchone() is None
        assert connection.execute("SELECT status FROM jobs WHERE id=?", (job.id,)).fetchone()[0] == "interviewing"
    monkeypatch.setattr(career_migrations, "apply_migrations", migrate)
    migrated = CareerRepository(tmp_path)
    assert migrated.job(job.id) == job and migrated.job_submissions() == ()
    with migrated.connect() as connection:
        assert connection.execute("SELECT version FROM schema_migrations WHERE subsystem='career'").fetchone()[0] == SCHEMA_VERSION
    assert list((tmp_path / "working" / "db-migrations").glob("workspace-before-career-v7-to-v8-*.db"))
    assert CareerRepository(tmp_path).job(job.id).status == "interviewing"


def test_career_writes_keep_csrf_origin_and_local_boundaries(tmp_path):
    app = create_app(content_root=tmp_path / "content", data_root=tmp_path,
                     enable_scheduler=False, enforce_security=True)
    client = TestClient(app)
    repository = app.state.career
    job = repository.add_job(company="安全验收", title="平台工程师")
    master = _master(repository)
    client.get("/career")
    token = client.cookies.get("pcw_csrf")
    for path, fields in (("/career/jobs", {"company": "新公司", "title": "新岗位"}),
                         (f"/career/jobs/{job.id}/update", _fields(job, status="interview_1")),
                         (f"/career/jobs/{job.id}/submissions", {"resume_id": master.id})):
        assert client.post(path, data=fields).status_code == 403
        assert client.post(path, data=fields | {"csrf_token": token},
                           headers={"origin": "https://attacker.example"}).status_code == 403
        assert client.post(path, data=fields | {"csrf_token": token},
                           headers={"x-forwarded-for": "127.0.0.1"}).status_code == 403
    assert repository.job(job.id) == job and repository.job_submissions() == ()
    accepted = client.post(f"/career/jobs/{job.id}/submissions",
                           data={"resume_id": master.id, "csrf_token": token}, follow_redirects=False)
    assert accepted.status_code == 303
    snapshot = repository.job_submissions()[0]
    path = f"/career/jobs/{job.id}/submissions/{snapshot.id}"
    assert client.get(path).headers["Cache-Control"] == "no-store"
    remote = TestClient(app, client=("198.51.100.10", 50000))
    assert remote.get(path, headers={"host": "127.0.0.1:8765"}).status_code == 403


def test_inline_patch_preserves_other_fields_and_is_transactional(tmp_path):
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    repository = client.app.state.career
    job = repository.add_job(company="局部更新", title="工程师", jd_text="保留 JD", source_url="https://example.test/job",
                             location="远程", tier="A", notes="原备注")
    first = client.patch(f"/career/jobs/{job.id}", json={"status": "interview_1", "next_action": "准备面试"})
    assert first.status_code == 200 and first.json()["job"]["status"] == "interview_1"
    second = client.patch(f"/career/jobs/{job.id}", json={"notes": "新备注"})
    assert second.status_code == 200
    saved = repository.job(job.id)
    assert (saved.jd_text, saved.source_url, saved.location, saved.tier) == (job.jd_text, job.source_url, job.location, job.tier)
    assert saved.status == "interview_1" and saved.next_action == "准备面试" and saved.notes == "新备注"
    count = len(repository.job_events(job.id))
    client.patch(f"/career/jobs/{job.id}", json={"status": "interview_1"})
    assert len(repository.job_events(job.id)) == count and repository.job_submissions() == ()
    for fields in ({"notes": "不能部分写入", "applied_on": "2026-02-30"}, {"applied_on": "2026-10-201234"},
                   {"jd_text": "禁止表格更改"}, {"id": "another"}, {"status": "bad"},
                   {"company": " "}, {"notes": None}, {"title": ["x"]}, {}, []):
        assert client.patch(f"/career/jobs/{job.id}", json=fields).status_code == 422
        assert repository.job(job.id) == saved
    assert client.patch("/career/jobs/missing", json={"notes": "不存在"}).status_code == 404
    assert client.patch(f"/career/jobs/{job.id}", content="{", headers={"content-type": "application/json"}).status_code == 422
    with repository.connect() as connection:
        connection.execute("""CREATE TRIGGER fail_inline_stage BEFORE INSERT ON job_events
                           BEGIN SELECT RAISE(ABORT, 'stage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        repository.patch_job(job.id, {"status": "offer", "notes": "应回滚"})
    assert repository.job(job.id) == saved


def test_json_creation_is_idempotent_and_detail_fields_remain_editable(tmp_path):
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))
    repository = client.app.state.career
    payload = {"company": "唯一创建", "title": "后端工程师", "creation_token": "e6b9e22e-cdda-4693-af82-7c1ecb63030a"}
    first = client.post("/career/jobs", json=payload)
    again = client.post("/career/jobs", json=payload)
    assert first.status_code == again.status_code == 201
    assert first.json()["job"]["id"] == again.json()["job"]["id"]
    job = repository.job(first.json()["job"]["id"])
    assert len([row for row in repository.jobs() if row.company == "唯一创建"]) == 1
    assert len(repository.job_events(job.id)) == 1
    for invalid in ({"company": "无标识", "title": "工程师"}, payload | {"creation_token": "bad"},
                    payload | {"company": ""}, payload | {"notes": 4}, payload | {"unknown": "x"}, []):
        assert client.post("/career/jobs", json=invalid).status_code == 422
    detail = client.get(f"/career/jobs/{job.id}")
    assert detail.status_code == 200 and 'name="jd_text"' in detail.text
    saved = client.post(f"/career/jobs/{job.id}/update", data=_fields(job, jd_text="新 JD", location="杭州",
                         source_url="https://example.test/role", tier="A", return_to="detail"), follow_redirects=False)
    assert saved.status_code == 303 and f"/career/jobs/{job.id}?saved=details" in saved.headers["location"]
    invalid = client.post(f"/career/jobs/{job.id}/update", data=_fields(job, company="", jd_text="保留失败输入", return_to="detail"))
    assert invalid.status_code == 422 and "保留失败输入" in invalid.text
    assert repository.job(job.id).jd_text == "新 JD"


def test_inline_json_endpoints_preserve_csrf_and_origin_protection(tmp_path):
    app = create_app(content_root=tmp_path / "content", data_root=tmp_path,
                     enable_scheduler=False, enforce_security=True)
    client = TestClient(app)
    job = app.state.career.add_job(company="保护写入", title="工程师")
    client.get("/career")
    token = client.cookies.get("pcw_csrf")
    payload = {"company": "新增保护", "title": "岗位", "creation_token": "4e2a37c8-208b-40fb-9123-81d4a9fb4f44"}
    assert client.post("/career/jobs", json=payload).status_code == 403
    assert client.patch(f"/career/jobs/{job.id}", json={"notes": "应拒绝"}).status_code == 403
    assert client.patch(f"/career/jobs/{job.id}", json={"notes": "应拒绝"},
                        headers={"x-csrf-token": token, "origin": "https://evil.example"}).status_code == 403
    assert client.patch(f"/career/jobs/{job.id}", json={"notes": "已确认"},
                        headers={"x-csrf-token": token, "origin": "http://127.0.0.1:8765"}).status_code == 200
    assert app.state.career.job(job.id).notes == "已确认"
