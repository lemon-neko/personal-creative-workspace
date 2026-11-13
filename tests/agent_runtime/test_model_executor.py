import json

import pytest

from app.agent_runtime.application.ports import ModelPolicy
from app.agent_runtime.domain.exceptions import InputLimitError, PreviewError
from app.agent_runtime.runtime.model_executor import ModelExecutor


def test_confirmed_model_runs_outside_write_transaction_and_honors_token_limit(runtime, planned):
    _, run = planned
    service = runtime.run_service

    class FakeModel:
        limit = 100
        calls = 0

        def policy(self):
            return ModelPolicy("测试指令", "local", "test-endpoint", "test-model", self.limit, 50)

        def estimate_tokens(self, wire_text):
            assert wire_text.startswith("测试指令\n")
            return 10

        def candidate(self, material, *, answered):
            self.calls += 1
            assert json.loads(material)["objective"] == "更新后的虚构资料"
            assert not answered
            with service.uow(write=True) as repos:
                assert repos.runtime.run(run.id).status == "running"
            return {"draft": "模型测试候选"}

    model = FakeModel()
    service.model = ModelExecutor(model)
    fingerprint = service.model_preview(run, runtime.task(run.task_id), None)["fingerprint"]
    service.update_run_objective(run.id, "更新后的虚构资料")
    with pytest.raises(PreviewError):
        service.execute_model(run.id, fingerprint)
    confirmed = service.model_preview(run, runtime.task(run.task_id), None)["fingerprint"]
    model.limit = 1
    with pytest.raises(InputLimitError):
        service.execute_model(run.id, confirmed)
    assert model.calls == 0
    assert runtime.run(run.id).status == "planned"
    model.limit = 100
    artifact = service.execute_model(run.id, confirmed)
    assert artifact.status == "review"
    assert "模型测试候选" in runtime.artifact_content(artifact.id)
    with pytest.raises(PreviewError):
        service.execute_model(run.id, confirmed)
    assert model.calls == 1


def test_background_model_does_not_send_if_provider_changed_after_claim(runtime, planned):
    _, run = planned
    service = runtime.run_service

    class FakeModel:
        endpoint = "original"

        def policy(self):
            return ModelPolicy("测试指令", "local", self.endpoint, "test-model", 100, 50)

        def estimate_tokens(self, wire_text):
            return 10

        def candidate(self, material, *, answered):
            pytest.fail("不能发往未确认的端点")

    model = FakeModel()
    service.model = ModelExecutor(model)
    confirmed = service.model_preview(run, runtime.task(run.task_id), None)["fingerprint"]
    pending = []
    service.execute_model(run.id, confirmed, dispatch=pending.append)
    model.endpoint = "unconfirmed"
    with pytest.raises(PreviewError):
        pending[0]()
    assert runtime.run(run.id).status == "failed"
    assert not runtime.artifacts(run_id=run.id)
