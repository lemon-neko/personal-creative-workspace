"""Static catalog of trusted desktop plugins."""

import re
from dataclasses import dataclass

from app.plugin_paths import (
    DAILY_ORIGIN as DAILY_ORIGIN,
    WORKBENCH_ORIGIN as WORKBENCH_ORIGIN,
    plugin_root as plugin_root,
)


@dataclass(frozen=True)
class PluginSpec:
    id: str
    links: tuple[tuple[str, str], ...]
    data_owner: str = "工作台"
    version: str = "1"
    dependencies: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ("workspace.local",)
    primary: bool = False


PLUGINS = (
    PluginSpec("daily", (("workspace", "日常工作"),), "Super Productivity", "20.0.0",
               permissions=("tasks.read_selected", "tasks.read_daily"), primary=True),
    PluginSpec("workflow", (("tasks", "AI 工作流"),), "Agent Autoloop", "1.8.1",
               ("model-gateway",), ("model.preview_confirm", "artifact.local"), True),
    PluginSpec("planning", (("focus", "主线与分支"), ("ideas", "想法库"), ("reviews", "周回顾"), ("legacy_workspace", "旧待办"))),
    PluginSpec("legacy-agent", (("legacy_tasks", "旧任务"), ("runs", "旧执行记录"))),
    PluginSpec("knowledge", (("knowledge", "知识库"), ("models", "模型与成本"))),
    PluginSpec("publishing", (("articles", "创作"),)),
    PluginSpec("career", (("career", "求职"), ("learning", "学习"))),
    PluginSpec("assistant", (("assistant", "助手"),)),
    PluginSpec("income", (("income", "收入"),)),
    PluginSpec("workspace-tools", (("search", "全局检索"), ("settings", "设置"), ("trash", "回收站"))),
)
CAPABILITIES = frozenset({"model-gateway"})
PRIMARY = (("daily", "workspace"), ("workflow", "tasks"))


def get_plugin(plugin_id: str) -> PluginSpec:
    return next(plugin for plugin in PLUGINS if plugin.id == plugin_id)


def validate_registry(plugins: tuple[PluginSpec, ...]) -> None:
    index = {plugin.id: plugin for plugin in plugins}
    if len(index) != len(plugins) or index.keys() & CAPABILITIES:
        raise ValueError("插件 ID 重复或与共享能力冲突")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(plugin_id: str) -> None:
        if plugin_id in visiting:
            raise ValueError("插件存在循环依赖")
        if plugin_id in visited or plugin_id in CAPABILITIES:
            return
        visiting.add(plugin_id)
        for dependency in index[plugin_id].dependencies:
            visit(dependency)
        visiting.remove(plugin_id)
        visited.add(plugin_id)

    names = set()
    primary = []
    for plugin in plugins:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", plugin.id) or not re.fullmatch(r"\d+(?:\.\d+\.\d+)?", plugin.version):
            raise ValueError("插件 ID 或版本格式无效")
        deps = set(plugin.dependencies)
        if deps - (index.keys() | CAPABILITIES) or len(deps) != len(plugin.dependencies):
            raise ValueError("插件依赖无效")
        for route, label in plugin.links:
            if not route or not label.strip() or route in names:
                raise ValueError("插件导航入口重复或无效")
            names.add(route)
            if plugin.primary:
                primary.append((plugin.id, route))
    if tuple(primary) != PRIMARY:
        raise ValueError("插件主导航不符")
    for plugin in plugins:
        visit(plugin.id)
