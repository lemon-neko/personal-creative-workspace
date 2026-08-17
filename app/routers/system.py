"""System, library, search, Obsidian, mobile and backup routes."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from app.backup import create_encrypted_backup, inspect_encrypted_backup, restore_encrypted_backup
from app.career import CareerRepository
from app.content import load_items, render_markdown
from app.knowledge import eligible_items
from app.knowledge_store import KnowledgeCard, load_knowledge_store
from app.library import MATERIAL_STATUSES, MATERIAL_TYPES, create_material, load_materials, update_material_status
from app.obsidian import ObsidianBridge, obsidian_uri
from app.runtime import inspect_data_permissions, inspect_tailnet, service_statuses
from app.search import SearchRepository
from app.vault import apply_vault_migration, plan_vault_migration
from app.web import TEMPLATES, collection, not_found
from app.workspace import SHANGHAI, create_item, items_directory, permanently_delete, restore_from_trash, trash_directory


router = APIRouter()


def _collection(request: Request):
    return collection(request)


def _not_found(request: Request, active_page: str = "") -> HTMLResponse:
    return not_found(request, active_page)


def _comma_values(value: str) -> list[str]:
    return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]


def _obsidian_context(request: Request, *, state=None, notice: str = "", error: str = "") -> dict:
    bridge: ObsidianBridge = request.app.state.obsidian
    store = load_knowledge_store(request.app.state.content_root)
    authored = _collection(request)
    return {
        "active_page": "settings",
        "state": state or bridge.state(),
        "inbox": bridge.inbox(),
        "knowledge_inbox": bridge.knowledge_inbox(),
        "knowledge_maps": store.maps,
        "knowledge_sources": eligible_items(authored),
        "migration": bridge.migration_preview(),
        "vault_url": obsidian_uri(request.app.state.content_root),
        "knowledge_home_url": obsidian_uri(request.app.state.content_root / "知识首页.md"),
        "notice": notice,
        "error": error,
    }


def _search_sources(application) -> dict:
    return {
        "items": load_items(items_directory(application.state.content_root)).items,
        "knowledge": load_knowledge_store(application.state.content_root),
        "materials": load_materials(application.state.content_root),
        "career": application.state.career,
        "video": application.state.video,
    }


@router.get("/library", response_class=HTMLResponse, name="library")
async def library(
    request: Request,
    material: Optional[str] = Query(default=None),
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    materials = load_materials(request.app.state.content_root)
    selected = next((item for item in materials if item.id == material), None)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="library.html",
        context={
            "active_page": "library",
            "materials": materials,
            "selected_material": selected,
            "selected_material_html": (
                render_markdown(selected.body) if selected else ""
            ),
            "material_types": MATERIAL_TYPES,
            "material_statuses": MATERIAL_STATUSES,
            "documents": request.app.state.career.documents(),
            "notice": "材料已保存；链接没有被自动访问。" if saved else None,
        },
    )
@router.post("/library", name="create_library_material")
async def create_library_material(
    request: Request,
    title: str = Form(...),
    body: str = Form(default=""),
    source_type: str = Form(default="note"),
    source_url: str = Form(default=""),
    document_id: str = Form(default=""),
    status: str = Form(default="inbox"),
) -> HTMLResponse:
    if document_id and request.app.state.career.document(document_id) is None:
        return _not_found(request, "library")
    try:
        material = create_material(
            request.app.state.content_root,
            title=title,
            body=body,
            source_type=source_type,
            source_url=source_url,
            document_id=document_id,
            status=status,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="library.html",
            context={
                "active_page": "library",
                "materials": load_materials(request.app.state.content_root),
                "selected_material": None,
                "selected_material_html": "",
                "material_types": MATERIAL_TYPES,
                "material_statuses": MATERIAL_STATUSES,
                "documents": request.app.state.career.documents(),
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("library").include_query_params(material=material.id, saved="created"),
        status_code=303,
    )

@router.post(
    "/library/{material_id}/status", name="change_material_status"
)
async def change_material_status(
    request: Request,
    material_id: str,
    status: str = Form(...),
) -> HTMLResponse:
    try:
        update_material_status(
            request.app.state.content_root,
            material_id,
            status,
        )
    except (KeyError, ValueError):
        return _not_found(request, "library")
    return RedirectResponse(
        request.url_for("library").include_query_params(
            material=material_id,
            saved="status",
        ),
        status_code=303,
    )

@router.post(
    "/library/{material_id}/thought", name="create_material_thought"
)
async def create_material_thought(
    request: Request,
    material_id: str,
    body: str = Form(...),
    title: str = Form(default=""),
) -> HTMLResponse:
    material = next(
        (
            item
            for item in load_materials(request.app.state.content_root)
            if item.id == material_id
        ),
        None,
    )
    if material is None:
        return _not_found(request, "library")
    source_line = (
        f"\n\n> 材料来源：{material.title}"
        + (f"\n> {material.source_url}" if material.source_url else "")
    )
    try:
        create_item(
            request.app.state.content_root,
            title=title,
            body=f"{body.strip()}{source_line}",
            tags=("阅读笔记",),
            category="材料摘录",
        )
        update_material_status(
            request.app.state.content_root,
            material.id,
            "reading",
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="library.html",
            context={
                "active_page": "library",
                "materials": load_materials(request.app.state.content_root),
                "selected_material": material,
                "selected_material_html": render_markdown(material.body),
                "material_types": MATERIAL_TYPES,
                "material_statuses": MATERIAL_STATUSES,
                "documents": request.app.state.career.documents(),
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("workspace").include_query_params(
            view="pending", saved="created"
        ),
        status_code=303,
    )

@router.get("/search", response_class=HTMLResponse, name="search")
async def search(request: Request, q: str = Query(default="")) -> HTMLResponse:
    repository: SearchRepository = request.app.state.search
    return TEMPLATES.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "active_page": "search",
            "query": q,
            "results": repository.search(q) if q.strip() else (),
        },
    )

@router.get(
    "/settings/search",
    response_class=HTMLResponse,
    name="search_settings",
)
async def search_settings(
    request: Request,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="search_settings.html",
        context={
            "active_page": "settings",
            "search_status": request.app.state.search.status(),
            "search_error": request.app.state.search_sync_error,
            "notice": "检索索引已完整重建。" if saved == "rebuilt" else "",
        },
    )

@router.post(
    "/settings/search/rebuild",
    name="rebuild_search_index",
)
async def rebuild_search_index(request: Request) -> HTMLResponse:
    request.app.state.search.rebuild(**_search_sources(request.app))
    request.app.state.search_sync_error = ""
    return RedirectResponse(
        request.url_for("search_settings").include_query_params(saved="rebuilt"),
        status_code=303,
    )

@router.get(
    "/settings/vault-migration",
    response_class=HTMLResponse,
    name="vault_migration",
)
async def vault_migration(request: Request) -> HTMLResponse:
    entries = plan_vault_migration(request.app.state.content_root)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="vault_migration.html",
        context={"active_page": "settings", "entries": entries},
    )

@router.post("/settings/vault-migration", name="apply_vault_migration")
async def apply_vault_migration_route(
    request: Request,
    confirmation: str = Form(...),
) -> HTMLResponse:
    if confirmation.strip() != "迁移内容":
        return TEMPLATES.TemplateResponse(
            request=request,
            name="vault_migration.html",
            context={
                "active_page": "settings",
                "entries": plan_vault_migration(request.app.state.content_root),
                "error": "请输入“迁移内容”确认。",
            },
            status_code=422,
        )
    entries = plan_vault_migration(request.app.state.content_root)
    try:
        rollback = apply_vault_migration(request.app.state.content_root, entries)
    except (OSError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="vault_migration.html",
            context={"active_page": "settings", "entries": entries, "error": str(error)},
            status_code=422,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="vault_migration.html",
        context={
            "active_page": "settings",
            "entries": (),
            "notice": f"迁移完成；回滚目录：{rollback.name if rollback else '无需迁移'}",
        },
    )

@router.get("/trash", response_class=HTMLResponse, name="trash")
async def trash(
    request: Request,
    saved: Optional[str] = Query(default=None),
) -> HTMLResponse:
    collection = load_items(trash_directory(request.app.state.content_root))
    notices = {
        "restored": "内容已恢复到想法库。",
        "deleted": "内容已永久删除；只能从此前的加密备份恢复。",
    }
    return TEMPLATES.TemplateResponse(
        request=request,
        name="trash.html",
        context={
            "active_page": "trash",
            "items": collection.items,
            "diagnostics": collection.diagnostics,
            "notice": notices.get(saved or ""),
        },
    )

@router.post("/trash/{item_id}/restore", name="restore_item")
async def restore_item(request: Request, item_id: str) -> HTMLResponse:
    try:
        restore_from_trash(request.app.state.content_root, item_id)
    except KeyError:
        return _not_found(request, "settings")
    return RedirectResponse(
        request.url_for("trash").include_query_params(saved="restored"),
        status_code=303,
    )

@router.post("/trash/{item_id}/delete", name="delete_item")
async def delete_item(
    request: Request,
    item_id: str,
    confirmation: str = Form(default=""),
) -> HTMLResponse:
    try:
        permanently_delete(
            request.app.state.content_root,
            item_id,
            confirmation,
        )
    except KeyError:
        return _not_found(request, "settings")
    except ValueError as error:
        collection = load_items(trash_directory(request.app.state.content_root))
        return TEMPLATES.TemplateResponse(
            request=request,
            name="trash.html",
            context={
                "active_page": "trash",
                "items": collection.items,
                "diagnostics": collection.diagnostics,
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("trash").include_query_params(saved="deleted"),
        status_code=303,
    )

@router.get("/settings", response_class=HTMLResponse, name="settings")
async def settings(request: Request) -> HTMLResponse:
    client = request.app.state.llm_client
    config = getattr(client, "config", None)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_page": "settings",
            "data_root": request.app.state.data_root,
            "content_root": request.app.state.content_root,
            "llm_enabled": client.enabled,
            "llm_model": getattr(config, "model", "") if config else "",
            "llm_base_url": getattr(config, "base_url", "") if config else "",
            "llm_is_local": urlparse(
                getattr(config, "base_url", "") if config else "",
            ).hostname
            in {"localhost", "127.0.0.1", "::1"},
        },
    )

@router.get(
    "/settings/runtime",
    response_class=HTMLResponse,
    name="runtime_settings",
)
async def runtime_settings(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="runtime_settings.html",
        context={
            "active_page": "settings",
            "services": service_statuses(data_root=request.app.state.data_root),
            "tailnet": inspect_tailnet(),
            "permissions": inspect_data_permissions(request.app.state.data_root),
            "mobile_config": request.app.state.mobile_store.config(),
        },
    )

@router.get(
    "/settings/obsidian",
    response_class=HTMLResponse,
    name="obsidian_settings",
)
async def obsidian_settings(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="obsidian_settings.html",
        context=_obsidian_context(request),
    )

@router.post(
    "/settings/obsidian/templates",
    name="initialize_obsidian_templates",
)
async def initialize_obsidian_templates(request: Request) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        changed = bridge.initialize_templates()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(
                request,
                notice=f"知识模板已就位，更新 {changed} 个模板文件。",
            ),
        )
    except OSError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )

@router.post("/settings/obsidian/scan", name="scan_obsidian")
async def scan_obsidian(request: Request) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        state = bridge.scan()
        notice = (
            f"扫描完成，协调了 {state.external_changes} 个外部修改。"
            if state.external_changes
            else "扫描完成，未发现需要协调的外部修改。"
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, state=state, notice=notice),
        )
    except (OSError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )

@router.post(
    "/settings/obsidian/rebuild-links",
    name="rebuild_obsidian_links",
)
async def rebuild_obsidian_links(request: Request) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        changed = bridge.rebuild_links()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(
                request,
                notice=f"已重建原生关系链接，更新 {changed} 个文件。",
            ),
        )
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )

@router.post(
    "/settings/obsidian/knowledge-inbox/{draft_id}/import",
    name="import_obsidian_knowledge_inbox",
)
async def import_obsidian_knowledge_inbox(
    request: Request,
    draft_id: str,
    expected_revision: str = Form(...),
    title: str = Form(default=""),
    summary: str = Form(default=""),
    subjects: str = Form(default=""),
    concepts: str = Form(default=""),
    source_ids: list[str] = Form(default=[]),
    map_ids: list[str] = Form(default=[]),
    parent_ids: list[str] = Form(default=[]),
) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        value = bridge.import_knowledge_inbox(
            draft_id,
            expected_revision=expected_revision,
            title=title,
            summary=summary,
            subjects=tuple(_comma_values(subjects)),
            concepts=tuple(_comma_values(concepts)),
            source_ids=tuple(source_ids),
            map_ids=tuple(map_ids),
            parent_ids=tuple(parent_ids),
        )
        bridge.rebuild_links()
        bridge.scan()
    except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )
    endpoint = "knowledge_card" if isinstance(value, KnowledgeCard) else "knowledge_map"
    parameter = {"card_id": value.id} if isinstance(value, KnowledgeCard) else {"map_id": value.id}
    return RedirectResponse(request.url_for(endpoint, **parameter), status_code=303)

@router.post(
    "/settings/obsidian/migration/apply",
    name="apply_obsidian_migration",
)
async def apply_obsidian_migration(
    request: Request,
    confirmation: str = Form(...),
) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        snapshot = bridge.apply_migration(confirmation)
        bridge.rebuild_links()
        state = bridge.scan()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(
                request,
                state=state,
                notice=f"知识结构已整理；回滚快照保存在 {snapshot.name}。",
            ),
        )
    except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )

@router.post(
    "/settings/obsidian/migration/rollback",
    name="rollback_obsidian_migration",
)
async def rollback_obsidian_migration(
    request: Request,
    confirmation: str = Form(...),
) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        snapshot = bridge.rollback_latest_migration(confirmation)
        state = bridge.scan()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(
                request,
                state=state,
                notice=f"已恢复到 {snapshot.name} 整理前的版本。",
            ),
        )
    except (OSError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )

@router.post(
    "/settings/obsidian/permissions",
    name="repair_obsidian_permissions",
)
async def repair_obsidian_permissions(request: Request) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        changed = bridge.repair_permissions()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(
                request,
                notice=f"权限检查完成，修复 {changed} 个路径。",
            ),
        )
    except OSError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )

@router.post(
    "/settings/obsidian/inbox/{draft_id}/import",
    name="import_obsidian_inbox",
)
async def import_obsidian_inbox(
    request: Request,
    draft_id: str,
    expected_revision: str = Form(...),
    title: str = Form(default=""),
    tags: str = Form(default=""),
    category: str = Form(default=""),
) -> HTMLResponse:
    bridge: ObsidianBridge = request.app.state.obsidian
    try:
        item = bridge.import_inbox(
            draft_id,
            expected_revision=expected_revision,
            title=title,
            tags=tags,
            category=category,
        )
        bridge.rebuild_links()
        bridge.scan()
    except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="obsidian_settings.html",
            context=_obsidian_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("idea_detail", item_id=item.id).include_query_params(
            saved="imported",
        ),
        status_code=303,
    )

@router.get(
    "/settings/mobile",
    response_class=HTMLResponse,
    name="mobile_settings",
)
async def mobile_settings(request: Request) -> HTMLResponse:
    store = request.app.state.mobile_store
    return TEMPLATES.TemplateResponse(
        request=request,
        name="mobile_settings.html",
        context={
            "active_page": "settings",
            "config": store.config(),
            "devices": store.devices(),
        },
    )

@router.post("/settings/mobile/config", name="save_mobile_config")
async def save_mobile_config(
    request: Request,
    enabled: Optional[str] = Form(default=None),
    tailnet_host: str = Form(default=""),
) -> HTMLResponse:
    store = request.app.state.mobile_store
    try:
        store.save_config(enabled=enabled == "on", tailnet_host=tailnet_host)
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="mobile_settings.html",
            context={
                "active_page": "settings",
                "config": store.config(),
                "devices": store.devices(),
                "error": str(error),
            },
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("mobile_settings").include_query_params(saved="config"),
        status_code=303,
    )

@router.post(
    "/settings/mobile/pairing-code",
    name="create_mobile_pairing_code",
)
async def create_mobile_pairing_code(request: Request) -> HTMLResponse:
    store = request.app.state.mobile_store
    if not store.config().enabled:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="mobile_settings.html",
            context={
                "active_page": "settings",
                "config": store.config(),
                "devices": store.devices(),
                "error": "请先填写 Tailscale 主机并启用手机同步",
            },
            status_code=422,
        )
    code, expires_at = store.create_pairing_code()
    return TEMPLATES.TemplateResponse(
        request=request,
        name="mobile_settings.html",
        context={
            "active_page": "settings",
            "config": store.config(),
            "devices": store.devices(),
            "pairing_code": code,
            "pairing_expires_at": expires_at,
        },
    )

@router.post(
    "/settings/mobile/devices/{device_id}/revoke",
    name="revoke_mobile_device",
)
async def revoke_mobile_device(request: Request, device_id: str) -> HTMLResponse:
    try:
        request.app.state.mobile_store.revoke_device(device_id)
    except KeyError:
        return _not_found(request, "settings")
    return RedirectResponse(
        request.url_for("mobile_settings").include_query_params(saved="revoked"),
        status_code=303,
    )

@router.get(
    "/settings/backups",
    response_class=HTMLResponse,
    name="backups",
)
async def backups(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="backups.html",
        context={
            "active_page": "settings",
            "data_root": request.app.state.data_root,
        },
    )

@router.post("/settings/backups/export", name="export_backup")
async def export_backup(
    request: Request, password: str = Form(...)
) -> FileResponse:
    working = request.app.state.data_root / "working"
    descriptor, path_text = tempfile.mkstemp(
        prefix="yubai-backup-", suffix=".zip", dir=working
    )
    os.close(descriptor)
    path = Path(path_text)
    try:
        create_encrypted_backup(request.app.state.data_root, password, path)
    except ValueError as error:
        path.unlink(missing_ok=True)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "error": str(error),
            },
            status_code=422,
        )  # type: ignore[return-value]
    filename = f"yubai-workspace-{datetime.now(SHANGHAI):%Y%m%d-%H%M%S}.zip"
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )

@router.post(
    "/settings/backups/inspect",
    response_class=HTMLResponse,
    name="inspect_backup",
)
async def inspect_backup(
    request: Request,
    password: str = Form(...),
    upload: UploadFile = File(...),
) -> HTMLResponse:
    content = await upload.read(200 * 1024 * 1024 + 1)
    if len(content) > 200 * 1024 * 1024:
        error = "备份文件不能超过 200 MB"
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "error": error,
            },
            status_code=422,
        )
    token = f"restore-{os.urandom(12).hex()}.zip"
    path = request.app.state.data_root / "working" / token
    path.write_bytes(content)
    path.chmod(0o600)
    try:
        preview = inspect_encrypted_backup(path, password)
    except ValueError as error:
        path.unlink(missing_ok=True)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "error": str(error),
            },
            status_code=422,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="backups.html",
        context={
            "active_page": "settings",
            "data_root": request.app.state.data_root,
            "preview": preview,
            "restore_token": token,
        },
    )

@router.post("/settings/backups/restore", name="restore_backup")
async def restore_backup(
    request: Request,
    restore_token: str = Form(...),
    password: str = Form(...),
    confirmation: str = Form(...),
) -> HTMLResponse:
    if (
        confirmation.strip() != "恢复备份"
        or not restore_token.startswith("restore-")
        or not restore_token.endswith(".zip")
        or Path(restore_token).name != restore_token
    ):
        return _not_found(request, "settings")
    path = request.app.state.data_root / "working" / restore_token
    if not path.is_file():
        return _not_found(request, "settings")
    try:
        rollback = restore_encrypted_backup(
            path, password, request.app.state.data_root
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="backups.html",
            context={
                "active_page": "settings",
                "data_root": request.app.state.data_root,
                "error": str(error),
            },
            status_code=422,
        )
    finally:
        path.unlink(missing_ok=True)
    request.app.state.career = CareerRepository(request.app.state.data_root)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="backups.html",
        context={
            "active_page": "settings",
            "data_root": request.app.state.data_root,
            "notice": f"恢复完成；回滚副本保存在 {rollback.name}。",
        },
    )
