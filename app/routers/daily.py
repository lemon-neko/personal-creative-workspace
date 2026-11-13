"""Desktop daily work and its read-only mobile snapshot."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.mobile_daily import DailySnapshot, daily_now, save_daily_snapshot
from app.plugin_runtime import daily_available
from app.plugins import DAILY_ORIGIN, WORKBENCH_ORIGIN
from app.web import TEMPLATES


router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="workspace")
async def workspace_home(request: Request):
    from app.routers.workspace_content import workspace

    if not request.app.state.plugins_enabled or request.query_params:
        return await workspace(
            request, request.query_params.get("saved"), request.query_params.get("q"),
            request.query_params.get("view", "pending"),
        )
    if request.app.state.enforce_security and request.url.netloc != "127.0.0.1:8765":
        return RedirectResponse(WORKBENCH_ORIGIN, status_code=303)
    ready = request.app.state.daily_verified and await daily_available()
    return TEMPLATES.TemplateResponse(
        request=request, name="workbench_daily.html",
        context={
            "active_page": "workspace", "daily_origin": DAILY_ORIGIN, "ready": ready,
            "mobile_enabled": request.app.state.mobile_store.config().enabled,
        },
    )


@router.post("/workflow/daily-snapshot")
def publish_daily_snapshot(request: Request, snapshot: DailySnapshot):
    if request.app.state.enforce_security and request.headers.get("origin") != WORKBENCH_ORIGIN:
        raise HTTPException(403, "日常快照只接受桌面工作台")
    if not request.app.state.plugins_enabled or not request.app.state.mobile_store.config().enabled:
        raise HTTPException(404, "未启用手机同步")
    now = daily_now()
    if snapshot.day != now.date():
        raise HTTPException(409, "只能同步今天的日常工作")
    save_daily_snapshot(request.app.state.data_root, snapshot, now)
    return {"synced": True}
