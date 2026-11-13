from app.agent_runtime.domain.models import AgentRun, Artifact, WorkspaceTask
from app.agent_runtime.domain.states import MAX_OBJECTIVE, MAX_TITLE, ROLE_DEFINITIONS


def clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def task_material(title: str, objective: str, task_type: str, priority: int) -> tuple[str, str, str]:
    title = clean(title, MAX_TITLE)
    objective = str(objective or "").strip()[:MAX_OBJECTIVE]
    if not title or not objective:
        raise ValueError("任务名称和目标不能为空")
    if task_type not in ROLE_DEFINITIONS:
        raise ValueError("任务类型无效")
    if priority not in range(1, 6):
        raise ValueError("优先级必须在 1 到 5 之间")
    return title, objective, ROLE_DEFINITIONS[task_type][0]


def checked_objective(objective: str) -> str:
    objective = objective.strip()
    if not objective or len(objective) > MAX_OBJECTIVE:
        raise ValueError(f"任务材料不能为空，最多 {MAX_OBJECTIVE} 字符")
    return objective


def require_plannable(task: WorkspaceTask) -> None:
    if task.status not in {"draft", "planned", "failed", "cancelled"}:
        raise ValueError("当前任务状态不能重新规划")


def require_executable(run: AgentRun) -> None:
    if run.status != "planned":
        raise ValueError("当前运行状态不能执行")


def should_cancel(run: AgentRun) -> bool:
    if run.status in {"completed", "cancelled", "failed"}:
        return False
    if run.status not in {"planned", "reviewing"}:
        raise ValueError("本次正在执行或状态已变化，请稍后刷新")
    return True


def require_reviewing(run: AgentRun) -> None:
    if run.status != "reviewing":
        raise ValueError("只有待确认的运行可以接受")


def require_candidate(artifact: Artifact) -> None:
    if artifact.status != "review":
        raise ValueError("只有待确认的产物可以验收")


def require_step_transition(current: str, target: str) -> None:
    allowed = {"pending": {"running", "cancelled"}, "running": {"completed", "failed", "cancelled"}}
    if target not in allowed.get(current, ()):
        raise ValueError("步骤状态无效")


def require_decision_answer(status: str, current_answer: str, options: list[str], answer: str) -> None:
    if status != "planned" or current_answer:
        raise ValueError("本次运行没有待回答的问题")
    if answer not in options:
        raise ValueError("请选择给出的一个选项")
