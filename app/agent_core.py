"""Compatibility facade for callers of the original local task runtime."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

from app.agent_runtime.application.artifact_service import ArtifactService
from app.agent_runtime.application.identity import now
from app.agent_runtime.application.ports import ModelPort, SearchPort
from app.agent_runtime.application.project_service import ProjectService
from app.agent_runtime.application.run_service import Dispatch, RunService
from app.agent_runtime.application.task_service import TaskService
from app.agent_runtime.domain.models import AgentRun, AgentStep, Artifact, ToolCall, WorkspaceProject, WorkspaceTask
from app.agent_runtime.domain.states import (
    ARTIFACT_STATUSES as ARTIFACT_STATUSES,
    DEFAULT_PROJECT_ID as DEFAULT_PROJECT_ID,
    MAX_DESCRIPTION as MAX_DESCRIPTION,
    MAX_OBJECTIVE as MAX_OBJECTIVE,
    MAX_TITLE as MAX_TITLE,
    PROJECT_STATUSES as PROJECT_STATUSES,
    ROLE_DEFINITIONS as ROLE_DEFINITIONS,
    RUN_STATUSES as RUN_STATUSES,
    RUN_STATUS_LABELS as RUN_STATUS_LABELS,
    STEP_STATUSES as STEP_STATUSES,
    TASK_STATUSES as TASK_STATUSES,
    TASK_TYPES as TASK_TYPES,
    TASK_STATUS_LABELS as TASK_STATUS_LABELS,
    TASK_TYPE_LABELS as TASK_TYPE_LABELS,
)
from app.agent_runtime.infrastructure.sqlite.database import initialize
from app.agent_runtime.infrastructure.sqlite.unit_of_work import SQLiteUnitOfWork
from app.agent_runtime.infrastructure.storage.artifact_storage import ArtifactStorage
from app.agent_runtime.runtime.local_executor import LocalExecutor
from app.agent_runtime.runtime.model_executor import ModelExecutor
from app.database import apply_migrations, connect_database
from app.search import SearchResult


class AgentCoreRepository:
    """Compose services and retain the original AgentCore API."""

    def __init__(self, data_root: Path, *, search: SearchPort | None = None, model: ModelPort | None = None) -> None:
        self.data_root = data_root
        self.database_path = data_root / "workspace.db"
        self.artifact_root = data_root / "working" / "agent-artifacts"
        storage = ArtifactStorage(self.artifact_root)
        initialize(data_root, migrate=apply_migrations)
        uow = SQLiteUnitOfWork(self.connect)
        with uow(write=True) as repos:
            repos.runtime.seed_project(now())
        self.project_service = ProjectService(uow)
        self.task_service = TaskService(uow)
        self.artifact_service = ArtifactService(uow, storage)
        self.run_service = RunService(
            uow, self.task_service, self.artifact_service, LocalExecutor(search),
            ModelExecutor(model),
        )

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def projects(self, *, include_archived: bool = False) -> tuple[WorkspaceProject, ...]:
        return self.project_service.projects(include_archived=include_archived)

    def project(self, project_id: str) -> WorkspaceProject | None:
        return self.project_service.project(project_id)

    def create_project(self, *, title: str, description: str = "") -> WorkspaceProject:
        return self.project_service.create_project(title=title, description=description)

    def tasks(self, *, project_id: str = "") -> tuple[WorkspaceTask, ...]:
        return self.task_service.tasks(project_id=project_id)

    def task(self, task_id: str) -> WorkspaceTask | None:
        return self.task_service.task(task_id)

    def linked_tasks(self, goal_id: str) -> dict[str, str]:
        return self.task_service.linked_tasks(goal_id)

    def task_source(self, task_id: str) -> tuple[str, str] | None:
        return self.task_service.task_source(task_id)

    def private_task_ids(self) -> set[str]:
        return self.task_service.private_task_ids()

    def daily_task_ids(self) -> dict[str, str]:
        return self.task_service.daily_task_ids()

    def daily_task_source(self, task_id: str) -> str:
        return self.task_service.daily_task_source(task_id)

    def decision(self, run_id: str) -> dict | None:
        return self.run_service.decision(run_id)

    def planned_decisions(self) -> dict[str, str]:
        return self.run_service.planned_decisions()

    def update_run_objective(self, run_id: str, objective: str) -> None:
        self.run_service.update_run_objective(run_id, objective)

    def answer_decision(self, run_id: str, answer: str) -> None:
        self.run_service.answer_decision(run_id, answer)

    def attention_runs(self) -> list[dict]:
        return self.run_service.attention_runs()

    def create_task(
        self,
        *,
        title: str,
        objective: str,
        task_type: str,
        project_id: str,
        priority: int = 3,
        source_action_id: str = "",
        source_event_id: str = "",
    ) -> WorkspaceTask:
        return self.task_service.create_task(
            title=title, objective=objective, task_type=task_type, project_id=project_id,
            priority=priority, source_action_id=source_action_id, source_event_id=source_event_id,
        )

    def plan_task(self, task_id: str) -> AgentRun:
        return self.run_service.plan_task(task_id)

    def runs(self, *, task_id: str = "") -> tuple[AgentRun, ...]:
        return self.run_service.runs(task_id=task_id)

    def run(self, run_id: str) -> AgentRun | None:
        return self.run_service.run(run_id)

    def steps(self, run_id: str) -> tuple[AgentStep, ...]:
        return self.run_service.steps(run_id)

    def tool_calls(self, run_id: str) -> tuple[ToolCall, ...]:
        return self.run_service.tool_calls(run_id)

    def artifacts(self, *, task_id: str = "", run_id: str = "") -> tuple[Artifact, ...]:
        return self.artifact_service.artifacts(task_id=task_id, run_id=run_id)

    def artifact(self, artifact_id: str) -> Artifact | None:
        return self.artifact_service.artifact(artifact_id)

    def artifact_content(self, artifact_id: str) -> str:
        return self.artifact_service.artifact_content(artifact_id)

    def execute_run(
        self, run_id: str, search_results: Iterable[SearchResult] | None = None, *,
        model: Callable[[], dict] | None = None, expected_answer: str = "", expected_revision: int | None = None,
        dispatch: Dispatch | None = None,
    ) -> Artifact | None:
        return self.run_service.execute_legacy(
            run_id, search_results, model=model, expected_answer=expected_answer,
            expected_revision=expected_revision, dispatch=dispatch,
        )

    def recover_interrupted_runs(self) -> None:
        self.run_service.recover_interrupted_runs()

    def approve_run(self, run_id: str) -> None:
        self.run_service.approve_run(run_id)

    def cancel_run(self, run_id: str) -> None:
        self.run_service.cancel_run(run_id)
