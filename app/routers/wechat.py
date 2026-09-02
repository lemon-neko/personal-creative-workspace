"""Local settings and explicit WeChat draft delivery routes."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.content import ContentItem, semantic_revision
from app.publishing import PublishingSource, WECHAT_RENDERER
from app.publishing_theme import WechatThemeConfig
from app.web import TEMPLATES, collection, not_found
from app.wechat import (
    MAX_COVER_BYTES,
    WechatAPIError,
    WechatCredentials,
    WechatDraftPush,
    WechatPushIntent,
    save_cover_asset,
)


router = APIRouter()


def _article(request: Request, item_id: str) -> ContentItem | None:
    item = collection(request).get(item_id)
    if item is None or item.kind != "article" or item.status == "archived":
        return None
    return item


def _settings_context(
    request: Request,
    *,
    notice: str = "",
    error: str = "",
) -> dict:
    return {
        "active_page": "settings",
        "wechat_status": request.app.state.wechat.credential_status(),
        "wechat_report": request.app.state.wechat.last_connection_report,
        "notice": notice,
        "error": error,
    }


def _intent_context(
    request: Request,
    intent: WechatPushIntent,
    *,
    existing: WechatDraftPush | None = None,
    result: WechatDraftPush | None = None,
    error: str = "",
) -> dict:
    return {
        "active_page": "publish",
        "intent": intent,
        "existing": existing,
        "result": result,
        "error": error,
        "push_error": (
            str(WechatAPIError(result.error_stage, result.error_code))
            if result is not None and result.status == "failed"
            else ""
        ),
        "wechat_status": request.app.state.wechat.credential_status(),
    }


@router.get(
    "/settings/wechat",
    response_class=HTMLResponse,
    name="wechat_settings",
)
async def wechat_settings(request: Request) -> HTMLResponse:
    saved = request.query_params.get("saved", "")
    notices = {
        "credentials": "公众号凭证已写入 macOS 钥匙串。",
        "deleted": "公众号凭证已从 macOS 钥匙串删除。",
        "connected": "连接测试成功，凭证和 IP 白名单可用。",
    }
    return TEMPLATES.TemplateResponse(
        request=request,
        name="wechat_settings.html",
        context=_settings_context(request, notice=notices.get(saved, "")),
    )


@router.post(
    "/settings/wechat/credentials",
    name="save_wechat_credentials",
)
async def save_wechat_credentials(
    request: Request,
    app_id: str = Form(...),
    app_secret: str = Form(...),
) -> HTMLResponse:
    try:
        request.app.state.wechat.credentials.save(
            WechatCredentials(app_id.strip(), app_secret.strip())
        )
    except (RuntimeError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_settings.html",
            context=_settings_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("wechat_settings").include_query_params(saved="credentials"),
        status_code=303,
    )


@router.post(
    "/settings/wechat/credentials/delete",
    name="delete_wechat_credentials",
)
async def delete_wechat_credentials(request: Request) -> HTMLResponse:
    try:
        request.app.state.wechat.credentials.delete()
    except RuntimeError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_settings.html",
            context=_settings_context(request, error=str(error)),
            status_code=422,
        )
    return RedirectResponse(
        request.url_for("wechat_settings").include_query_params(saved="deleted"),
        status_code=303,
    )


@router.post("/settings/wechat/test", name="test_wechat_connection")
async def test_wechat_connection(request: Request) -> HTMLResponse:
    try:
        await request.app.state.wechat.test_connection()
    except httpx.HTTPError:
        message = "网络连接失败，请检查本机网络后重试"
    except (RuntimeError, WechatAPIError) as error:
        message = str(error)
    else:
        return RedirectResponse(
            request.url_for("wechat_settings").include_query_params(saved="connected"),
            status_code=303,
        )
    if message:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_settings.html",
            context=_settings_context(
                request,
                error=f"连接测试失败：{message}",
            ),
            status_code=502,
        )


@router.post(
    "/publish/{item_id}/wechat/preflight",
    response_class=HTMLResponse,
    name="wechat_push_preflight",
)
async def wechat_push_preflight(
    request: Request,
    item_id: str,
    article_revision: str = Form(...),
    title: str = Form(...),
    author: str = Form(default="羽白"),
    digest: str = Form(default=""),
    source_url: str = Form(default=""),
    final_html: str = Form(...),
    cover_asset: str = Form(default=""),
    cover_upload: UploadFile | None = File(default=None),
    formula_count: int = Form(default=0),
    image_fallback_count: int = Form(default=0),
    formula_fallback_count: int = Form(default=0),
    primary_color: str = Form(default="#1199aa"),
    font_size: str = Form(default="16"),
    font_family: str = Form(default="system"),
    indent: str = Form(default="0"),
    justify: str = Form(default="1"),
) -> HTMLResponse:
    item = _article(request, item_id)
    if item is None:
        return not_found(request, "publish")
    if article_revision != semantic_revision(item):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_error.html",
            context={
                "active_page": "publish",
                "item": item,
                "error": "文章已被修改，请刷新发布页后重新准备。",
            },
            status_code=409,
        )
    if image_fallback_count or formula_fallback_count:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_error.html",
            context={
                "active_page": "publish",
                "item": item,
                "error": "仍有外部图片或公式转换失败，不能直接推送；富文本复制仍可使用。",
            },
            status_code=422,
        )
    if cover_upload is not None and cover_upload.filename:
        data = await cover_upload.read(MAX_COVER_BYTES + 1)
        try:
            cover_asset = save_cover_asset(
                request.app.state.content_root,
                cover_upload.filename,
                data,
            )
        except ValueError as error:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="wechat_push_error.html",
                context={
                    "active_page": "publish",
                    "item": item,
                    "error": str(error),
                },
                status_code=422,
            )
    if not cover_asset:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_error.html",
            context={
                "active_page": "publish",
                "item": item,
                "error": "请选择现有封面或上传一张 PNG/JPEG 封面。",
            },
            status_code=422,
        )
    theme = WechatThemeConfig.from_mapping(
        {
            "primary_color": primary_color,
            "font_size": font_size,
            "font_family": font_family,
            "indent": indent,
            "justify": justify,
        }
    )
    expected = WECHAT_RENDERER.render(
        PublishingSource(item.id, item.kind, item.title, item.summary, item.body),
        theme,
    ).export_html
    try:
        intent, existing = request.app.state.wechat.prepare_intent(
            article_id=item.id,
            article_revision=article_revision,
            title=title,
            author=author,
            digest=digest,
            source_url=source_url,
            final_html=final_html,
            expected_html=expected,
            cover_asset=cover_asset,
            formula_count=formula_count,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_error.html",
            context={
                "active_page": "publish",
                "item": item,
                "error": str(error),
            },
            status_code=422,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="wechat_push_confirm.html",
        context=_intent_context(request, intent, existing=existing),
    )


async def _push_intent(
    request: Request,
    item_id: str,
    intent_id: str,
    *,
    allow_duplicate: bool,
) -> HTMLResponse:
    item = _article(request, item_id)
    if item is None:
        return not_found(request, "publish")
    try:
        intent = request.app.state.wechat.intents.load(intent_id)
    except (KeyError, ValueError) as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_error.html",
            context={"active_page": "publish", "item": item, "error": str(error)},
            status_code=422,
        )
    if intent.article_id != item.id:
        return not_found(request, "publish")
    try:
        result = await request.app.state.wechat.push(
            intent,
            current_revision=semantic_revision(item),
            allow_duplicate=allow_duplicate,
        )
    except ValueError as error:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_confirm.html",
            context=_intent_context(request, intent, error=str(error)),
            status_code=409,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="wechat_push_confirm.html",
        context=_intent_context(request, intent, result=result),
        status_code=200 if result.status == "succeeded" else 502,
    )


@router.post(
    "/publish/{item_id}/wechat/confirm",
    response_class=HTMLResponse,
    name="wechat_push_confirm",
)
async def wechat_push_confirm(
    request: Request,
    item_id: str,
    intent_id: str = Form(...),
) -> HTMLResponse:
    return await _push_intent(
        request, item_id, intent_id, allow_duplicate=False
    )


@router.post(
    "/publish/{item_id}/wechat/duplicate",
    response_class=HTMLResponse,
    name="wechat_push_duplicate",
)
async def wechat_push_duplicate(
    request: Request,
    item_id: str,
    intent_id: str = Form(...),
    confirmation: str = Form(...),
) -> HTMLResponse:
    if confirmation.strip() != "创建新草稿副本":
        try:
            intent = request.app.state.wechat.intents.load(intent_id)
        except (KeyError, ValueError):
            return not_found(request, "publish")
        return TEMPLATES.TemplateResponse(
            request=request,
            name="wechat_push_confirm.html",
            context=_intent_context(
                request,
                intent,
                existing=request.app.state.wechat.pushes.blocking(
                    intent.dedupe_key
                ),
                error="请输入“创建新草稿副本”确认重复推送。",
            ),
            status_code=422,
        )
    return await _push_intent(request, item_id, intent_id, allow_duplicate=True)
