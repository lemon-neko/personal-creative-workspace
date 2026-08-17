"""Publishing and private video creation routes."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import httpx
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.content import ContentItem, render_markdown
from app.llm import PolishResult
from app.model_gateway import ModelTaskKind
from app.publishing import PublishingSource, WECHAT_RENDERER, resolve_publishing_source
from app.video import VIDEO_ASPECT_RATIOS, VIDEO_PLATFORMS, VIDEO_STATUSES, VIDEO_TYPES, VideoScene, inspect_opencut
from app.web import REPO_ROOT, TEMPLATES, collection, not_found
from app.workspace import create_item


router = APIRouter()


def _collection(request: Request):
    return collection(request)


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return not_found(request, active_page)


def _video_context(request: Request, *, saved: str | None = None, error: str | None = None) -> dict:
    authored = _collection(request)
    projects = request.app.state.video.projects()
    notices = {
        "created": "视频策划项目已生成。原文章没有被修改，初始分镜和私有交接文件已经就位。",
        "status": "视频项目状态已更新。",
        "plan": "视频规格与分镜已保存，旁白、字幕、Remotion Props 和 OpenCut 交接文件已重新生成。",
    }
    return {
        "active_page": "video",
        "articles": tuple(item for item in authored.items if item.kind == "article" and item.status != "archived"),
        "video_projects": projects,
        "video_counts": {status: sum(project.status == status for project in projects) for status in VIDEO_STATUSES},
        "opencut": inspect_opencut(REPO_ROOT.parent / "OpenCut"),
        "video_platforms": VIDEO_PLATFORMS,
        "video_aspect_ratios": tuple(sorted(VIDEO_ASPECT_RATIOS)),
        "video_types": VIDEO_TYPES,
        "notice": notices.get(saved or ""),
        "error": error,
    }


def _publish_context(request: Request, item: ContentItem, *, candidate: PolishResult | None = None, error: str | None = None) -> dict:
    source = PublishingSource(
        source_id=item.id,
        kind=item.kind,
        title=candidate.title if candidate else item.title,
        summary=item.summary,
        markdown=candidate.markdown if candidate else item.body,
    )
    return {
        "active_page": "publish",
        "item": item,
        "source": source,
        "rendered": WECHAT_RENDERER.render(source),
        "original_html": render_markdown(item.body),
        "candidate": candidate,
        "error": error,
        "llm_enabled": request.app.state.llm_client.enabled,
    }


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


@router.get("/publish", response_class=HTMLResponse, name="publish_index")
async def publish_index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="publish_index.html",
        context={
            "active_page": "publish",
            "items": _collection(request).items,
            "llm_enabled": request.app.state.llm_client.enabled,
        },
    )

@router.get(
    "/publish/{item_id}",
    response_class=HTMLResponse,
    name="publish_item",
)
async def publish_item(request: Request, item_id: str) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if (
        item is None
        or resolve_publishing_source(
            request.app.state.content_root,
            item_id,
        )
        is None
    ):
        return _not_found(request, "publish")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="publish.html",
        context=_publish_context(request, item),
    )

@router.post(
    "/publish/{item_id}/polish",
    response_class=HTMLResponse,
    name="polish_item",
)
async def polish_item(
    request: Request,
    item_id: str,
    mode: str = Form(default="auto"),
    outbound_text: str = Form(default=""),
) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if item is None:
        return _not_found(request, "publish")
    client = request.app.state.llm_client
    if not client.enabled:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context=_publish_context(
                request,
                item,
                error="尚未配置兼容模型，忠实排版仍可正常使用。",
            ),
            status_code=422,
        )
    if not outbound_text:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="llm_disclosure.html",
            context=_disclosure_context(
                request,
                purpose="生成公众号幻想栈风格候选稿",
                task_type=ModelTaskKind.PUBLISH.value,
                source_labels=(item.title,),
                submit_url=request.url_for("polish_item", item_id=item.id),
                outbound_text=json.dumps(
                    {"title": item.title, "body": item.body},
                    ensure_ascii=False,
                    indent=2,
                ),
                back_url=request.url_for("publish_item", item_id=item.id),
                hidden_fields={"mode": mode},
            ),
        )
    try:
        reviewed = json.loads(outbound_text)
        reviewed_title = str(reviewed["title"]).strip()
        reviewed_body = str(reviewed["body"]).strip()
        if not reviewed_title or not reviewed_body:
            raise ValueError("标题和正文不能为空")
        candidate = await asyncio.to_thread(
            client.polish,
            title=reviewed_title[:120],
            body=reviewed_body,
            mode=mode,
        )
    except (
        KeyError,
        TypeError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
        httpx.HTTPError,
    ) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context=_publish_context(request, item, error=f"润色失败：{error}"),
            status_code=502,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="publish.html",
        context=_publish_context(request, item, candidate=candidate),
    )

@router.post(
    "/publish/{item_id}/manual", name="manual_publish_task"
)
async def manual_publish_task(
    request: Request,
    item_id: str,
    mode: str = Form(default="auto"),
) -> HTMLResponse:
    item = _collection(request).get(item_id)
    if item is None or mode not in {"auto", "essay", "explainer"}:
        return _not_found(request, "publish")
    payload = json.dumps(
        {"title": item.title, "body": item.body, "mode": mode},
        ensure_ascii=False,
        indent=2,
    )
    try:
        task = request.app.state.model_tasks.create(
            task_type=ModelTaskKind.PUBLISH.value,
            purpose="生成幻想栈风格公众号候选稿，不覆盖原文",
            source_labels=(item.title,),
            payload=payload,
            return_url=str(request.url_for("publish_item", item_id=item.id)),
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context=_publish_context(request, item, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("model_task", task_id=task.id), status_code=303
    )

@router.post("/publish/{item_id}/save", name="save_polished_article")
async def save_polished_article(
    request: Request,
    item_id: str,
    title: str = Form(...),
    markdown: str = Form(...),
) -> HTMLResponse:
    source = _collection(request).get(item_id)
    if source is None:
        return _not_found(request, "publish")
    try:
        created = create_item(
            request.app.state.content_root,
            title=title,
            body=markdown,
            tags=source.tags,
            category=source.category or "",
            kind="article",
            parent_id=source.id,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="publish.html",
            context=_publish_context(request, source, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("workspace").include_query_params(
            saved="article",
            view="articles",
            created=created.id,
        ),
        status_code=303,
    )

@router.get("/video", response_class=HTMLResponse, name="video_studio")
async def video_studio(
    request: Request,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="video.html",
        context=_video_context(request, saved=saved),
    )

@router.post("/video/projects", name="create_video_project")
async def create_video_project(
    request: Request,
    source_id: str = Form(...),
    notes: str = Form(default=""),
    platform: str = Form(default="general"),
    aspect_ratio: str = Form(default="16:9"),
    target_duration: int = Form(default=90),
    video_type: str = Form(default="knowledge-explainer"),
    audience: str = Form(default="对主题感兴趣的普通读者"),
    tone: str = Form(default="清晰、克制、保留个人观察"),
) -> HTMLResponse:
    source = _collection(request).get(source_id)
    if source is None:
        return _not_found(request, "video")
    try:
        request.app.state.video.create(
            source,
            notes=notes,
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=audience,
            tone=tone,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="video.html",
            context=_video_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("video_studio").include_query_params(saved="created"),
        status_code=303,
    )

@router.post(
    "/video/projects/{project_id}/plan",
    name="update_video_project_plan",
)
async def update_video_project_plan(
    request: Request,
    project_id: str,
    platform: str = Form(...),
    aspect_ratio: str = Form(...),
    target_duration: int = Form(...),
    video_type: str = Form(...),
    audience: str = Form(...),
    tone: str = Form(...),
    notes: str = Form(default=""),
    scene_duration: list[int] = Form(...),
    scene_narration: list[str] = Form(...),
    scene_visual: list[str] = Form(...),
    scene_caption: list[str] = Form(...),
    scene_assets: list[str] = Form(default=[]),
) -> HTMLResponse:
    lengths = {
        len(scene_duration),
        len(scene_narration),
        len(scene_visual),
        len(scene_caption),
    }
    if len(lengths) != 1 or not scene_duration:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="video.html",
            context=_video_context(request, error="分镜表单结构无效，请刷新页面后重试"),
            status_code=422,
        )
    padded_assets = scene_assets + [""] * (len(scene_duration) - len(scene_assets))
    scenes = tuple(
        VideoScene(
            id=f"scene-{index + 1:02d}",
            duration_seconds=duration,
            narration=scene_narration[index],
            visual=scene_visual[index],
            caption=scene_caption[index],
            assets=tuple(
                value.strip()
                for value in padded_assets[index].replace("，", ",").split(",")
                if value.strip()
            ),
        )
        for index, duration in enumerate(scene_duration)
    )
    try:
        request.app.state.video.update_plan(
            project_id,
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=audience,
            tone=tone,
            notes=notes,
            scenes=scenes,
        )
    except KeyError:
        return _not_found(request, "video")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="video.html",
            context=_video_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("video_studio").include_query_params(saved="plan"),
        status_code=303,
    )

@router.post(
    "/video/projects/{project_id}/status",
    name="update_video_project_status",
)
async def update_video_project_status(
    request: Request,
    project_id: str,
    status: str = Form(...),
) -> HTMLResponse:
    try:
        request.app.state.video.update_status(project_id, status)
    except KeyError:
        return _not_found(request, "video")
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="video.html",
            context=_video_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("video_studio").include_query_params(saved="status"),
        status_code=303,
    )

@router.get(
    "/video/projects/{project_id}/files/{file_path:path}",
    name="video_project_file",
)
async def video_project_file(
    request: Request,
    project_id: str,
    file_path: str,
) -> FileResponse:
    path = request.app.state.video.resolve_file(project_id, file_path)
    if path is None:
        return _not_found(request, "video")  # type: ignore[return-value]
    return FileResponse(path, filename=path.name)
