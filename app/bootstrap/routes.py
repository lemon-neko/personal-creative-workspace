"""Compose desktop routes from the static plugin catalog in registration order."""

from fastapi import FastAPI

from app.plugins import PLUGINS, validate_registry
from app.routers import (
    agent_core, assistant, career_learning, creation, daily, focus, income,
    knowledge_models, resumes, system, wechat, workflow, workspace_content,
)


ROUTE_GROUPS = {
    "daily": (daily.router,),
    "workflow": (workflow.router,),
    "planning": (workspace_content.router, focus.router),
    "legacy-agent": (agent_core.router,),
    "knowledge": (knowledge_models.router,),
    "publishing": (creation.router, wechat.router),
    "career": (resumes.router, career_learning.router),
    "assistant": (assistant.router,),
    "income": (income.router,),
    "workspace-tools": (system.router,),
}


def register_plugins(app: FastAPI) -> None:
    validate_registry(PLUGINS)
    if set(ROUTE_GROUPS) != {plugin.id for plugin in PLUGINS}:
        raise ValueError("插件清单与路由装配不符")
    entries = {
        route.name
        for group in ROUTE_GROUPS.values() for router in group for route in router.routes
        if "GET" in (getattr(route, "methods", None) or ()) and "{" not in route.path
    }
    for plugin in PLUGINS:
        for name, _ in plugin.links:
            if name not in entries:
                raise ValueError(f"插件导航入口缺失：{name}")
        for router in ROUTE_GROUPS[plugin.id]:
            app.include_router(router)
    app.state.plugins = PLUGINS
    app.state.primary_nav = tuple(link for plugin in PLUGINS if plugin.primary for link in plugin.links)
    app.state.plugin_nav = tuple(link for plugin in PLUGINS if not plugin.primary for link in plugin.links)
