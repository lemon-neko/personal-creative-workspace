from __future__ import annotations

import json
import sqlite3
import struct
import zlib
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.career import (
    CAMPAIGN_SCHEMA,
    CAREER_RADAR_SCHEMA,
    SCHEMA,
    CareerRepository,
)
from app.database import WORKSPACE_REGISTRY, apply_migrations
from app.main import create_app
from app.model_gateway import ModelTaskKind, ModelTaskStore
from app.resume_studio import (
    apply_tailoring_suggestions,
    build_import_candidate,
    match_resume,
    normalize_structured_resume,
    validate_tailoring_suggestions,
)
from app.resume_docx import parse_resume_docx
from app.resume_import import import_primary_resume


def _png(width: int, height: int) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xdd\xee\xee" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _resume_docx() -> bytes:
    lines = (
        "测试作者",
        "AI-Agent应用开发工程师",
        "4年经验 29岁 author@example.test 13800138000",
        "个人概要",
        "能够从需求走到可靠交付。",
        "教育背景",
        "示例大学 计算机科学与技术（本科） 2018.09–2022.06",
        "工作经历",
        "示例科技 AI 算法+测试开发工程师 2022.07–至今",
        "负责 Agent 应用可靠性建设",
        "项目经历",
        "LogRoot Agent",
        "项目介绍",
        "构建缺陷定位 Agent",
        "Python FastAPI RAG",
        "完成可追溯交付",
        "大模型推理引擎测评框架",
        "项目介绍",
        "构建缺陷定位 Agent",
        "Python FastAPI RAG",
        "完成可追溯交付",
        "设计统一评测入口",
        "实现性能数据采集",
        "支持失败恢复",
        "输出 JUnit XML 报告",
        "自我评价",
        "重视问题拆解和结果验证。",
    )
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    ).encode()
    portrait = _png(120, 160)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/media/portrait.png", portrait)
        archive.writestr("word/media/portrait-copy.png", portrait)
        archive.writestr("word/media/icon.png", _png(100, 100))
    return buffer.getvalue()


def _structured(project_id: str = ""):
    return normalize_structured_resume(
        {
            "personal_info": {
                "name": "测试作者",
                "title": "Agent 应用开发",
                "email": "author@example.test",
            },
            "summary": "使用 Python 与 FastAPI 构建可靠 Agent 应用。",
            "work_experience": [
                {
                    "title": "AI 工程师",
                    "company": "示例公司",
                    "years": "2022–2026",
                    "description": ["交付 Agent 服务", "降低失败率 20%"],
                }
            ],
            "education": [
                {"institution": "示例大学", "degree": "本科", "years": "2018–2022"}
            ],
            "projects": [
                {
                    "project_id": project_id,
                    "name": "可靠性工作台",
                    "role": "负责人",
                    "description": ["实现 Trace 与幂等恢复"],
                }
            ]
            if project_id
            else [],
            "skills": ["Python", "FastAPI", "LangGraph"],
        }
    )


