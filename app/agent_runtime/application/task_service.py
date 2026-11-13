from app.agent_runtime.application.identity import identifier, now
from app.agent_runtime.application.ports import RuntimeData, UnitOfWork
from app.agent_runtime.domain.models import WorkspaceTask
from app.agent_runtime.domain.policies import checked_objective, task_material


class TaskService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def create_task(
        self, *, title: str, objective: str, task_type: str, project_id: str,
        priority: int = 3, source_action_id: str = "", source_event_id: str = "",
    ) -> WorkspaceTask:
        title, objective, role_key = task_material(title, objective, task_type, priority)
        if source_action_id and source_event_id:
            raise ValueError("一个任务只能关联一项行动")
        source = {"action_id": source_action_id, "event_id": source_event_id}
        linked = bool(source_action_id or source_event_id)
        with self.uow(write=True) as repos:
            if repos.runtime.project(project_id) is None:
                raise ValueError("项目不存在")
            if linked and (existing := repos.focus.existing_task(**source)) is not None:
                return existing
            stamp = now()
            task = WorkspaceTask(
                identifier("task"), project_id, title, objective, task_type, role_key, "draft", priority,
                "生成本地执行计划", 1, stamp, stamp,
            )
            repos.runtime.add_task(task)
            if linked:
                repos.focus.link_task(task.id, **source)
        return task

    @staticmethod
    def update_task_objective(repo: RuntimeData, task_id: str, objective: str) -> None:
        repo.set_objective(task_id, checked_objective(objective), now())

    def tasks(self, *, project_id: str = "") -> tuple[WorkspaceTask, ...]:
        with self.uow() as repos:
            return repos.runtime.tasks(project_id=project_id)

    def task(self, task_id: str) -> WorkspaceTask | None:
        with self.uow() as repos:
            return repos.runtime.task(task_id)

    def linked_tasks(self, goal_id: str) -> dict[str, str]:
        with self.uow() as repos:
            return repos.focus.linked_tasks(goal_id)

    def task_source(self, task_id: str) -> tuple[str, str] | None:
        with self.uow() as repos:
            return repos.focus.task_source(task_id)

    def private_task_ids(self) -> set[str]:
        with self.uow() as repos:
            return repos.focus.private_task_ids()

    def daily_task_ids(self) -> dict[str, str]:
        with self.uow() as repos:
            return repos.focus.daily_task_ids()

    def daily_task_source(self, task_id: str) -> str:
        with self.uow() as repos:
            return repos.focus.daily_task_source(task_id)

    def daily_task_context(self, task_id: str) -> tuple[str, str]:
        with self.uow() as repos:
            event_id = repos.focus.daily_task_source(task_id)
            return event_id, repos.focus.planner_day(event_id) if event_id else ""
