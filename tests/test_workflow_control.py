import json

import pytest

from app import workflow_store as store
from app.workflow_control import invalidate, trace
from tests.test_workflow_plugins import make_workspace


def fact(seq, kind, *changes):
    return {
        "seq": seq, "at": seq * 1000, "type": kind,
        "changes": [{"table": table, "key": str(key), "row": row} for table, key, row in changes],
    }


def test_trace_uses_final_projection_of_each_fact_and_preserves_unknown(tmp_path):
    config = {"rules": [{"name": "review", "cwd": "~/project", "prompt": "not a browser field"}],
              "agents": {"agent": {"worker": "worker"}}}
    queued = {"id": 1, "rule": "review", "grp": "group", "lane": "one", "agent": "agent",
              "state": "queued", "rules_version": 1, "attempts": 0}
    claimed = queued | {"state": "claimed", "claimed_at": "2026-01-01T00:00:01Z", "claim": "private token"}
    event = {"id": 11, "source": "test", "type": "input", "summary": "event token=fixture-secret-123", "detail": "private body"}
    card = {"id": 31, "kind": "ask", "state": "open", "title": "decision", "run_id": 1}
    facts = [
        fact(1, "rules", ("config", "rules", {"value": config})),
        fact(2, "ingest", ("runs", 1, queued), ("events", 11, event),
             ("run_events", "1:11", {"run_id": 1, "event_id": 11})),
        fact(3, "claimNext", ("runs", 1, claimed)),
        fact(4, "started", ("runs", 1, claimed | {"link": "javascript:alert(1)"})),
        fact(5, "tick", ("runs", 1, claimed | {"state": "unknown"})),
    ]
    unknown = trace(1, facts)
    assert unknown["state"] == "unknown" and unknown["usage"] is None
    assert [step["kind"] for step in unknown["timeline"]][-2:] == ["start", "unknown"]
    assert unknown["timeline"][1]["config"]["cwd"] == "~/project"
    assert all(value not in json.dumps(unknown) for value in ("private token", "private body", "not a browser field", "javascript:"))
    assert "fixture-secret-123" not in json.dumps(unknown)
    assert unknown["frames"][-1]["run"]["state"] == "unknown"
    facts += [
        fact(6, "finish", ("runs", 1, claimed), ("runs", 1, claimed | {"state": "done", "usage": '{"output":0}'}),
             ("cards", 31, card)),
        fact(7, "answer", ("cards", 31, card | {"state": "decided", "answer_event": 12, "decided_at": "later",
                                               "choice": 0, "options": '["selected","other"]'}),
             ("run_events", "2:12", {"run_id": 2, "event_id": 12})),
    ]
    result = trace(1, facts)
    assert result["cards"][0]["following"] == [2]
    receipts = [step for step in result["timeline"] if step["kind"] == "receipt"]
    assert len(receipts) == 1 and receipts[0]["outcome"] == "done" and receipts[0]["usage"] == {"output": 0}
    assert next(step for step in result["timeline"] if step["kind"] == "answer")["selected"] == "selected"
    workflow = make_workspace(tmp_path)[0].state.workflow
    workflow.control_traces[1] = "stale"
    assert invalidate(workflow, facts[-1]) == {"runs": [1, 2], "tables": ["cards", "run_events"]}
    assert 1 not in workflow.control_traces


def test_failed_private_answer_write_cannot_approve_or_leave_a_file(tmp_path, monkeypatch):
    workflow = make_workspace(tmp_path)[0].state.workflow
    item_id = workflow.store.handoff("manual:test", "Test")
    previous = store.identifier()
    workflow.store._write("INSERT INTO workflow_turns(id,item_id,state) VALUES (?,?,'decision')", (previous, item_id))
    results = workflow.store.root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{previous}.json").write_text(json.dumps({"question": "question", "options": ["a", "b"]}))
    old = workflow.store.turn(previous)
    fingerprint = workflow.preview(item_id, "objective", old, answer_text="free text")["fingerprint"]

    def broken_write(path, text):
        path.write_text(text)
        raise OSError("disk error")

    monkeypatch.setattr(store, "atomic_write_text", broken_write)
    with pytest.raises(OSError, match="disk error"):
        workflow.approve(item_id, "objective", old, 1, None, fingerprint, "free text")
    assert [turn["id"] for turn in workflow.store.turns(item_id)] == [previous]
    assert not list(results.glob("*.answer.txt"))


def test_archived_item_keeps_history_and_same_source_can_start_fresh(tmp_path):
    from fastapi.testclient import TestClient

    from app.atomic import atomic_write_text
    from app.plugins import WORKBENCH_ORIGIN
    from tests.test_workflow_plugins import csrf

    app, _ = make_workspace(tmp_path)
    workflow = app.state.workflow
    old = workflow.store.handoff("sp:test", "Test")
    atomic_write_text(workflow.store.root / "workflow-archive.json", json.dumps({
        "time": "2026-11-12T05:00:00Z", "items": [old],
    }))
    assert workflow.store.active_items() == []
    with TestClient(app, base_url=WORKBENCH_ORIGIN) as client:
        headers = csrf(client)
        response = client.get(f"/workflow/items/{old}")
        assert "此工作项已归档" in response.text
        assert client.post(f"/workflow/items/{old}/preview", data={"objective": "旧事项"}, headers=headers).status_code == 422
        route = "/workflow/handoff"
        task = {"id": "test", "title": "Test"}
        url = client.post(route, json=task, headers=headers).json()["url"]
        assert client.post(route, json=task, headers=headers).json()["url"] == url
        [active] = workflow.store.active_items()
        assert active["id"] != old and url.endswith(active["id"])


def test_event_stream_resumes_and_filters_autoloop_facts(tmp_path):
    import asyncio

    import httpx

    from app.workflow_control import stream_events

    workflow = make_workspace(tmp_path)[0].state.workflow
    update = fact(
        13, "ingest", ("keys", "owner", {"secret": "private-value"}),
        ("runs", 42, {"id": 42, "claim": "private-claim"}),
    )

    def hub(request):
        assert request.url.path == "/v1/stream"
        assert request.url.params["after"] == "12"
        assert request.headers["authorization"] == "Bearer local-test-owner"
        return httpx.Response(200, text=f"id: 13\nevent: fact\ndata: {json.dumps(update)}\n\n")

    async def read():
        async with workflow.autoloop.connect(
            "http://127.0.0.1", {"owner": "local-test-owner"}, transport=httpx.MockTransport(hub),
        ):
            return [frame async for frame in stream_events(workflow, 12)]

    connected, event, disconnected = asyncio.run(read())
    assert "event: connected" in connected and "event: disconnected" in disconnected
    assert event.startswith("id: 13\nevent: fact\n")
    assert json.loads(event.split("data: ")[1]) == {"runs": [42], "tables": ["runs"]}
