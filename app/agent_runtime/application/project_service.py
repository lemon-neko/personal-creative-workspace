from app.agent_runtime.application.identity import identifier, now
from app.agent_runtime.application.ports import UnitOfWork
from app.agent_runtime.domain.models import WorkspaceProject
from app.agent_runtime.domain.policies import clean
from app.agent_runtime.domain.states import MAX_DESCRIPTION, MAX_TITLE


class ProjectService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def projects(self, *, include_archived: bool = False) -> tuple[WorkspaceProject, ...]:
        with self.uow() as repos:
            return repos.runtime.projects(include_archived=include_archived)

    def project(self, project_id: str) -> WorkspaceProject | None:
        with self.uow() as repos:
            return repos.runtime.project(project_id)

    def create_project(self, *, title: str, description: str = "") -> WorkspaceProject:
        title = clean(title, MAX_TITLE)
        if not title:
            raise ValueError("项目名称不能为空")
        stamp = now()
        project = WorkspaceProject(
            identifier("project"), title, str(description or "").strip()[:MAX_DESCRIPTION], "active", stamp, stamp,
        )
        with self.uow(write=True) as repos:
            repos.runtime.add_project(project)
        return project
