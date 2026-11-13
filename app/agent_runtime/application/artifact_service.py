from collections.abc import Iterator
from contextlib import contextmanager

from app.agent_runtime.application.identity import identifier, now
from app.agent_runtime.application.ports import ArtifactFiles, Candidate, RuntimeData, UnitOfWork
from app.agent_runtime.domain.models import Artifact, WorkspaceTask
from app.agent_runtime.domain.policies import require_candidate


class ArtifactService:
    def __init__(self, uow: UnitOfWork, storage: ArtifactFiles):
        self.uow = uow
        self.storage = storage

    def artifacts(self, *, task_id: str = "", run_id: str = "") -> tuple[Artifact, ...]:
        with self.uow() as repos:
            return repos.runtime.artifacts(task_id=task_id, run_id=run_id)

    def artifact(self, artifact_id: str) -> Artifact | None:
        with self.uow() as repos:
            return repos.runtime.artifact(artifact_id)

    def artifact_content(self, artifact_id: str) -> str:
        artifact = self.artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: Artifact) -> str:
        return self.storage.read(artifact.storage_key, artifact.content_hash)

    @contextmanager
    def save_artifact(self, task: WorkspaceTask, run_id: str, candidate: Candidate) -> Iterator[Artifact]:
        artifact_id = identifier("artifact")
        key = f"{artifact_id}.md"
        digest = self.storage.write(key, candidate.body)
        artifact = Artifact(
            artifact_id, task.id, run_id, "task-worksheet", f"{task.title} · 任务工作纸",
            "review", key, digest, candidate.summary, now(), "",
        )
        try:
            yield artifact
        except BaseException:
            self.storage.remove(key)
            raise

    def validate_for_acceptance(self, artifact: Artifact) -> None:
        require_candidate(artifact)
        try:
            self.validate_artifact(artifact)
        except OSError as error:
            raise ValueError("无法读取待确认产物") from error

    @staticmethod
    def accept_artifact(repo: RuntimeData, artifact: Artifact, stamp: str) -> None:
        require_candidate(artifact)
        repo.set_artifact_status(artifact.id, "accepted", stamp)

    @staticmethod
    def reject_artifact(repo: RuntimeData, run_id: str) -> None:
        repo.reject_candidates(run_id)
