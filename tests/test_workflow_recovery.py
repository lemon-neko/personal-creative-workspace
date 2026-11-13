"""The workbench can resend Hub messages without replaying model requests."""

import asyncio
import json

import httpx
import pytest

from app.workflow import Workflow
from app.workflow_hub import EVENT_TYPE
from app.workflow_worker import WorkflowWorker
from tests.test_workflow_plugins import make_workspace

KEYS = {"source": "local-test-source", "worker": "local-test-worker", "owner": "local-test-owner"}


def approved_item(workflow):
    item_id = workflow.store.handoff("manual:recovery", "虚构恢复验收")
    preview = workflow.preview(item_id, "选择颜色")
    workflow.approve(item_id, "选择颜色", None, None, None, preview["fingerprint"])
    return workflow.store.turns(item_id)[0]


def test_dispatch_reuses_approved_turn_id_after_lost_ack(tmp_path):
    app, model = make_workspace(tmp_path)
    workflow = app.state.workflow
    turn = approved_item(workflow)
    messages = []

    def hub(request):
        assert request.url.path == "/v1/events"
        assert request.headers["authorization"] == "Bearer " + KEYS["source"]
        messages.append(json.loads(request.content))
        if len(messages) == 1:
            raise httpx.ReadTimeout("Hub accepted the event but the reply was lost", request=request)
        return httpx.Response(200, json={"duplicate": True})

    async def deliver():
        async with workflow.autoloop.connect("http://127.0.0.1", KEYS, transport=httpx.MockTransport(hub)):
            worker = WorkflowWorker(workflow)
            with pytest.raises(httpx.ReadTimeout):
                await worker.dispatch()
            assert not workflow.store.turn(turn["id"])["delivered"]
            await worker.dispatch()
            await worker.dispatch()

    asyncio.run(deliver())
    assert messages == [{"id": turn["id"], "type": EVENT_TYPE, "subject": turn["item_id"]}] * 2
    assert workflow.store.turn(turn["id"])["delivered"]
    assert not model.calls


def test_restart_resends_saved_receipt_without_another_model_call(tmp_path):
    app, model = make_workspace(tmp_path)
    workflow = app.state.workflow
    turn = approved_item(workflow)
    job = {"run": 41, "token": "local-test-job", "context": {"events": [
        {"type": EVENT_TYPE, "source": "workbench", "id": turn["id"], "subject": turn["item_id"]},
    ]}}
    receipts, starts = [], []

    def hub(request):
        assert request.headers["authorization"] == "Bearer local-test-job"
        if request.url.path == "/v1/runs/41/started":
            starts.append(json.loads(request.content))
        elif request.url.path == "/v1/runs/41/result":
            receipts.append(json.loads(request.content))
            if len(receipts) == 1:
                raise httpx.ReadTimeout("Hub result acknowledgement was lost", request=request)
        else:
            raise AssertionError(request.url.path)
        return httpx.Response(200, json={})

    async def run_before_and_after_restart():
        async with workflow.autoloop.connect("http://127.0.0.1", KEYS, transport=httpx.MockTransport(hub)):
            with pytest.raises(httpx.ReadTimeout):
                await WorkflowWorker(workflow).execute(job, asyncio.Event())
        assert workflow.store.turn(turn["id"])["state"] == "decision"

        restarted = Workflow(tmp_path, app.state.model_gateway)
        restarted.store.recover_interrupted_turns()
        async with restarted.autoloop.connect("http://127.0.0.1", KEYS, transport=httpx.MockTransport(hub)):
            await WorkflowWorker(restarted).execute(job, asyncio.Event())

    asyncio.run(run_before_and_after_restart())
    assert len(model.calls) == len(starts) == 1
    assert len(receipts) == 2 and receipts[0] == receipts[1]
    assert receipts[1]["ask"][0]["about"] == turn["id"]


@pytest.mark.parametrize("corrupt_result", (False, True))
def test_restart_of_running_turn_without_valid_result_needs_approval(tmp_path, corrupt_result):
    app, model = make_workspace(tmp_path)
    turn = approved_item(app.state.workflow)
    assert app.state.workflow.store.start_approved_turn(turn["id"], 42)
    if corrupt_result:
        app.state.workflow.store.save_candidate(turn["id"], {"unexpected": "invalid"})
    restarted = Workflow(tmp_path, app.state.model_gateway)
    restarted.store.recover_interrupted_turns()
    assert restarted.store.linked_turn(42)["state"] == "failed"
    assert not restarted.store.pending_dispatch()
    assert not model.calls
