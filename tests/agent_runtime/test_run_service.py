import pytest


def test_stale_background_work_cannot_resurrect_interrupted_run(runtime, planned):
    task, run = planned
    assert runtime.plan_task(task.id) == run
    pending = []

    def never_call():
        pytest.fail("恢复时不能再次调用模型")

    runtime.execute_run(run.id, (), model=never_call, dispatch=pending.append)
    runtime.run_service.recover_interrupted_runs()
    with pytest.raises(ValueError, match="运行状态已变化"):
        pending[0]()
    runtime.run_service.recover_interrupted_runs()
    assert runtime.run(run.id).error_code == "interrupted"
    retry = runtime.plan_task(task.id)
    assert retry.id != run.id
    assert {entry.id for entry in runtime.runs(task_id=task.id)} == {run.id, retry.id}
    assert runtime.task(task.id).status == "planned"
    assert not runtime.artifacts(run_id=run.id)


def test_artifact_commit_failure_leaves_failed_run_without_partial_result(runtime, planned, monkeypatch):
    task, run = planned

    def fail(*_args):
        raise OSError("fictional write failure after artifact insertion")

    monkeypatch.setattr(
        "app.agent_runtime.infrastructure.sqlite.repositories.RuntimeRepository.set_run_progress", fail,
    )
    with pytest.raises(OSError, match="fictional write failure"):
        runtime.run_service.execute_run(run.id)
    assert runtime.run(run.id).error_code == "local-runtime-error"
    assert runtime.task(task.id).status == "failed"
    assert not runtime.artifacts(run_id=run.id)
    assert runtime.tool_calls(run.id)[0].tool_key == "workspace.search"
    assert not list(runtime.artifact_root.glob("*.md"))


def test_decision_answer_rolls_back_if_task_update_fails(runtime, planned, monkeypatch):
    task, run = planned
    runtime.execute_run(run.id, (), model=lambda: {"question": "选择虚构格式", "options": ["甲", "乙"]})
    original = runtime.task(task.id)

    def fail(*_args):
        raise OSError("fictional task update failure")

    monkeypatch.setattr(
        "app.agent_runtime.infrastructure.sqlite.repositories.RuntimeRepository.set_task_state", fail,
    )
    with pytest.raises(OSError, match="fictional task update failure"):
        runtime.run_service.answer_decision(run.id, "甲")
    assert runtime.decision(run.id)["answer"] == ""
    assert runtime.task(task.id) == original
