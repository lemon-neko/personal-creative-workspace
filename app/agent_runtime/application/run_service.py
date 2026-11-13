from collections.abc import Callable, Iterable

from app.agent_runtime.application.artifact_service import ArtifactService
from app.agent_runtime.application.identity import identifier, now
from app.agent_runtime.application.ports import Decision, LocalStrategy, ModelStrategy, RuntimeData, Source, UnitOfWork
from app.agent_runtime.application.task_service import TaskService
from app.agent_runtime.domain.exceptions import PreviewError
from app.agent_runtime.domain.models import AgentRun, AgentStep, Artifact, ToolCall, WorkspaceTask
from app.agent_runtime.domain.policies import (
    checked_objective,
    require_decision_answer,
    require_executable,
    require_plannable,
    require_reviewing,
    require_step_transition,
    should_cancel,
)

Dispatch = Callable[[Callable[[], Artifact | None]], None]


class RunService:
    def __init__(
        self, uow: UnitOfWork, tasks: TaskService, artifacts: ArtifactService,
        local: LocalStrategy, model: ModelStrategy,
    ):
        self.uow = uow
        self.tasks = tasks
        self.artifact_service = artifacts
        self.local = local
        self.model = model

    def runs(self, *, task_id: str = "") -> tuple[AgentRun, ...]:
        with self.uow() as repos:
            return repos.runtime.runs(task_id=task_id)

    def run(self, run_id: str) -> AgentRun | None:
        with self.uow() as repos:
            return repos.runtime.run(run_id)

    def steps(self, run_id: str) -> tuple[AgentStep, ...]:
        with self.uow() as repos:
            return repos.runtime.steps(run_id)

    def tool_calls(self, run_id: str) -> tuple[ToolCall, ...]:
        with self.uow() as repos:
            return repos.runtime.tool_calls(run_id)

    def decision(self, run_id: str) -> dict | None:
        with self.uow() as repos:
            return repos.runtime.decision(run_id)

    def planned_decisions(self) -> dict[str, str]:
        with self.uow() as repos:
            return repos.runtime.planned_decisions()

    def attention_runs(self) -> list[dict]:
        with self.uow() as repos:
            return repos.focus.attention_runs()

    def plan_task(self, task_id: str) -> AgentRun:
        with self.uow(write=True) as repos:
            repo = repos.runtime
            task = repo.task(task_id)
            if task is None:
                raise KeyError(task_id)
            require_plannable(task)
            if existing := repo.planned_run(task_id):
                return existing
            stamp = now()
            run = AgentRun(identifier("run"), task_id, task.assigned_role, "planned", 0, "", stamp, "", "")
            steps = tuple(
                AgentStep(identifier("step"), run.id, position, key, title, "pending", "", "", "")
                for position, key, title in (
                    (1, "load-context", "准备任务上下文"),
                    (2, "compose-artifact", "组织任务工作纸"),
                    (3, "review-artifact", "执行确定性审查"),
                )
            )
            repo.add_run(run, steps)
            repo.set_task_state(task_id, "planned", "运行本地计划", stamp)
        return run

    def update_run_objective(self, run_id: str, objective: str) -> None:
        objective = checked_objective(objective)
        with self.uow(write=True) as repos:
            repo = repos.runtime
            run = repo.run(run_id)
            if run is None or run.status != "planned" or repo.decision(run_id):
                raise ValueError("本轮任务材料已锁定，请刷新页面")
            self.tasks.update_task_objective(repo, run.task_id, objective)

    def answer_decision(self, run_id: str, answer: str) -> None:
        with self.uow(write=True) as repos:
            repo = repos.runtime
            run, decision = repo.run(run_id), repo.decision(run_id)
            if not run or not decision:
                raise ValueError("本次运行没有待回答的问题")
            require_decision_answer(run.status, decision["answer"], decision["options"], answer)
            repo.answer_decision(run_id, answer)
            repo.set_task_state(run.task_id, "planned", "预览并继续 AI 工作", now())

    @property
    def model_enabled(self) -> bool:
        return self.model.enabled

    def model_preview(self, run: AgentRun, task: WorkspaceTask, decision: dict | None) -> dict | None:
        if task.id in self.tasks.private_task_ids():
            return None
        return self.model.preview(run, task, decision)

    def execute_run(self, run_id: str, search_results: Iterable[Source] | None = None) -> Artifact | None:
        return self._execute_run(run_id, search_results)

    def execute_model(self, run_id: str, fingerprint: str, *, dispatch: Dispatch | None = None) -> Artifact | None:
        return self._execute_run(run_id, preview_fingerprint=fingerprint, dispatch=dispatch)

    def execute_legacy(
        self, run_id: str, sources: Iterable[Source] | None, *, model: Callable[[], dict] | None,
        expected_answer: str, expected_revision: int | None, dispatch: Dispatch | None,
    ) -> Artifact | None:
        """Retain the in-process callback API; only execute_model selects a configured gateway."""
        return self._execute_run(
            run_id, sources, model=model, expected_answer=expected_answer,
            expected_revision=expected_revision, dispatch=dispatch,
        )

    def _execute_run(
        self, run_id: str, search_results: Iterable[Source] | None = None, *,
        model: Callable[[], dict] | None = None, expected_answer: str = "", expected_revision: int | None = None,
        dispatch: Dispatch | None = None, preview_fingerprint: str | None = None,
    ) -> Artifact | None:
        with self.uow(write=True) as repos:
            repo = repos.runtime
            run = repo.run(run_id)
            if run is None:
                raise KeyError(run_id)
            if preview_fingerprint is None and run.status == "reviewing":
                existing = repo.artifacts(run_id=run_id)
                if existing:
                    return existing[0]
            if preview_fingerprint is not None and run.status != "planned":
                raise PreviewError("预览已失效，请刷新后重新确认。")
            require_executable(run)
            task = repo.task(run.task_id)
            if task is None:
                raise KeyError(run.task_id)
            steps = repo.steps(run_id)
            if len(steps) != 3:
                raise RuntimeError("执行计划不完整")
            decision = repo.decision(run_id)
            if preview_fingerprint is not None:
                if task.id in repos.focus.private_task_ids():
                    raise PreviewError("预览已失效，请刷新后重新确认。")
                model = self.model.confirm(run, task, decision, preview_fingerprint)
                expected_answer = decision["answer"] if decision else ""
            if decision and (model is None or not decision["answer"] or decision["answer"] != expected_answer):
                raise ValueError("请先回答决策问题，再预览并继续 AI 工作")
            if expected_revision is not None and expected_revision != task.revision:
                raise ValueError("任务材料已变化，请重新确认预览")
            stamp = now()
            repo.claim_run(run_id, stamp)
            repo.set_task_state(task.id, "running", "等待运行完成", stamp)

        def finish() -> Artifact | None:
            return self._finish_run(
                run_id, task, steps, search_results, model,
                answered=bool(expected_answer), confirmed=preview_fingerprint is not None,
            )

        if dispatch is None:
            return finish()
        try:
            dispatch(finish)
        except Exception:
            self._fail_run(run_id, task.id, model is not None)
            raise
        return None

    def _finish_run(
        self, run_id: str, task: WorkspaceTask, steps: tuple[AgentStep, ...],
        sources: Iterable[Source] | None, model: Callable[[], dict] | None, *, answered: bool, confirmed: bool,
    ) -> Artifact | None:
        try:
            call = None
            if model is not None:
                with self.uow() as repos:
                    self._require_running(repos.runtime.run(run_id))
                    if confirmed and task.id in repos.focus.private_task_ids():
                        raise RuntimeError("这项任务已移出工作台")
                result = self.model.execute(task, model, answered=answered)
                if isinstance(result, Decision):
                    with self.uow(write=True) as repos:
                        repo = repos.runtime
                        self._require_running(repo.run(run_id))
                        repo.add_decision(run_id, result.question, result.options)
                        repo.set_run_progress(run_id, "planned", 0)
                        repo.set_task_state(task.id, "planned", "回答 AI 提出的决策", now())
                    return None
            with self.uow(write=True) as repos:
                self._require_running(repos.runtime.run(run_id))
                require_step_transition(steps[0].status, "running")
                repos.runtime.set_step(steps[0].id, "running", now())
            if model is None:
                result, call = self.local.execute(task, run_id, steps[0].id, sources)
            with self.uow(write=True) as repos:
                repo = repos.runtime
                self._require_running(repo.run(run_id))
                if call is not None:
                    repo.add_tool_call(call)
                stamp = now()
                repo.set_step(steps[0].id, "completed", stamp)
                require_step_transition(steps[1].status, "running")
                repo.set_step(steps[1].id, "running", stamp)

            review_error = None
            if model is None:
                try:
                    self.local.review(result)
                except RuntimeError as error:
                    review_error = error
            with self.artifact_service.save_artifact(task, run_id, result) as artifact, self.uow(write=True) as repos:
                repo = repos.runtime
                self._require_running(repo.run(run_id))
                repo.add_artifact(artifact)
                stamp = now()
                repo.set_step(steps[1].id, "completed", stamp, artifact.id)
                require_step_transition(steps[2].status, "running")
                repo.set_step(steps[2].id, "running", stamp)
                if review_error is None:
                    repo.set_step(steps[2].id, "completed", stamp, artifact.id)
                    repo.set_run_progress(run_id, "reviewing", 3)
                    repo.set_task_state(task.id, "reviewing", "人工确认任务产物", stamp)
                else:
                    self._mark_failed(repo, run_id, task.id, model=False)
            if review_error is not None:
                raise review_error
            return artifact
        except Exception:
            self._fail_run(run_id, task.id, model is not None)
            raise

    @staticmethod
    def _require_running(run: AgentRun | None) -> None:
        if run is None or run.status != "running":
            raise ValueError("运行状态已变化，请刷新")

    def _fail_run(self, run_id: str, task_id: str, model: bool) -> None:
        with self.uow(write=True) as repos:
            repo = repos.runtime
            run = repo.run(run_id)
            if run is not None and run.status == "running":
                self._mark_failed(repo, run_id, task_id, model=model)

    def _mark_failed(self, repo: RuntimeData, run_id: str, task_id: str, *, model: bool) -> None:
        stamp = now()
        repo.finish_run(run_id, "failed", stamp, "model-runtime-error" if model else "local-runtime-error")
        repo.finish_steps(run_id, "failed", stamp)
        self.artifact_service.reject_artifact(repo, run_id)
        repo.set_task_state(task_id, "failed", "检查本地运行记录", stamp)

    def recover_interrupted_runs(self) -> None:
        stamp = now()
        with self.uow(write=True) as repos:
            repo = repos.runtime
            for run in repo.running_runs():
                repo.finish_steps(run.id, "failed", stamp)
                self.artifact_service.reject_artifact(repo, run.id)
                repo.finish_run(run.id, "failed", stamp, "interrupted")
                repo.set_task_state(run.task_id, "failed", "上次运行中断，请重新规划", stamp)

    def approve_run(self, run_id: str) -> None:
        with self.uow() as repos:
            run = repos.runtime.run(run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status == "completed":
                return
            require_reviewing(run)
            artifacts = repos.runtime.artifacts(run_id=run_id)
        if not artifacts:
            raise ValueError("运行没有可确认的产物")
        for artifact in artifacts:
            self.artifact_service.validate_for_acceptance(artifact)

        with self.uow(write=True) as repos:
            repo = repos.runtime
            current = repo.run(run_id)
            if current is not None and current.status == "completed":
                return
            if current != run or repo.artifacts(run_id=run_id) != artifacts:
                raise ValueError("运行状态已变化，请刷新")
            stamp = now()
            for artifact in artifacts:
                self.artifact_service.accept_artifact(repo, artifact, stamp)
            repo.finish_run(run_id, "completed", stamp)
            repo.set_task_state(run.task_id, "completed", "已完成人工确认", stamp)

    def cancel_run(self, run_id: str) -> None:
        with self.uow(write=True) as repos:
            repo = repos.runtime
            run = repo.run(run_id)
            if run is None:
                raise KeyError(run_id)
            if not should_cancel(run):
                return
            stamp = now()
            repo.finish_run(run_id, "cancelled", stamp)
            repo.finish_steps(run_id, "cancelled", stamp, include_pending=True)
            self.artifact_service.reject_artifact(repo, run_id)
            repo.set_task_state(run.task_id, "cancelled", "任务已取消", stamp)
