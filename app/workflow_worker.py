"""Deliver approved turns and execute jobs claimed from Autoloop."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import httpx

from app.atomic import atomic_write_text
from app.deepseek_harness import DeepSeekHarnessClient
from app.model_gateway import ModelProvider
from app.workflow import Workflow
from app.workflow_hub import EVENT_TYPE
from app.workflow_store import ANSWER_REFERENCE, identifier


def answer_body(turn):
    if turn["has_answer"]:
        return {"text": ANSWER_REFERENCE + turn["id"]}
    return {"choice": turn["choice"] or 0}


def answer_matches(turn, card):
    body = answer_body(turn)
    return card.get("choice") == body.get("choice") and card.get("answer", card.get("text")) == body.get("text")


class WorkflowWorker:
    def __init__(self, workflow: Workflow):
        self.workflow = workflow
        self.store = workflow.store
        self.autoloop = workflow.autoloop

    async def dispatch(self):
        for turn in self.store.pending_dispatch():
            try:
                if turn["card"]:
                    reply = await self.autoloop.request(f"/v1/cards/{turn['card']}/answer", method="POST", body=answer_body(turn))
                    if not reply.get("changed"):
                        snapshot = await self.autoloop.request("/v1/state")
                        previous = next((c for c in snapshot["recentCards"] if c["id"] == turn["card"]), None)
                        if not previous or not answer_matches(turn, previous):
                            self.store.fail_dispatch(turn["id"])
                else:
                    reply = await self.autoloop.request("/v1/events", method="POST", role="source", body={
                        "id": turn["id"], "type": EVENT_TYPE, "subject": turn["item_id"],
                    })
                    if not reply.get("routed") and not reply.get("duplicate"):
                        self.store.fail_dispatch(turn["id"])
                self.store.mark_delivered(turn["id"])
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 409 and turn["card"]:
                    snapshot = await self.autoloop.request("/v1/state")
                    previous = next((c for c in snapshot["recentCards"] if c["id"] == turn["card"]), None)
                    if previous and answer_matches(turn, previous) and previous["state"] != "closed":
                        self.store.mark_delivered(turn["id"])
                        continue
                if error.response.status_code < 500:
                    self.store.fail_dispatch(turn["id"])
                else:
                    raise

    def job_turn(self, job):
        run = job["run"]
        if turn := self.store.linked_turn(run):
            return turn
        context = job["context"]
        for answer in context.get("answers", ()):
            turn = self.store.approved_card_turn(answer["card"])
            if turn and answer_matches(turn, answer):
                return turn
        for event in context.get("events", ()):
            if event["type"] == EVENT_TYPE and event["source"] == "workbench":
                turn = self.store.turn(event["id"])
                if turn and turn["item_id"] == event["subject"] and turn["state"] in ("approved", "cancelled"):
                    return turn
        return self.store.create_pending_turn(run, job["rule"]["name"])

    def model_result(self, preview, cancelled, session_id, turn_id):
        client = self.workflow.gateway.client
        try:
            candidate = self.workflow.gateway.agent_candidate(
                preview["material"], answered=preview["answered"], cancelled=cancelled.is_set, session_id=session_id,
            )
        finally:
            if isinstance(client, DeepSeekHarnessClient) and (events := client.telemetry_for(session_id)):
                with suppress(OSError):
                    self.store.save_telemetry(turn_id, events)
        stats = client.last_usage
        usage = {
            native: stats[source] for source, native in (
                ("prompt_tokens", "input"), ("completion_tokens", "output"), ("prompt_cache_hit_tokens", "cached"),
            ) if source in stats
        }
        if usage:
            candidate["_usage"] = usage
        return candidate

    async def execute(self, job, cancelled: asyncio.Event):
        turn = self.job_turn(job)
        turn_id, state, run, token = turn["id"], turn["state"], job["run"], job["token"]
        if state == "approved":
            start = {"session": f"dsh-{turn_id}"} if self.workflow.gateway.provider == ModelProvider.DEEPSEEK_HARNESS else {}
            await self.autoloop.request(f"/v1/runs/{run}/started", method="POST", token=token, body=start)
            if self.store.start_approved_turn(turn_id, run):
                try:
                    previous = self.store.turn(turn["previous_id"]) if turn["previous_id"] else None
                    preview = self.workflow.preview(turn["item_id"], turn["objective"], previous, turn["choice"], self.store.private_answer(turn))
                    if cancelled.is_set() or preview["fingerprint"] != turn["fingerprint"] or not self.workflow.gateway.enabled:
                        raise ValueError("模型确认已失效")
                    candidate = await asyncio.to_thread(self.model_result, preview, cancelled, start.get("session"), turn_id)
                    stopped = cancelled.is_set() or self.store.turn(turn_id)["state"] == "cancelled"
                    state = "cancelled" if stopped else "draft" if "draft" in candidate else "decision"
                    if state != "cancelled":
                        self.store.save_candidate(turn_id, candidate)
                except (ValueError, TypeError, RuntimeError, OSError, httpx.HTTPError):
                    state = "cancelled" if cancelled.is_set() else "failed"
                state = self.store.finish_running_turn(turn_id, state)
            else:
                state = self.store.turn(turn_id)["state"]
        if state in ("approval", "decision"):
            options = ["确认后运行", "暂不运行"]
            if state == "decision":
                options = [f"选项 {i+1}" for i in range(len(self.store.payload(turn_id)["options"]))]
            result = {"outcome": "done", "summary": "等待人工确认", "ask": [{
                "title": "待你决定" if state == "decision" else "待确认模型外发",
                "text": "请在羽白工作台查看", "options": options, "about": turn_id, "key": turn_id,
            }]}
        elif state in ("draft", "accepted"):
            result = {"outcome": "done", "summary": "产物待人工验收"}
        elif state == "cancelled" or cancelled.is_set():
            result = {"outcome": "cancelled"}
        else:
            # Retry is a new, explicitly approved model turn. Never replay a timed-out call.
            result = {"outcome": "done", "summary": "模型结果不可确认，请在工作台重新预览"}
        if state in ("decision", "draft", "accepted") and (usage := self.store.payload(turn_id).get("_usage")):
            result["usage"] = usage
        await self.autoloop.request(f"/v1/runs/{run}/result", method="POST", token=token, body=result)

    async def run(self):
        claim_path = self.store.root / "claim"
        claim = claim_path.read_text().strip() if claim_path.is_file() else identifier()
        atomic_write_text(claim_path, claim)
        current = None
        while True:
            try:
                await self.dispatch()
                if current is None:
                    reply = await self.autoloop.request("/v1/work", role="worker", params={"claim": claim, "wait": 1, "capacity": 1})
                    current = reply["job"]
                if current:
                    cancelled = asyncio.Event()

                    async def heartbeat():
                        while True:
                            try:
                                reply = await self.autoloop.request("/v1/work", role="worker", params={
                                    "claim": identifier(), "running": current["run"], "capacity": 0,
                                })
                                if current["run"] in reply["cancel"]:
                                    cancelled.set()
                            except (RuntimeError, httpx.HTTPError):
                                pass
                            await asyncio.sleep(1)

                    task = asyncio.create_task(heartbeat())
                    try:
                        await self.execute(current, cancelled)
                        current = None
                        claim = identifier()
                        atomic_write_text(claim_path, claim)
                    finally:
                        cancelled.set()
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                self.workflow.ready = True
                self.workflow.error = ""
            except (RuntimeError, OSError, ValueError, httpx.HTTPError) as error:
                self.workflow.ready = False
                self.workflow.error = "Autoloop 暂不可用，保留已确认的任务并等待重连"
                # An expired claim must not prevent recovery of the next native job.
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 409):
                    current = None
                    claim = identifier()
                    atomic_write_text(claim_path, claim)
                await asyncio.sleep(1)
