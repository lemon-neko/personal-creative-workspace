"""Native resume studio routes built on the existing private career store."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.career import RESUME_STATUSES, CareerRepository
from app.model_gateway import ModelGateway, ModelTaskKind
from app.resume_pdf import ResumePdfError, render_resume_pdf
from app.resume_assets import validate_resume_image
from app.resume_docx import DocxResumeCandidate, parse_resume_docx
from app.resume_import import import_primary_resume
from app.resume_studio import (
    RESUME_TEMPLATE_KEYS,
    RESUME_TEMPLATE_LABELS,
    StructuredResume,
    build_import_candidate,
    display_sections,
    deserialize_structured_resume,
    group_work_experience,
    match_resume,
    normalize_structured_resume,
    project_has_structured_content,
    project_structure_candidates,
)
from app.web import TEMPLATES, not_found


router = APIRouter()


def _not_found(request: Request) -> HTMLResponse:
    return not_found(request, "career")


def _lines(value: Any) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _values(form: Any, name: str) -> list[str]:
    return [str(value).strip() for value in form.getlist(name)]


def _resume_from_form(form: Any, repository: CareerRepository) -> StructuredResume:
    work_rows = []
    work_fields = {
        key: _values(form, f"work_{key}")
        for key in ("title", "company", "location", "years", "description")
    }
    work_count = max((len(values) for values in work_fields.values()), default=0)
    for index in range(work_count):
        row = {
            key: values[index] if index < len(values) else ""
            for key, values in work_fields.items()
        }
        row["description"] = _lines(row["description"])
        if any(value for value in row.values()):
            work_rows.append(row)

    education_rows = []
    education_fields = {
        key: _values(form, f"education_{key}")
        for key in ("institution", "degree", "years", "description")
    }
    education_count = max(
        (len(values) for values in education_fields.values()), default=0
    )
    for index in range(education_count):
        row = {
            key: values[index] if index < len(values) else ""
            for key, values in education_fields.items()
        }
        if any(row.values()):
            education_rows.append(row)

    project_lookup = {project.id: project for project in repository.projects()}
    project_rows = []
    for project_id in dict.fromkeys(_values(form, "project_ids")):
        project = project_lookup.get(project_id)
        if project is None:
            raise ValueError("简历引用了不存在的项目证据")
        project_rows.append(
            {
                "project_id": project.id,
                "name": str(form.get(f"project_name_{project.id}", project.name)),
                "role": str(form.get(f"project_role_{project.id}", project.role)),
                "years": str(
                    form.get(f"project_years_{project.id}", project.timeframe)
                ),
                "github": str(form.get(f"project_github_{project.id}", "")),
                "website": str(form.get(f"project_website_{project.id}", "")),
                "summary": str(form.get(f"project_summary_{project.id}", "")),
                "tech_stack": str(
                    form.get(f"project_tech_stack_{project.id}", "")
                ),
                "responsibilities": _lines(
                    form.get(f"project_responsibilities_{project.id}", "")
                ),
                "description": _lines(
                    form.get(
                        f"project_description_{project.id}",
                        "\n".join(
                            value
                            for value in (
                                project.summary,
                                project.actions,
                                project.outcome,
                            )
                            if value
                        ),
                    )
                ),
            }
        )

    visible = set(_values(form, "visible_sections"))
    sections = [
        {
            "key": key,
            "title": str(form.get(f"section_title_{key}", title)),
            "visible": key in visible,
            "order": int(str(form.get(f"section_order_{key}", index))),
        }
        for index, (key, title) in enumerate(
            (
                ("summary", "职业摘要"),
                ("work_experience", "工作经历"),
                ("education", "教育经历"),
                ("projects", "项目经历"),
                ("skills", "专业技能"),
                ("self_evaluation", "自我评价"),
            )
        )
    ]
    return normalize_structured_resume(
        {
            "personal_info": {
                key: str(form.get(f"personal_{key}", ""))
                for key in (
                    "name",
                    "title",
                    "email",
                    "phone",
                    "location",
                    "website",
                    "github",
                    "experience_years",
                    "age",
                )
            },
            "summary": str(form.get("summary", "")),
            "work_experience": work_rows,
            "education": education_rows,
            "projects": project_rows,
            "skills": _lines(form.get("skills", "")),
            "self_evaluation": _lines(form.get("self_evaluation", "")),
            "sections": sections,
        }
    )


def _resume_context(
    request: Request,
    structured: StructuredResume,
    *,
    resume=None,
    title: str = "",
    target_role: str = "",
    document_id: str = "",
    photo_url: str = "",
    import_diagnostics: tuple[str, ...] = (),
    error: str | None = None,
    template_key: str = "",
) -> dict[str, Any]:
    repository: CareerRepository = request.app.state.career
    structure_candidates = project_structure_candidates(
        structured, repository.projects()
    )
    project_editor_rows = structure_candidates if resume is None else structured.projects
    selected = {
        str(row.get("project_id", "")): row for row in project_editor_rows
    }
    work_rows = list(structured.work_experience) + [
        {"title": "", "company": "", "location": "", "years": "", "description": []}
    ]
    education_rows = list(structured.education) + [
        {"institution": "", "degree": "", "years": "", "description": ""}
    ]
    active_template_key = template_key or (
        resume.template_key
        if resume
        else "china_single_photo"
        if photo_url
        else "ats_single"
    )
    if active_template_key not in RESUME_TEMPLATE_KEYS:
        active_template_key = "ats_single"
    return {
        "active_page": "career",
        "resume": resume,
        "structured": structured,
        "resume_title": title or (resume.title if resume else "主简历"),
        "target_role": target_role or (resume.target_role if resume else ""),
        "document_id": document_id,
        "photo_url": photo_url,
        "import_diagnostics": import_diagnostics,
        "projects": repository.projects(),
        "selected_projects": selected,
        "project_structure_candidates": structure_candidates,
        "legacy_project_count": sum(
            not project_has_structured_content(row) for row in structured.projects
        ),
        "work_rows": work_rows,
        "education_rows": education_rows,
        "source_current": repository.resume_source_is_current(resume)
        if resume and resume.is_structured
        else True,
        "jobs": repository.jobs(),
        "resume_statuses": RESUME_STATUSES,
        "resume_template_labels": RESUME_TEMPLATE_LABELS,
        "active_template_key": active_template_key,
        "display_sections": display_sections(structured, active_template_key),
        "work_groups": group_work_experience(structured.work_experience),
        "llm_enabled": request.app.state.model_gateway.enabled,
        "error": error,
    }


def _document_import_candidate(
    repository: CareerRepository, document
) -> DocxResumeCandidate:
    if document.stored_name.lower().endswith(".docx"):
        content = repository.document_path(document).read_bytes()
        return parse_resume_docx(content, repository.profile(), repository.projects())
    return DocxResumeCandidate(
        build_import_candidate(
            document.extracted_text, repository.profile(), repository.projects()
        ),
        None,
        ("该文件不包含可提取的证件照",),
    )


def _photo_data_url(repository: CareerRepository, resume) -> str:
    asset = repository.resume_photo(resume)
    if asset is None:
        return ""
    content = repository.resume_asset_path(asset).read_bytes()
    return validate_resume_image(content).data_url


def _tailor_material(repository: CareerRepository, resume, job) -> str:
    structured = repository.structured_resume(resume)
    project_lookup = {project.id: project for project in repository.projects()}
    evidence = {
        "career-profile": {
            "target_roles": repository.profile().target_roles,
            "experience": repository.profile().experience,
            "skills": repository.profile().skills,
            "facts": repository.profile().facts,
        },
        **{
            project_id: project_lookup[project_id].__dict__
            for project_id in resume.project_ids
            if project_id in project_lookup
        },
    }
    return json.dumps(
        {
            "resume_id": resume.id,
            "resume_revision": resume.revision,
            "resume": structured.to_payload(),
            "job": {
                "id": job.id,
                "company": job.company,
                "title": job.title,
                "jd_text": job.jd_text,
                "confirmed_skills": list(repository.confirmed_skill_names(job.id)),
            },
            "evidence": evidence,
            "allowed_evidence_ids": list(evidence),
        },
        ensure_ascii=False,
    )


def _parse_material(repository: CareerRepository, document) -> str:
    return json.dumps(
        {
            "document_id": document.id,
            "document_name": document.original_name,
            "document_text": document.extracted_text,
            "profile": repository.profile().__dict__,
            "projects": [project.__dict__ for project in repository.projects()],
            "allowed_project_ids": [project.id for project in repository.projects()],
        },
        ensure_ascii=False,
    )


@router.get("/career/resumes", response_class=HTMLResponse, name="career_resumes")
async def career_resumes(request: Request) -> HTMLResponse:
    return RedirectResponse(str(request.url_for("career").include_query_params(
        saved=request.query_params.get("saved", ""))) + "#resumes", status_code=302)


@router.get("/career/resumes/{resume_id}/tailor", name="resume_tailor_start")
async def resume_tailor_start(request: Request, resume_id: str, job_id: str) -> HTMLResponse:
    repository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or resume.resume_kind != "master" or repository.job(job_id) is None:
        return _not_found(request)
    return RedirectResponse(request.url_for("resume_match", resume_id=resume_id, job_id=job_id), status_code=302)


@router.get("/career/jobs/{job_id}/submissions/{submission_id}", name="job_submission_detail")
async def job_submission_detail(request: Request, job_id: str, submission_id: int) -> HTMLResponse:
    repository = request.app.state.career
    snapshot = repository.job_submission(submission_id)
    job = repository.job(job_id)
    if snapshot is None or snapshot.job_id != job_id or job is None:
        return _not_found(request)
    structured = deserialize_structured_resume(snapshot.structured_data)
    return TEMPLATES.TemplateResponse(
        request=request, name="career_submission.html",
        context={
            **_resume_context(request, structured, title=snapshot.title, target_role=snapshot.target_role,
                              template_key=snapshot.template_key),
            "snapshot": snapshot, "job": job,
            "history": repository.job_submissions(job_id),
            "photo_url": str(request.url_for("job_submission_photo", job_id=job_id, submission_id=snapshot.id))
                         if snapshot.photo_asset_id else "",
            "show_photo": True,
        },
    )


@router.get("/career/jobs/{job_id}/submissions/{submission_id}/photo", name="job_submission_photo")
async def job_submission_photo(request: Request, job_id: str, submission_id: int) -> Response:
    repository = request.app.state.career
    snapshot = repository.job_submission(submission_id)
    if snapshot is None or snapshot.job_id != job_id or not snapshot.photo_asset_id:
        return _not_found(request)
    asset = repository.resume_asset(snapshot.photo_asset_id)
    if asset is None:
        return _not_found(request)
    try:
        validated = validate_resume_image(repository.resume_asset_path(asset).read_bytes())
    except (FileNotFoundError, ValueError):
        return _not_found(request)
    return Response(validated.content, media_type=validated.media_type)


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
        return HTMLResponse(str(error), status_code=422)
    return RedirectResponse(
        request.url_for("career_resumes").include_query_params(saved="legacy"),
        status_code=303,
    )


@router.post("/career/resumes/{resume_id}/status", name="change_resume_status")
async def change_resume_status(
    request: Request, resume_id: str, status: str = Form(...)
) -> HTMLResponse:
    try:
        request.app.state.career.update_resume_status(resume_id, status)
    except KeyError:
        return _not_found(request)
    except ValueError as error:
        return HTMLResponse(str(error), status_code=422)
    return RedirectResponse(request.url_for("career_resumes"), status_code=303)


@router.post(
    "/career/resumes/import/preview",
    response_class=HTMLResponse,
    name="resume_import_preview",
)
async def resume_import_preview(
    request: Request, document_id: str = Form(...)
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    document = repository.document(document_id)
    if document is None or document.kind != "resume" or not document.extracted_text:
        return _not_found(request)
    try:
        candidate = _document_import_candidate(repository, document)
    except (FileNotFoundError, ValueError) as error:
        return HTMLResponse(str(error), status_code=422)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="resume_import_preview.html",
        context=_resume_context(
            request,
            candidate.resume,
            title=f"主简历 · {document.original_name}",
            target_role=repository.profile().target_roles.splitlines()[0]
            if repository.profile().target_roles
            else "",
            document_id=document.id,
            photo_url=str(
                request.url_for("resume_document_portrait", document_id=document.id)
            )
            if candidate.portrait
            else "",
            import_diagnostics=candidate.diagnostics,
        ),
    )


@router.get(
    "/career/documents/{document_id}/portrait",
    name="resume_document_portrait",
)
async def resume_document_portrait(request: Request, document_id: str) -> Response:
    repository: CareerRepository = request.app.state.career
    document = repository.document(document_id)
    if (
        document is None
        or document.kind != "resume"
        or not document.stored_name.endswith(".docx")
    ):
        return _not_found(request)
    try:
        candidate = _document_import_candidate(repository, document)
    except (FileNotFoundError, ValueError):
        return _not_found(request)
    if candidate.portrait is None:
        return _not_found(request)
    return Response(
        candidate.portrait.content, media_type=candidate.portrait.media_type
    )


@router.post(
    "/career/resumes/import/{document_id}/model-preview",
    response_class=HTMLResponse,
    name="resume_import_model_preview",
)
async def resume_import_model_preview(
    request: Request, document_id: str
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    document = repository.document(document_id)
    if document is None or document.kind != "resume" or not document.extracted_text:
        return _not_found(request)
    config = request.app.state.model_gateway.config
    return TEMPLATES.TemplateResponse(
        request=request,
        name="llm_disclosure.html",
        context={
            "active_page": "career",
            "purpose": "把简历资料整理为结构化主简历候选",
            "source_labels": (document.original_name,),
            "target": config.base_url if config else "",
            "submit_url": request.url_for(
                "resume_import_model_run", document_id=document.id
            ),
            "outbound_text": _parse_material(repository, document),
            "back_url": request.url_for("career_resumes"),
            "task_type": ModelTaskKind.RESUME_PARSE.value,
            "hidden_fields": {},
        },
    )


@router.post(
    "/career/resumes/import/{document_id}/model-run",
    response_class=HTMLResponse,
    name="resume_import_model_run",
)
async def resume_import_model_run(
    request: Request,
    document_id: str,
    outbound_text: str = Form(...),
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    document = repository.document(document_id)
    if document is None or document.kind != "resume":
        return _not_found(request)
    try:
        candidate = await asyncio.to_thread(
            repository.resume_service.analyze_import,
            outbound_text,
            request.app.state.model_gateway.resume_parse_candidate,
        )
    except (
        httpx.HTTPError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as error:
        return HTMLResponse(str(error), status_code=422)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="resume_import_preview.html",
        context=_resume_context(
            request,
            candidate,
            title=f"主简历 · {document.original_name}",
            target_role=repository.profile().target_roles.splitlines()[0]
            if repository.profile().target_roles
            else "",
            document_id=document.id,
        ),
    )


@router.post(
    "/career/resumes/import/{document_id}/manual",
    name="resume_import_manual",
)
async def resume_import_manual(request: Request, document_id: str) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    document = repository.document(document_id)
    if document is None or document.kind != "resume" or not document.extracted_text:
        return _not_found(request)
    task = request.app.state.model_tasks.create(
        task_type=ModelTaskKind.RESUME_PARSE.value,
        purpose="把简历资料整理为结构化主简历候选",
        source_labels=(document.original_name,),
        payload=_parse_material(repository, document),
        return_url=str(request.url_for("career_resumes")),
    )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )


@router.post("/career/resumes/import/confirm", name="resume_import_confirm")
async def resume_import_confirm(request: Request) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    form = await request.form()
    structured: StructuredResume | None = None
    try:
        structured = _resume_from_form(form, repository)
        document_id = str(form.get("document_id", ""))
        existing = repository.primary_resume_for_document(document_id)
        if existing is not None:
            return RedirectResponse(
                request.url_for("resume_detail", resume_id=existing.id), status_code=303
            )
        document = repository.document(document_id)
        if document is None:
            raise ValueError("关联文档不存在")
        if document.stored_name.lower().endswith(".docx"):
            result = import_primary_resume(
                repository,
                document,
                title=str(form.get("title", "主简历")),
                target_role=str(form.get("target_role", "")),
                structured=structured,
                include_photo=str(form.get("include_photo", "")) == "1",
            )
            resume = result.resume
            if resume is None:
                raise ValueError("主简历创建失败")
        else:
            resume = repository.resume_service.import_structured_resume(
                document,
                title=str(form.get("title", "主简历")),
                target_role=str(form.get("target_role", "")),
                structured=structured,
            )
    except (TypeError, ValueError) as error:
        fallback = structured or normalize_structured_resume({})
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_import_preview.html",
            context=_resume_context(
                request,
                fallback,
                title=str(form.get("title", "主简历")),
                target_role=str(form.get("target_role", "")),
                document_id=str(form.get("document_id", "")),
                error=str(error),
            ),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=resume.id), status_code=303
    )


@router.get(
    "/career/resumes/{resume_id}", response_class=HTMLResponse, name="resume_detail"
)
async def resume_detail(request: Request, resume_id: str) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None:
        return _not_found(request)
    if not resume.is_structured:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_legacy_detail.html",
            context={
                "active_page": "career",
                "resume": resume,
                "document": repository.document(resume.document_id or ""),
                "resume_statuses": RESUME_STATUSES,
            },
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="resume_detail.html",
        context=_resume_context(
            request,
            repository.structured_resume(resume),
            resume=resume,
            photo_url=str(request.url_for("resume_photo", resume_id=resume.id))
            if resume.photo_asset_id
            else "",
        ),
    )


def _project_structure_context(
    request: Request,
    resume,
    structured: StructuredResume,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    repository: CareerRepository = request.app.state.career
    candidates = project_structure_candidates(structured, repository.projects())
    return {
        "active_page": "career",
        "resume": resume,
        "structured": structured,
        "candidates": candidates,
        "pending_count": sum(row["needs_confirmation"] for row in candidates),
        "error": error,
    }


@router.get(
    "/career/resumes/{resume_id}/projects/structure",
    response_class=HTMLResponse,
    name="resume_project_structure_preview",
)
async def resume_project_structure_preview(
    request: Request, resume_id: str
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or not resume.is_structured:
        return _not_found(request)
    structured = repository.structured_resume(resume)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="resume_project_structure.html",
        context=_project_structure_context(request, resume, structured),
    )


@router.post(
    "/career/resumes/{resume_id}/projects/structure",
    response_class=HTMLResponse,
    name="resume_project_structure_confirm",
)
async def resume_project_structure_confirm(
    request: Request, resume_id: str
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or not resume.is_structured:
        return _not_found(request)
    form = await request.form()
    current = repository.structured_resume(resume)
    payload = current.to_payload()
    try:
        for row in payload["projects"]:
            project_id = str(row.get("project_id", ""))
            summary = str(
                form.get(f"project_summary_{project_id}", row.get("summary", ""))
            )
            tech_stack = str(
                form.get(
                    f"project_tech_stack_{project_id}",
                    "\n".join(row.get("tech_stack", [])),
                )
            )
            responsibilities = _lines(
                form.get(
                    f"project_responsibilities_{project_id}",
                    "\n".join(row.get("responsibilities", [])),
                )
            )
            if not summary.strip() and not tech_stack.strip() and not responsibilities:
                raise ValueError(f"项目“{row.get('name', '')}”至少保留一层有效内容")
            row["summary"] = summary
            row["tech_stack"] = tech_stack
            row["responsibilities"] = responsibilities
        structured = normalize_structured_resume(payload)
        saved = repository.update_structured_resume(
            resume.id,
            structured=structured,
            expected_revision=int(str(form.get("revision", "-1"))),
            title=resume.title,
            target_role=resume.target_role,
            notes=resume.notes,
            template_key=resume.template_key,
        )
    except RuntimeError as error:
        latest = repository.resume(resume.id)
        latest_structured = (
            repository.structured_resume(latest)
            if latest is not None and latest.is_structured
            else current
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_project_structure.html",
            context=_project_structure_context(
                request, latest or resume, latest_structured, error=str(error)
            ),
            status_code=409,
        )
    except (TypeError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_project_structure.html",
            context=_project_structure_context(
                request, resume, current, error=str(error)
            ),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=saved.id).include_query_params(
            saved="project-structure"
        ),
        status_code=303,
    )


@router.get("/career/resumes/{resume_id}/photo", name="resume_photo")
async def resume_photo(request: Request, resume_id: str) -> Response:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or not resume.is_structured:
        return _not_found(request)
    asset = repository.resume_photo(resume)
    if asset is None:
        return _not_found(request)
    try:
        content = repository.resume_asset_path(asset).read_bytes()
        validated = validate_resume_image(content)
    except (FileNotFoundError, ValueError):
        return _not_found(request)
    return Response(validated.content, media_type=validated.media_type)


@router.post("/career/resumes/{resume_id}/photo", name="replace_resume_photo")
async def replace_resume_photo(
    request: Request,
    resume_id: str,
    revision: int = Form(...),
    upload: UploadFile = File(...),
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or not resume.is_structured:
        return _not_found(request)
    asset = None
    try:
        content = await upload.read(5 * 1024 * 1024 + 1)
        image = validate_resume_image(content)
        asset = repository.store_resume_asset(image)
        repository.update_resume_photo(
            resume.id, expected_revision=revision, photo_asset_id=asset.id
        )
    except RuntimeError as error:
        if asset is not None:
            repository.delete_resume_asset_if_unreferenced(asset.id)
        return HTMLResponse(str(error), status_code=409)
    except ValueError as error:
        if asset is not None:
            repository.delete_resume_asset_if_unreferenced(asset.id)
        return HTMLResponse(str(error), status_code=422)
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=resume.id).include_query_params(
            saved="photo"
        ),
        status_code=303,
    )


@router.post("/career/resumes/{resume_id}/photo/remove", name="remove_resume_photo")
async def remove_resume_photo(
    request: Request,
    resume_id: str,
    revision: int = Form(...),
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    try:
        repository.update_resume_photo(
            resume_id, expected_revision=revision, photo_asset_id=""
        )
    except KeyError:
        return _not_found(request)
    except RuntimeError as error:
        return HTMLResponse(str(error), status_code=409)
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=resume_id).include_query_params(
            saved="photo-removed"
        ),
        status_code=303,
    )


@router.post("/career/resumes/{resume_id}", name="save_resume_detail")
async def save_resume_detail(request: Request, resume_id: str) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or not resume.is_structured:
        return _not_found(request)
    form = await request.form()
    structured: StructuredResume | None = None
    try:
        structured = _resume_from_form(form, repository)
        saved = repository.update_structured_resume(
            resume_id,
            structured=structured,
            expected_revision=int(str(form.get("revision", "-1"))),
            title=str(form.get("title", "")),
            target_role=str(form.get("target_role", "")),
            notes=str(form.get("notes", "")),
            template_key=str(form.get("template_key", resume.template_key)),
        )
    except RuntimeError as error:
        latest = repository.resume(resume_id)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_conflict.html",
            context={
                "active_page": "career",
                "resume": latest,
                "submitted": str(form.get("summary", "")),
                "latest": repository.structured_resume(latest).summary
                if latest and latest.is_structured
                else "",
                "error": str(error),
            },
            status_code=409,
        )
    except (TypeError, ValueError) as error:
        fallback = structured or repository.structured_resume(resume)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_detail.html",
            context=_resume_context(
                request,
                fallback,
                resume=resume,
                error=str(error),
                template_key=str(form.get("template_key", resume.template_key)),
            ),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=saved.id).include_query_params(
            saved="resume"
        ),
        status_code=303,
    )


@router.get(
    "/career/resumes/{resume_id}/match/{job_id}",
    response_class=HTMLResponse,
    name="resume_match",
)
async def resume_match(request: Request, resume_id: str, job_id: str) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    job = repository.job(job_id)
    if resume is None or not resume.is_structured or job is None:
        return _not_found(request)
    report = match_resume(
        repository.structured_resume(resume), job.jd_text,
        repository.confirmed_skill_names(job.id),
    ) if job.jd_text.strip() else None
    return TEMPLATES.TemplateResponse(
        request=request,
        name="resume_match.html",
        context={
            "active_page": "career",
            "resume": resume,
            "job": job,
            "report": report,
            "llm_enabled": request.app.state.model_gateway.enabled,
        },
    )


@router.post("/career/resumes/{resume_id}/tailor/copy", name="resume_tailor_copy")
async def resume_tailor_copy(
    request: Request, resume_id: str, job_id: str = Form(...)
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    job = repository.job(job_id)
    if resume is None or resume.resume_kind != "master" or job is None:
        return _not_found(request)
    try:
        created = repository.resume_service.tailor_resume(resume, job)
    except KeyError:
        return _not_found(request)
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=created.id), status_code=303
    )


@router.post(
    "/career/resumes/{resume_id}/tailor/preview",
    response_class=HTMLResponse,
    name="resume_tailor_preview",
)
async def resume_tailor_preview(
    request: Request, resume_id: str, job_id: str = Form(...)
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    job = repository.job(job_id)
    if resume is None or resume.resume_kind != "master" or job is None:
        return _not_found(request)
    if not job.jd_text.strip():
        return HTMLResponse("请先补充 JD，再进行岗位分析或模型定制。", status_code=422)

    material = _tailor_material(repository, resume, job)
    config = request.app.state.model_gateway.config
    return TEMPLATES.TemplateResponse(
        request=request,
        name="llm_disclosure.html",
        context={
            "active_page": "career",
            "purpose": "根据已确认事实为目标职位生成字段级简历修改候选",
            "source_labels": (resume.title, f"{job.company} · {job.title}"),
            "target": config.base_url if config else "",
            "submit_url": request.url_for(
                "resume_tailor_run", resume_id=resume.id, job_id=job.id
            ),
            "outbound_text": material,
            "back_url": request.url_for(
                "resume_match", resume_id=resume.id, job_id=job.id
            ),
            "task_type": ModelTaskKind.RESUME_TAILOR.value,
            "hidden_fields": {},
        },
    )


@router.post(
    "/career/resumes/{resume_id}/tailor/run/{job_id}",
    response_class=HTMLResponse,
    name="resume_tailor_run",
)
async def resume_tailor_run(
    request: Request,
    resume_id: str,
    job_id: str,
    outbound_text: str = Form(...),
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    job = repository.job(job_id)
    gateway: ModelGateway = request.app.state.model_gateway
    if resume is None or resume.resume_kind != "master" or job is None:
        return _not_found(request)
    if not job.jd_text.strip():
        return HTMLResponse("请先补充 JD，再进行岗位分析或模型定制。", status_code=422)

    try:
        suggestions = await asyncio.to_thread(
            repository.resume_service.analyze_tailoring, resume, outbound_text, gateway.resume_tailor_candidate,
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as error:
        return HTMLResponse(str(error), status_code=422)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="resume_tailor_preview.html",
        context={
            "active_page": "career",
            "resume": resume,
            "job": job,
            "suggestions": suggestions,
        },
    )


@router.post(
    "/career/resumes/{resume_id}/tailor/manual/{job_id}",
    name="resume_tailor_manual",
)
async def resume_tailor_manual(
    request: Request, resume_id: str, job_id: str
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    job = repository.job(job_id)
    if resume is None or resume.resume_kind != "master" or job is None:
        return _not_found(request)
    if not job.jd_text.strip():
        return HTMLResponse("请先补充 JD，再进行岗位分析或模型定制。", status_code=422)

    task = request.app.state.model_tasks.create(
        task_type=ModelTaskKind.RESUME_TAILOR.value,
        purpose="为目标职位生成字段级简历修改候选",
        source_labels=(resume.title, f"{job.company} · {job.title}"),
        payload=_tailor_material(repository, resume, job),
        return_url=str(
            request.url_for("resume_match", resume_id=resume.id, job_id=job.id)
        ),
    )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )


@router.post(
    "/career/resumes/{resume_id}/tailor/confirm/{job_id}",
    name="resume_tailor_confirm",
)
async def resume_tailor_confirm(
    request: Request, resume_id: str, job_id: str
) -> HTMLResponse:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    job = repository.job(job_id)
    if resume is None or resume.resume_kind != "master" or job is None:
        return _not_found(request)
    if not job.jd_text.strip():
        return HTMLResponse("请先补充 JD，再进行岗位分析或模型定制。", status_code=422)

    form = await request.form()
    selected = {str(value) for value in form.getlist("selected")}
    if not selected:
        return HTMLResponse("请至少采用一项修改候选", status_code=422)
    raw = []
    for index in range(int(str(form.get("suggestion_count", "0")))):
        if str(index) not in selected:
            continue
        raw.append(
            {
                "path": str(form.get(f"path_{index}", "")),
                "before": str(form.get(f"before_{index}", "")),
                "after": str(form.get(f"after_{index}", "")),
                "reason": str(form.get(f"reason_{index}", "")),
                "evidence_ids": _lines(form.get(f"evidence_{index}", "")),
            }
        )
    try:
        created = repository.resume_service.tailor_resume(resume, job, raw)
    except (KeyError, TypeError, ValueError) as error:
        return HTMLResponse(str(error), status_code=422)
    return RedirectResponse(
        request.url_for("resume_detail", resume_id=created.id), status_code=303
    )


@router.get("/career/resumes/{resume_id}/pdf", name="resume_pdf")
async def resume_pdf(
    request: Request, resume_id: str, html: bool = False, variant: str = "china"
) -> Response:
    repository: CareerRepository = request.app.state.career
    resume = repository.resume(resume_id)
    if resume is None or not resume.is_structured:
        return _not_found(request)
    if variant not in {"china", "ats"}:
        return HTMLResponse("简历导出版本无效", status_code=422)
    show_photo = variant == "china" and bool(resume.photo_asset_id)
    photo_data_url = _photo_data_url(repository, resume) if show_photo else ""
    rendered = TEMPLATES.get_template("resume_print.html").render(
        resume=resume,
        structured=repository.structured_resume(resume),
        show_photo=show_photo,
        photo_data_url=photo_data_url,
        photo_url=photo_data_url,
        active_template_key=(
            resume.template_key if variant == "china" else "ats_single"
        ),
        display_sections=display_sections(
            repository.structured_resume(resume),
            resume.template_key if variant == "china" else "ats_single",
        ),
        work_groups=group_work_experience(
            repository.structured_resume(resume).work_experience
        ),
    )
    extension = "html" if html else "pdf"
    filename = f"resume-{variant}.{extension}"
    encoded_name = quote(f"{resume.title or 'resume'}-{variant}.{extension}")
    disposition = (
        f"attachment; filename=\"{filename}\"; filename*=UTF-8''{encoded_name}"
    )
    if html:
        return Response(
            rendered,
            media_type="text/html",
            headers={"Content-Disposition": disposition},
        )
    try:
        content = await render_resume_pdf(rendered)
    except ResumePdfError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="resume_pdf_error.html",
            context={"active_page": "career", "resume": resume, "error": str(error)},
            status_code=503,
        )
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )
