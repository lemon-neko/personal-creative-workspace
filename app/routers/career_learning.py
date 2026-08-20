"""Private career and learning-loop routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.career import DOCUMENT_KINDS, JOB_STATUSES, LEARNING_STATUSES, PROJECT_STATUSES, RESUME_STATUSES, CareerRepository
from app.knowledge import eligible_items
from app.model_gateway import ModelTaskKind
from app.web import REPO_ROOT, TEMPLATES, collection, not_found


router = APIRouter()


def _collection(request: Request):
    return collection(request)


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return not_found(request, active_page)


def _llm_target(request: Request) -> str:
    config = getattr(request.app.state.llm_client, "config", None)
    return getattr(config, "base_url", "") if config else "已配置的模型接口"


def _disclosure_context(request: Request, *, purpose: str, source_labels: tuple[str, ...], submit_url, outbound_text: str, back_url, task_type: str = "", hidden_fields: dict[str, str] | None = None, error: str | None = None) -> dict:
    return {
        "active_page": "settings",
        "purpose": purpose,
        "source_labels": source_labels,
        "target": _llm_target(request),
        "submit_url": submit_url,
        "outbound_text": outbound_text,
        "back_url": back_url,
        "task_type": task_type,
        "hidden_fields": hidden_fields or {},
        "error": error,
    }


def _career_job_context(request: Request, job, *, skill_candidates: tuple[dict, ...] = (), error: str | None = None) -> dict:
    repository: CareerRepository = request.app.state.career
    gap_map = {gap.skill_id: gap for gap in repository.gaps() if gap.job_id == job.id}
    analyzer = getattr(request.app.state.llm_client, "job_skill_candidate", None)
    return {
        "active_page": "career",
        "job": job,
        "events": repository.job_events(job.id),
        "skills": repository.skills(),
        "gap_map": gap_map,
        "job_statuses": JOB_STATUSES,
        "llm_enabled": request.app.state.llm_client.enabled and callable(analyzer),
        "skill_candidates": skill_candidates,
        "error": error,
    }


@router.get("/career", response_class=HTMLResponse, name="career")
async def career(request: Request) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    jobs = repository.jobs()
    tasks = repository.learning_tasks()
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career.html",
        context={
            "active_page": "career",
            "profile": repository.profile(),
            "jobs": jobs,
            "projects": repository.projects(),
            "resumes": repository.resumes(),
            "active_jobs": tuple(
                job
                for job in jobs
                if job.status not in {"rejected", "withdrawn", "archived"}
            ),
            "active_tasks": tuple(
                task for task in tasks if task.status in {"backlog", "active"}
            ),
        },
    )

@router.get(
    "/career/profile",
    response_class=HTMLResponse,
    name="career_profile",
)
async def career_profile(request: Request) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_profile.html",
        context={
            "active_page": "career",
            "profile": repository.profile(),
            "documents": repository.documents(),
            "llm_enabled": request.app.state.llm_client.enabled,
        },
    )

@router.post("/career/profile", name="save_career_profile")
async def save_career_profile(
    request: Request,
    target_roles: str = Form(default=""),
    contact: str = Form(default=""),
    education: str = Form(default=""),
    experience: str = Form(default=""),
    certifications: str = Form(default=""),
    skills: str = Form(default=""),
    facts: str = Form(default=""),
) -> HTMLResponse:
    request.app.state.career.save_profile(
        target_roles=target_roles,
        contact=contact,
        education=education,
        experience=experience,
        certifications=certifications,
        skills=skills,
        facts=facts,
    )
    return RedirectResponse(
        request.url_for("career_profile").include_query_params(saved="profile"),
        status_code=303,
    )

@router.post(
    "/career/profile/import/{document_id}/preview",
    response_class=HTMLResponse,
    name="preview_profile_import",
)
async def preview_profile_import(
    request: Request, document_id: str
) -> HTMLResponse:
    document = request.app.state.career.document(document_id)
    if document is None or not document.extracted_text:
        return _not_found(request, "career")
    config = getattr(request.app.state.llm_client, "config", None)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="llm_disclosure.html",
        context={
            "active_page": "career",
            "purpose": "从简历资料提取候选人档案候选字段",
            "task_type": ModelTaskKind.PROFILE.value,
            "source_labels": (document.original_name,),
            "target": getattr(config, "base_url", "") if config else "",
            "submit_url": request.url_for(
                "analyze_profile_import", document_id=document_id
            ),
            "outbound_text": document.extracted_text,
            "back_url": request.url_for("career_profile"),
        },
    )

@router.post(
    "/career/profile/import/{document_id}/manual",
    name="manual_profile_import",
)
async def manual_profile_import(
    request: Request, document_id: str
) -> HTMLResponse:
    document = request.app.state.career.document(document_id)
    if document is None or not document.extracted_text:
        return _not_found(request, "career")
    try:
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.PROFILE.value,
            purpose="从简历资料提取候选人档案候选字段",
            source_labels=(document.original_name,),
            payload=document.extracted_text,
            return_url=str(request.url_for("career_profile")),
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_profile.html",
            context={
                "active_page": "career",
                "profile": request.app.state.career.profile(),
                "documents": request.app.state.career.documents(),
                "llm_enabled": request.app.state.llm_client.enabled,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post(
    "/career/profile/import/{document_id}/analyze",
    response_class=HTMLResponse,
    name="analyze_profile_import",
)
async def analyze_profile_import(
    request: Request,
    document_id: str,
    outbound_text: str = Form(...),
) -> HTMLResponse:
    document = request.app.state.career.document(document_id)
    client = request.app.state.llm_client
    analyzer = getattr(client, "profile_candidate", None)
    if document is None or not client.enabled or not callable(analyzer):
        return _not_found(request, "career")
    try:
        candidate = await asyncio.to_thread(analyzer, outbound_text)
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="llm_disclosure.html",
            context={
                "active_page": "career",
                "purpose": "从简历资料提取候选人档案候选字段",
                "task_type": ModelTaskKind.PROFILE.value,
                "source_labels": (document.original_name,),
                "target": getattr(getattr(client, "config", None), "base_url", ""),
                "submit_url": request.url_for(
                    "analyze_profile_import", document_id=document_id
                ),
                "outbound_text": outbound_text,
                "back_url": request.url_for("career_profile"),
                "error": f"分析失败：{error}",
            },
            status_code=502,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_profile.html",
        context={
            "active_page": "career",
            "profile": request.app.state.career.profile(),
            "candidate": candidate,
            "documents": request.app.state.career.documents(),
            "llm_enabled": True,
            "notice": "模型只生成了候选字段；请检查后再保存。",
        },
    )

@router.get(
    "/career/documents",
    response_class=HTMLResponse,
    name="career_documents",
)
async def career_documents(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_documents.html",
        context={
            "active_page": "career",
            "documents": request.app.state.career.documents(),
            "document_kinds": DOCUMENT_KINDS,
        },
    )

@router.post("/career/documents", name="upload_career_document")
async def upload_career_document(
    request: Request,
    kind: str = Form(...),
    upload: UploadFile = File(...),
) -> HTMLResponse:
    content = await upload.read(20 * 1024 * 1024 + 1)
    try:
        request.app.state.career.add_document(
            kind=kind,
            filename=upload.filename or "upload",
            content=content,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_documents.html",
            context={
                "active_page": "career",
                "documents": request.app.state.career.documents(),
                "document_kinds": DOCUMENT_KINDS,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("career_documents").include_query_params(saved="uploaded"),
        status_code=303,
    )

@router.get(
    "/career/documents/{document_id}/download", name="download_career_document"
)
async def download_career_document(
    request: Request, document_id: str
) -> FileResponse:
    document = request.app.state.career.document(document_id)
    if document is None:
        return _not_found(request, "career")  # type: ignore[return-value]
    if Path(document.stored_name).name != document.stored_name:
        return _not_found(request, "career")  # type: ignore[return-value]
    path = request.app.state.data_root / "documents" / document.stored_name
    if not path.is_file():
        return _not_found(request, "career")  # type: ignore[return-value]
    return FileResponse(
        path, media_type="application/octet-stream", filename=document.original_name
    )

@router.post(
    "/career/documents/{document_id}/delete", name="delete_career_document"
)
async def delete_career_document(
    request: Request,
    document_id: str,
    confirmation: str = Form(default=""),
) -> HTMLResponse:
    try:
        request.app.state.career.delete_document(document_id, confirmation)
    except KeyError:
        return _not_found(request, "career")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_documents.html",
            context={
                "active_page": "career",
                "documents": request.app.state.career.documents(),
                "document_kinds": DOCUMENT_KINDS,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("career_documents").include_query_params(saved="deleted"),
        status_code=303,
    )

@router.get(
    "/career/projects", response_class=HTMLResponse, name="career_projects"
)
async def career_projects(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_projects.html",
        context={
            "active_page": "career",
            "projects": request.app.state.career.projects(),
            "project_statuses": PROJECT_STATUSES,
        },
    )

@router.post("/career/projects", name="create_career_project")
async def create_career_project(request: Request) -> HTMLResponse:
    form = await request.form()
    try:
        request.app.state.career.add_project(
            **{
                key: str(value)
                for key, value in form.items()
                if key != "csrf_token"
            }
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_projects.html",
            context={
                "active_page": "career",
                "projects": request.app.state.career.projects(),
                "project_statuses": PROJECT_STATUSES,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("career_projects").include_query_params(saved="created"),
        status_code=303,
    )

@router.post("/career/projects/{project_id}", name="update_career_project")
async def update_career_project(request: Request, project_id: str) -> HTMLResponse:
    form = await request.form()
    try:
        request.app.state.career.update_project(
            project_id,
            **{
                key: str(value)
                for key, value in form.items()
                if key != "csrf_token"
            },
        )
    except (KeyError, ValueError):
        return _not_found(request, "career")
    return RedirectResponse(
        request.url_for("career_projects").include_query_params(saved="updated"),
        status_code=303,
    )

@router.get(
    "/career/resumes", response_class=HTMLResponse, name="career_resumes"
)
async def career_resumes(request: Request) -> HTMLResponse:
    repository = request.app.state.career
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_resumes.html",
        context={
            "active_page": "career",
            "resumes": repository.resumes(),
            "documents": repository.documents("resume"),
            "projects": repository.projects(),
            "resume_statuses": RESUME_STATUSES,
        },
    )

@router.post("/career/resumes", name="create_resume_version")
async def create_resume_version(
    request: Request,
    title: str = Form(...),
    target_role: str = Form(default=""),
    document_id: str = Form(default=""),
    project_ids: list[str] = Form(default=[]),
    status: str = Form(default="draft"),
    notes: str = Form(default=""),
) -> HTMLResponse:
    try:
        request.app.state.career.add_resume(
            title=title,
            target_role=target_role,
            document_id=document_id,
            project_ids=tuple(project_ids),
            status=status,
            notes=notes,
        )
    except ValueError as error:
        repository = request.app.state.career
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_resumes.html",
            context={
                "active_page": "career",
                "resumes": repository.resumes(),
                "documents": repository.documents("resume"),
                "projects": repository.projects(),
                "resume_statuses": RESUME_STATUSES,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("career_resumes").include_query_params(saved="created"),
        status_code=303,
    )

@router.post(
    "/career/resumes/{resume_id}/status", name="change_resume_status"
)
async def change_resume_status(
    request: Request, resume_id: str, status: str = Form(...)
) -> HTMLResponse:
    try:
        request.app.state.career.update_resume_status(resume_id, status)
    except (KeyError, ValueError):
        return _not_found(request, "career")
    return RedirectResponse(request.url_for("career_resumes"), status_code=303)

@router.get("/career/jobs", response_class=HTMLResponse, name="career_jobs")
async def career_jobs(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_jobs.html",
        context={
            "active_page": "career",
            "jobs": request.app.state.career.jobs(),
            "job_statuses": JOB_STATUSES,
        },
    )

@router.post("/career/jobs", name="create_career_job")
async def create_career_job(
    request: Request,
    company: str = Form(...),
    title: str = Form(...),
    jd_text: str = Form(...),
    location: str = Form(default=""),
    source_url: str = Form(default=""),
    notes: str = Form(default=""),
) -> HTMLResponse:
    try:
        job = request.app.state.career.add_job(
            company=company,
            title=title,
            jd_text=jd_text,
            location=location,
            source_url=source_url,
            notes=notes,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_jobs.html",
            context={
                "active_page": "career",
                "jobs": request.app.state.career.jobs(),
                "job_statuses": JOB_STATUSES,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("career_job_detail", job_id=job.id), status_code=303
    )

@router.get(
    "/career/jobs/{job_id}", response_class=HTMLResponse, name="career_job_detail"
)
async def career_job_detail(request: Request, job_id: str) -> HTMLResponse:
    repository = request.app.state.career
    job = repository.job(job_id)
    if job is None:
        return _not_found(request, "career")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_job_detail.html",
        context=_career_job_context(request, job),
    )

@router.post("/career/jobs/{job_id}/status", name="change_job_status")
async def change_job_status(
    request: Request,
    job_id: str,
    status: str = Form(...),
    note: str = Form(default=""),
) -> HTMLResponse:
    try:
        request.app.state.career.update_job_status(job_id, status, note)
    except (KeyError, ValueError):
        return _not_found(request, "career")
    return RedirectResponse(
        request.url_for("career_job_detail", job_id=job_id), status_code=303
    )

@router.post("/career/jobs/{job_id}/skills", name="save_job_skill_gap")
async def save_job_skill_gap(
    request: Request,
    job_id: str,
    skill_id: str = Form(...),
    importance: int = Form(...),
    evidence: str = Form(default=""),
    gap_note: str = Form(default=""),
) -> HTMLResponse:
    try:
        request.app.state.career.set_job_skill_gap(
            job_id=job_id,
            skill_id=skill_id,
            importance=importance,
            evidence=evidence,
            gap_note=gap_note,
        )
    except ValueError:
        return _not_found(request, "career")
    return RedirectResponse(
        request.url_for("career_job_detail", job_id=job_id), status_code=303
    )

@router.post(
    "/career/jobs/{job_id}/skills/preview",
    response_class=HTMLResponse,
    name="preview_job_skills",
)
async def preview_job_skills(request: Request, job_id: str) -> HTMLResponse:
    job = request.app.state.career.job(job_id)
    analyzer = getattr(request.app.state.llm_client, "job_skill_candidate", None)
    if (
        job is None
        or not request.app.state.llm_client.enabled
        or not callable(analyzer)
    ):
        return _not_found(request, "career")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="llm_disclosure.html",
        context=_disclosure_context(
            request,
            purpose="从不可信职位描述中提取技能要求候选",
            task_type=ModelTaskKind.JOB_SKILLS.value,
            source_labels=(f"{job.company} · {job.title}",),
            submit_url=request.url_for("analyze_job_skills", job_id=job.id),
            outbound_text=job.jd_text,
            back_url=request.url_for("career_job_detail", job_id=job.id),
        ),
    )

@router.post(
    "/career/jobs/{job_id}/skills/manual", name="manual_job_skills"
)
async def manual_job_skills(request: Request, job_id: str) -> HTMLResponse:
    job = request.app.state.career.job(job_id)
    if job is None or not job.jd_text.strip():
        return _not_found(request, "career")
    try:
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.JOB_SKILLS.value,
            purpose="从不可信职位描述中提取技能要求候选",
            source_labels=(f"{job.company} · {job.title}",),
            payload=job.jd_text,
            return_url=str(
                request.url_for("career_job_detail", job_id=job.id)
            ),
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_job_detail.html",
            context=_career_job_context(request, job, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post(
    "/career/jobs/{job_id}/skills/analyze",
    response_class=HTMLResponse,
    name="analyze_job_skills",
)
async def analyze_job_skills(
    request: Request,
    job_id: str,
    outbound_text: str = Form(...),
) -> HTMLResponse:
    job = request.app.state.career.job(job_id)
    client = request.app.state.llm_client
    analyzer = getattr(client, "job_skill_candidate", None)
    if job is None or not client.enabled or not callable(analyzer):
        return _not_found(request, "career")
    try:
        candidates = await asyncio.to_thread(analyzer, outbound_text)
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_job_detail.html",
            context=_career_job_context(
                request,
                job,
                error=f"职位要求分析失败：{error}",
            ),
            status_code=502,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="career_job_detail.html",
        context=_career_job_context(
            request,
            job,
            skill_candidates=tuple(candidates),
        ),
    )

@router.post(
    "/career/jobs/{job_id}/skills/confirm",
    name="confirm_job_skills",
)
async def confirm_job_skills(request: Request, job_id: str) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    job = repository.job(job_id)
    if job is None:
        return _not_found(request, "career")
    form = await request.form()
    selected = list(dict.fromkeys(str(value) for value in form.getlist("selected")))
    try:
        if not selected or len(selected) > 30:
            raise ValueError("请至少选择一条技能候选")
        reviewed: list[tuple[str, str, int, str]] = []
        for raw_index in selected:
            if not raw_index.isdigit():
                raise ValueError("技能候选编号无效")
            index = int(raw_index)
            name = str(form.get(f"name_{index}", "")).strip()
            category = str(form.get(f"category_{index}", "")).strip()
            requirement = str(form.get(f"requirement_{index}", "")).strip()
            importance = int(str(form.get(f"importance_{index}", "3")))
            if not name or len(name) > 120 or importance not in range(1, 6):
                raise ValueError("技能名称或重要度无效")
            reviewed.append((name, category[:120], importance, requirement[:2000]))
    except (TypeError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="career_job_detail.html",
            context=_career_job_context(request, job, error=str(error)),
            status_code=422,
        )
    for name, category, importance, requirement in reviewed:
        skill = repository.find_or_add_skill(name=name, category=category)
        repository.set_job_skill_gap(
            job_id=job.id,
            skill_id=skill.id,
            importance=importance,
            gap_note=requirement,
        )
    return RedirectResponse(
        request.url_for("career_job_detail", job_id=job.id).include_query_params(
            saved="skills",
        ),
        status_code=303,
    )

@router.get("/learning", response_class=HTMLResponse, name="learning")
async def learning(request: Request) -> HTMLResponse:
    repository = request.app.state.career
    repository.seed_agent_reliability_campaign(
        str(REPO_ROOT.parent / "agent-reliability-arena"),
    )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="learning.html",
        context={
            "active_page": "learning",
            "skills": repository.skills(),
            "tasks": repository.learning_tasks(),
            "gaps": repository.gaps(),
            "jobs": {job.id: job for job in repository.jobs()},
            "learning_statuses": LEARNING_STATUSES,
            "projects": repository.projects(),
            "content_items": eligible_items(_collection(request)),
            "campaigns": repository.campaigns(),
            "campaign_xp": {
                campaign.id: repository.campaign_xp(campaign.id)
                for campaign in repository.campaigns()
            },
        },
    )

def campaign_context(
    request: Request,
    campaign_id: str,
    *,
    error: str | None = None,
    notice: str | None = None,
) -> dict | None:
    repository: CareerRepository = request.app.state.career
    campaign = repository.campaign(campaign_id)
    if campaign is None:
        return None
    quests = repository.quests(campaign_id)
    tasks = {task.id: task for task in repository.learning_tasks()}
    return {
        "active_page": "learning",
        "campaign": campaign,
        "quests": quests,
        "quest_evidence": {
            quest.id: repository.quest_evidence(quest.id) for quest in quests
        },
        "tasks": tasks,
        "earned_xp": repository.campaign_xp(campaign_id),
        "error": error,
        "notice": notice,
    }

@router.get(
    "/learning/campaigns/{campaign_id}",
    response_class=HTMLResponse,
    name="learning_campaign",
)
async def learning_campaign(
    request: Request,
    campaign_id: str,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    notices = {
        "started": "关卡已开始。通关靠证据，不靠签到。",
        "evidence": "验收证据已保存到本地私人数据库。",
        "cleared": "关卡已通关，XP 已到账，下一关已解锁。",
    }
    context = campaign_context(
        request,
        campaign_id,
        notice=notices.get(saved or ""),
    )
    if context is None:
        return _not_found(request, "learning")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="learning_campaign.html",
        context=context,
    )

@router.post(
    "/learning/campaigns/{campaign_id}/quests/{quest_id}/start",
    name="start_campaign_quest",
)
async def start_campaign_quest(
    request: Request,
    campaign_id: str,
    quest_id: str,
) -> HTMLResponse:
    try:
        quest = request.app.state.career.start_quest(quest_id)
        if quest.campaign_id != campaign_id:
            raise KeyError(quest_id)
    except (KeyError, ValueError):
        return _not_found(request, "learning")
    return RedirectResponse(
        request.url_for(
            "learning_campaign", campaign_id=campaign_id
        ).include_query_params(
            saved="started",
        ),
        status_code=303,
    )

@router.post(
    "/learning/campaigns/{campaign_id}/quests/{quest_id}/evidence",
    name="submit_quest_evidence",
)
async def submit_quest_evidence(
    request: Request,
    campaign_id: str,
    quest_id: str,
    commit_sha: str = Form(...),
    test_result: str = Form(...),
    reflection: str = Form(default=""),
    evidence_url: str = Form(default=""),
) -> HTMLResponse:
    try:
        quest = request.app.state.career.quest(quest_id)
        if quest is None or quest.campaign_id != campaign_id:
            raise KeyError(quest_id)
        request.app.state.career.add_quest_evidence(
            quest_id,
            commit_sha=commit_sha,
            test_result=test_result,
            reflection=reflection,
            evidence_url=evidence_url,
        )
    except KeyError:
        return _not_found(request, "learning")
    except ValueError as error:
        context = campaign_context(request, campaign_id, error=str(error))
        if context is None:
            return _not_found(request, "learning")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="learning_campaign.html",
            context=context,
            status_code=422,
        )
    return RedirectResponse(
        request.url_for(
            "learning_campaign", campaign_id=campaign_id
        ).include_query_params(
            saved="evidence",
        ),
        status_code=303,
    )

@router.post(
    "/learning/campaigns/{campaign_id}/quests/{quest_id}/clear",
    name="clear_campaign_quest",
)
async def clear_campaign_quest(
    request: Request,
    campaign_id: str,
    quest_id: str,
    confirmation: str = Form(default=""),
) -> HTMLResponse:
    if confirmation.strip() != "确认通关":
        context = campaign_context(
            request,
            campaign_id,
            error="请输入“确认通关”后再结算 XP。",
        )
        if context is None:
            return _not_found(request, "learning")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="learning_campaign.html",
            context=context,
            status_code=422,
        )
    try:
        quest = request.app.state.career.quest(quest_id)
        if quest is None or quest.campaign_id != campaign_id:
            raise KeyError(quest_id)
        request.app.state.career.clear_quest(quest_id)
    except KeyError:
        return _not_found(request, "learning")
    except ValueError as error:
        context = campaign_context(request, campaign_id, error=str(error))
        if context is None:
            return _not_found(request, "learning")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="learning_campaign.html",
            context=context,
            status_code=422,
        )
    return RedirectResponse(
        request.url_for(
            "learning_campaign", campaign_id=campaign_id
        ).include_query_params(
            saved="cleared",
        ),
        status_code=303,
    )

@router.post("/learning/skills", name="create_skill")
async def create_skill(
    request: Request,
    name: str = Form(...),
    category: str = Form(default=""),
    current_level: int = Form(default=0),
    target_level: int = Form(default=3),
    notes: str = Form(default=""),
) -> HTMLResponse:
    try:
        request.app.state.career.add_skill(
            name=name,
            category=category,
            current_level=current_level,
            target_level=target_level,
            notes=notes,
        )
    except ValueError as error:
        repository = request.app.state.career
        return TEMPLATES.TemplateResponse(
            request=request,
            name="learning.html",
            context={
                "active_page": "learning",
                "skills": repository.skills(),
                "tasks": repository.learning_tasks(),
                "gaps": repository.gaps(),
                "jobs": {job.id: job for job in repository.jobs()},
                "learning_statuses": LEARNING_STATUSES,
                "projects": repository.projects(),
                "content_items": eligible_items(_collection(request)),
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(request.url_for("learning"), status_code=303)
@router.post("/learning/tasks", name="create_learning_task")
async def create_learning_task(
    request: Request,
    skill_id: str = Form(...),
    title: str = Form(...),
    status: str = Form(default="backlog"),
    priority: int = Form(default=3),
    linked_content_id: str = Form(default=""),
    linked_project_id: str = Form(default=""),
    notes: str = Form(default=""),
) -> HTMLResponse:
    try:
        request.app.state.career.add_learning_task(
            skill_id=skill_id,
            title=title,
            status=status,
            priority=priority,
            linked_content_id=linked_content_id,
            linked_project_id=linked_project_id,
            notes=notes,
        )
    except ValueError:
        return _not_found(request, "learning")
    return RedirectResponse(request.url_for("learning"), status_code=303)

@router.post(
    "/learning/tasks/{task_id}/status", name="change_learning_task_status"
)
async def change_learning_task_status(
    request: Request, task_id: str, status: str = Form(...)
) -> HTMLResponse:
    try:
        request.app.state.career.update_learning_task_status(task_id, status)
    except (KeyError, ValueError):
        return _not_found(request, "learning")
    return RedirectResponse(request.url_for("learning"), status_code=303)
