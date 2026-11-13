import re
from itertools import islice
from collections.abc import Iterable

from app.agent_runtime.application.identity import identifier, now
from app.agent_runtime.application.ports import Candidate, SearchPort, Source
from app.agent_runtime.domain.models import ToolCall, WorkspaceTask
from app.agent_runtime.domain.states import ROLE_DEFINITIONS


class LocalExecutor:
    def __init__(self, search: SearchPort | None = None):
        self.search = search

    def execute(
        self, task: WorkspaceTask, run_id: str, step_id: str, sources: Iterable[Source] | None = None,
    ) -> tuple[Candidate, ToolCall]:
        if sources is None:
            sources = self.search.sources(task) if self.search is not None else ()
        rows = tuple(islice(sources, 8))
        term_count = min(len(re.findall(r"[\w\u3400-\u9fff]+", task.objective)), 8)
        call = ToolCall(
            identifier("tool-call"), run_id, step_id, "workspace.search", "completed",
            f"本地关键词 {term_count} 个；未保存原始查询正文",
            f"返回 {len(rows)} 条本地来源摘要", now(),
        )
        body = _worksheet(task, rows)
        return Candidate(body, f"本地来源 {len(rows)} 条；等待作者确认。"), call

    @staticmethod
    def review(candidate: Candidate) -> None:
        if "正式知识结论" not in candidate.body or "未调用模型" not in candidate.body:
            raise RuntimeError("Reviewer 未通过任务产物边界检查")


def _worksheet(
    task: WorkspaceTask,
    sources: tuple[Source, ...],
) -> str:
    role = next((value for value in ROLE_DEFINITIONS.values() if value[0] == task.assigned_role), None)
    role_label = role[1] if role else task.assigned_role
    rows = list(sources)
    source_lines = "\n".join(
        f"- [{value.source_label}] {value.title} — {re.sub(r'<[^>]+>', '', value.snippet).strip()}"
        for value in rows
    ) or "- 当前本地索引没有命中内容；需要作者补充来源或拆分目标。"
    return (
        f"# {task.title}\n\n"
        f"> 本产物由本地规则式 {role_label} 角色生成，未调用模型，"
        "不代表正式知识结论。\n\n"
        "## 任务目标\n\n"
        f"{task.objective}\n\n"
        "## 本地来源摘要\n\n"
        f"{source_lines}\n\n"
        "## 建议执行路径\n\n"
        "1. 确认目标边界与完成标准。\n"
        "2. 阅读命中的本地来源，标记事实、判断和仍需验证的问题。\n"
        "3. 只在证据充分时形成候选结论；正式入库前关联随想与主题。\n\n"
        "## Reviewer 检查\n\n"
        "- 未调用外部模型或网络。\n"
        "- 未修改随想、知识卡、文章或外部系统。\n"
        "- 产物仅保存在私有工作目录，等待作者确认。\n"
    )
