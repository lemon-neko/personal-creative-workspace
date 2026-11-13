from stat import S_IMODE

import pytest


def test_acceptance_validates_private_artifact_and_is_idempotent(runtime, planned):
    task, run = planned
    artifact = runtime.run_service.execute_run(run.id)
    service = runtime.artifact_service
    body = service.artifact_content(artifact.id)
    path = runtime.artifact_root / artifact.storage_key
    assert S_IMODE(path.stat().st_mode) == 0o600
    assert S_IMODE(runtime.artifact_root.stat().st_mode) == 0o700
    path.write_text("变更过的样例", encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        service.artifact_content(artifact.id)
    with pytest.raises(ValueError, match="校验失败"):
        runtime.approve_run(run.id)
    assert service.artifact(artifact.id).status == "review"
    assert runtime.task(task.id).status == "reviewing"
    path.write_text(body, encoding="utf-8")
    runtime.approve_run(run.id)
    accepted = service.artifact(artifact.id)
    runtime.approve_run(run.id)
    assert service.artifact(artifact.id) == accepted
    assert accepted.status == "accepted"
    with pytest.raises(ValueError, match="不能执行"):
        runtime.run_service.execute_run(run.id)