def test_resume_studio_migrates_v3_database_without_rewriting_legacy_records(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workspace.db"
    snapshot_root = tmp_path / "working" / "db-migrations"
    apply_migrations(
        database_path,
        registry=WORKSPACE_REGISTRY,
        subsystem="career",
        snapshot_root=snapshot_root,
        migrations={
            1: f"{SCHEMA}\nPRAGMA user_version = 1;",
            2: f"{CAMPAIGN_SCHEMA}\nPRAGMA user_version = 2;",
            3: f"{CAREER_RADAR_SCHEMA}\nPRAGMA user_version = 3;",
        },
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO resumes(
                id,title,target_role,project_ids,status,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                "resume-legacy",
                "历史简历",
                "Agent 工程师",
                "[]",
                "active",
                "保留原记录",
                "2026-08-01T10:00:00+08:00",
                "2026-08-01T10:00:00+08:00",
            ),
        )

    repository = CareerRepository(tmp_path)
    legacy = repository.resume("resume-legacy")

    assert legacy is not None
    assert legacy.resume_kind == "legacy"
    assert legacy.structured_data == ""
    assert legacy.revision == 0
    assert list(snapshot_root.glob("workspace-before-career-v3-to-v6-*.db"))
    CareerRepository(tmp_path)
    assert repository.resume("resume-legacy") == legacy


def test_structured_resume_repository_preserves_master_and_tailored_versions(
    tmp_path: Path,
) -> None:
    repository = CareerRepository(tmp_path)
    project = repository.add_project(name="可靠性工作台", outcome="交付测试")
    job = repository.add_job(
        company="示例公司",
        title="Agent 工程师",
        jd_text="需要 Python、FastAPI 和 LangGraph。",
    )
    master = repository.add_structured_resume(
        title="主简历",
        structured=_structured(project.id),
        resume_kind="master",
        status="active",
        is_primary=True,
    )
    tailored = repository.add_structured_resume(
        title="示例公司定制版",
        structured=repository.structured_resume(master),
        resume_kind="tailored",
        parent_id=master.id,
        job_id=job.id,
    )

    assert repository.primary_resume().id == master.id  # type: ignore[union-attr]
    assert tailored.parent_id == master.id
    assert tailored.job_id == job.id
    assert repository.resume(master.id).revision == 1  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="已经存在主简历"):
        repository.add_structured_resume(
            title="重复主简历",
            structured=_structured(project.id),
            resume_kind="master",
            is_primary=True,
        )


def test_resume_revision_and_fact_source_changes_are_explicit(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path)
    project = repository.add_project(name="项目", outcome="交付")
    master = repository.add_structured_resume(
        title="主简历",
        structured=_structured(project.id),
        resume_kind="master",
        is_primary=True,
    )
    updated = repository.update_structured_resume(
        master.id,
        structured=_structured(project.id),
        expected_revision=1,
        title="主简历 v2",
    )
    assert updated.revision == 2
    with pytest.raises(RuntimeError, match="已在.*更新"):
        repository.update_structured_resume(
            master.id,
            structured=_structured(project.id),
            expected_revision=1,
            title="过期保存",
        )
    repository.update_project(project.id, name="项目", outcome="新增事实")
    assert not repository.resume_source_is_current(updated)


def test_local_import_and_jd_match_do_not_invent_ats_claims(tmp_path: Path) -> None:
    repository = CareerRepository(tmp_path)
    repository.save_profile(
        target_roles="Agent 应用开发",
        contact="author@example.test",
        experience="负责 FastAPI 服务\n完成异步任务",
        skills="Python\nFastAPI",
        facts="四年应用开发经验",
    )
    candidate = build_import_candidate(
        "测试作者\nAgent engineer", repository.profile(), ()
    )
    report = match_resume(candidate, "需要 Python、FastAPI 和 Redis。")
    assert candidate.personal_info["name"] == "测试作者"
    assert "Python" in report.matched_keywords
    assert "Redis" in report.missing_keywords
    assert report.keyword_coverage is not None
    empty = match_resume(candidate, "负责业务协作与交付")
    assert empty.keyword_coverage is None


def test_tailoring_candidates_require_existing_fields_and_evidence() -> None:
    resume = _structured("project-1")
    raw = [
        {
            "path": "summary",
            "before": resume.summary,
            "after": "面向 Agent 应用可靠性的 Python 工程师。",
            "reason": "贴近岗位重点",
            "evidence_ids": ["career-profile", "project-1"],
        }
    ]
    suggestions = validate_tailoring_suggestions(
        raw, resume, {"career-profile", "project-1"}
    )
    tailored = apply_tailoring_suggestions(resume, suggestions)
    assert tailored.summary.startswith("面向 Agent")
    assert resume.summary.startswith("使用 Python")
    with pytest.raises(ValueError, match="有效证据"):
        validate_tailoring_suggestions(
            [{**raw[0], "evidence_ids": ["invented"]}],
            resume,
            {"career-profile", "project-1"},
        )
    with pytest.raises(ValueError, match="字段无效"):
        validate_tailoring_suggestions(
            [{**raw[0], "path": "personal_info.name"}],
            resume,
            {"career-profile", "project-1"},
        )


