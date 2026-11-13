"""Built-in desktop plugins, registered once for routing and navigation."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI

DAILY_ORIGIN = "http://localhost:8767"
WORKBENCH_ORIGIN = "http://127.0.0.1:8765"


@dataclass(frozen=True)
class Plugin:
    id: str
    routes: tuple[APIRouter, ...]
    links: tuple[tuple[str, str], ...]
    data_owner: str = "工作台"
    version: str = "1"
    dependencies: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ("workspace.local",)
    primary: bool = False


def register_plugins(app: FastAPI) -> None:
    from app.routers import (
        agent_core, assistant, career_learning, creation, daily, focus, income,
        knowledge_models, resumes, system, wechat, workflow, workspace_content,
    )

    plugins = (
        Plugin("daily", (daily.router,), (("workspace", "日常工作"),), "Super Productivity", "20.0.0",
               permissions=("tasks.read_selected", "tasks.read_daily"), primary=True),
        Plugin("workflow", (workflow.router,), (("tasks", "AI 工作流"),), "Agent Autoloop", "1.8.1",
               ("model-gateway",), ("model.preview_confirm", "artifact.local"), True),
        Plugin("planning", (workspace_content.router, focus.router),
               (("focus", "主线与分支"), ("ideas", "想法库"), ("reviews", "周回顾"), ("legacy_workspace", "旧待办"))),
        Plugin("legacy-agent", (agent_core.router,), (("legacy_tasks", "旧任务"), ("runs", "旧执行记录"))),
        Plugin("knowledge", (knowledge_models.router,), (("knowledge", "知识库"), ("models", "模型与成本"))),
        Plugin("publishing", (creation.router, wechat.router), (("articles", "创作"),)),
        Plugin("career", (resumes.router, career_learning.router), (("career", "求职"), ("learning", "学习"))),
        Plugin("assistant", (assistant.router,), (("assistant", "助手"),)),
        Plugin("income", (income.router,), (("income", "收入"),)),
        Plugin("workspace-tools", (system.router,), (("search", "全局检索"), ("settings", "设置"), ("trash", "回收站"))),
    )
    app.state.plugins = plugins
    app.state.primary_nav = tuple(link for plugin in plugins if plugin.primary for link in plugin.links)
    app.state.plugin_nav = tuple(link for plugin in plugins if not plugin.primary for link in plugin.links)
    for plugin in plugins:
        for router in plugin.routes:
            app.include_router(router)


def plugin_root(data_root: Path) -> Path:
    return data_root / "working" / "plugins"
