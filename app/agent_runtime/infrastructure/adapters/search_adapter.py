from app.agent_runtime.domain.models import WorkspaceTask
from app.search import SearchRepository, SearchResult


class SearchAdapter:
    def __init__(self, search: SearchRepository):
        self.search = search

    def sources(self, task: WorkspaceTask) -> tuple[SearchResult, ...]:
        return tuple(self.search.search(task.objective, limit=8) or self.search.search(task.title, limit=8))