def test_resume_manual_import_rejects_fabricated_project_ids(tmp_path: Path) -> None:
    store = ModelTaskStore(tmp_path)
    task = store.create(
        task_type=ModelTaskKind.RESUME_PARSE.value,
        purpose="结构化简历",
        source_labels=("resume.md",),
        payload=json.dumps(
            {
                "document_id": "doc-1",
                "document_text": "测试",
                "allowed_project_ids": ["project-real"],
            },
            ensure_ascii=False,
        ),
        return_url="/career/resumes",
    )
    result = {"resume": _structured("project-fake").to_payload()}
    with pytest.raises(ValueError, match="虚构"):
        store.import_result(task.id, json.dumps(result, ensure_ascii=False))


def test_resume_studio_import_edit_match_and_html_download(tmp_path: Path) -> None:
    application = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=False,
    )
    repository = application.state.career
    document = repository.add_document(
        kind="resume",
        filename="resume.md",
        content="测试作者\nPython FastAPI 工程师".encode(),
    )
    job = repository.add_job(
        company="示例公司",
        title="Agent 工程师",
        jd_text="需要 Python 和 FastAPI。",
    )
    client = TestClient(application)
    preview = client.post(
        "/career/resumes/import/preview", data={"document_id": document.id}
    )
    assert preview.status_code == 200
    assert "确认主简历候选" in preview.text

    confirmed = client.post(
        "/career/resumes/import/confirm",
        data={
            "document_id": document.id,
            "title": "Agent 主简历",
            "target_role": "Agent 工程师",
            "personal_name": "测试作者",
            "personal_title": "Agent 工程师",
            "personal_email": "author@example.test",
            "summary": "使用 Python 和 FastAPI 构建 Agent。",
            "skills": "Python\nFastAPI",
            "visible_sections": [
                "summary",
                "work_experience",
                "education",
                "projects",
                "skills",
            ],
        },
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    resume = repository.primary_resume()
    assert resume is not None
    detail = client.get(f"/career/resumes/{resume.id}")
    assert detail.status_code == 200
    assert "实时预览" in detail.text
    assert "导出国内版" in detail.text
    assert "resume-editor-form" in detail.text
    match = client.get(f"/career/resumes/{resume.id}/match/{job.id}")
    assert match.status_code == 200
    assert "关键词覆盖率" in match.text
    html = client.get(f"/career/resumes/{resume.id}/pdf?html=true")
    assert html.status_code == 200
    assert "A4" in html.text
    assert "no-store" in html.headers.get("cache-control", "")


def test_manual_bridge_creates_confirmed_master_and_tailored_child(
    tmp_path: Path,
) -> None:
    application = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=False,
    )
    repository = application.state.career
    project = repository.add_project(name="证据项目", outcome="稳定交付")
    document = repository.add_document(
        kind="resume",
        filename="resume.txt",
        content=b"fictional resume",
    )
    parse_task = application.state.model_tasks.create(
        task_type=ModelTaskKind.RESUME_PARSE.value,
        purpose="结构化简历",
        source_labels=(document.original_name,),
        payload=json.dumps(
            {
                "document_id": document.id,
                "allowed_project_ids": [project.id],
            },
            ensure_ascii=False,
        ),
        return_url="/career/resumes",
    )
    application.state.model_tasks.import_result(
        parse_task.id,
        json.dumps({"resume": _structured(project.id).to_payload()}, ensure_ascii=False),
    )
    client = TestClient(application)
    confirmed = client.post(
        f"/model-tasks/{parse_task.id}/confirm",
        data={"title": "人工桥接主简历", "target_role": "Agent 工程师"},
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    master = repository.primary_resume()
    assert master is not None

    job = repository.add_job(
        company="示例公司",
        title="Agent 工程师",
        jd_text="需要 Python 与 FastAPI。",
    )
    before = repository.structured_resume(master).summary
    tailor_task = application.state.model_tasks.create(
        task_type=ModelTaskKind.RESUME_TAILOR.value,
        purpose="岗位定制",
        source_labels=(master.title, job.title),
        payload=json.dumps(
            {
                "resume_id": master.id,
                "resume_revision": master.revision,
                "resume": repository.structured_resume(master).to_payload(),
                "job": {"id": job.id},
                "allowed_evidence_ids": ["career-profile", project.id],
            },
            ensure_ascii=False,
        ),
        return_url=f"/career/resumes/{master.id}/match/{job.id}",
    )
    application.state.model_tasks.import_result(
        tailor_task.id,
        json.dumps(
            {
                "suggestions": [
                    {
                        "path": "summary",
                        "before": before,
                        "after": "面向 Agent 可靠性的 Python 工程师。",
                        "reason": "突出岗位重点",
                        "evidence_ids": ["career-profile", project.id],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    tailored = client.post(
        f"/model-tasks/{tailor_task.id}/confirm",
        data={"selected": "0", "after_0": "面向 Agent 可靠性的 Python 工程师。"},
        follow_redirects=False,
    )
    assert tailored.status_code == 303
    child = next(row for row in repository.resumes() if row.resume_kind == "tailored")
    assert child.parent_id == master.id
    assert repository.structured_resume(master).summary == before
    assert repository.structured_resume(child).summary.startswith("面向 Agent")


def test_docx_resume_import_is_idempotent_and_keeps_private_portrait(
    tmp_path: Path,
) -> None:
    repository = CareerRepository(tmp_path)
    first_project = repository.add_project(name="LogRoot Agent", outcome="交付")
    second_project = repository.add_project(
        name="大模型推理引擎测评框架", outcome="完成评测"
    )
    document = repository.add_document(
        kind="resume", filename="示例主简历.docx", content=_resume_docx()
    )
    legacy = repository.add_resume(title="历史简历", document_id=document.id)

    candidate = parse_resume_docx(
        repository.document_path(document).read_bytes(),
        repository.profile(),
        repository.projects(),
    )
    assert len(candidate.resume.education) == 1
    assert len(candidate.resume.work_experience) == 1
    assert tuple(row["project_id"] for row in candidate.resume.projects) == (
        first_project.id,
        second_project.id,
    )
    assert len(candidate.resume.projects[1]["description"]) == 4
    assert candidate.portrait is not None
    assert (candidate.portrait.width, candidate.portrait.height) == (120, 160)
    assert len(candidate.resume.skills) == len(
        {value.casefold() for value in candidate.resume.skills}
    )

    result = import_primary_resume(
        repository,
        document,
        title="主简历",
        target_role="Agent 应用开发工程师",
    )
    repeated = import_primary_resume(
        repository,
        document,
        title="不应重复创建",
        target_role="Agent 应用开发工程师",
    )
    assert result.created is True
    assert repeated.created is False
    assert repeated.resume == result.resume
    assert repository.resume(legacy.id) is not None
    assert repository.document(document.id) is not None
    assert len([row for row in repository.resumes() if row.resume_kind == "master"]) == 1
    assert result.snapshot is not None and result.snapshot.is_file()

    resume = result.resume
    assert resume is not None and resume.photo_asset_id
    asset = repository.resume_asset(resume.photo_asset_id)
    assert asset is not None
    assert repository.resume_asset_path(asset).stat().st_mode & 0o777 == 0o600

    application = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=False,
    )
    client = TestClient(application)
    assert client.get(f"/career/resumes/{resume.id}/photo").status_code == 200
    china = client.get(f"/career/resumes/{resume.id}/pdf?variant=china&html=true")
    ats = client.get(f"/career/resumes/{resume.id}/pdf?variant=ats&html=true")
    assert china.status_code == ats.status_code == 200
    assert "data:image/png;base64," in china.text
    assert "data:image/" not in ats.text
    assert "自我评价" in china.text
