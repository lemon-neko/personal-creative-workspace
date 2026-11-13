"""Workflow use cases shared by the HTTP routes and Worker."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path

from app.deepseek_harness import DEFAULT_DSH, ENDPOINT, MODEL, DeepSeekHarnessClient, credential
from app.llm import LLMConfig
from app.model_gateway import AGENT_INSTRUCTION, POLICIES, ModelGateway, ModelProvider, ModelTaskKind, estimate_tokens
from app.workflow_hub import AutoloopClient
from app.workflow_store import WorkflowStore


class WorkflowConfigurationError(ValueError):
    """The configured model backend cannot be initialized safely."""


class Workflow:
    def __init__(self, root: Path, gateway):
        self.store = WorkflowStore(root)
        self.gateway = gateway
        settings = self.store.root / "harness.json"
        if settings.is_file():
            try:
                config = json.loads(settings.read_text())
                if not isinstance(config, dict):
                    raise ValueError("需要 JSON 对象")
                executable = Path(config.get("executable", DEFAULT_DSH))
                model = config.get("model", MODEL)
                if not isinstance(model, str):
                    raise ValueError("模型名必须是字符串")
            except (OSError, TypeError, ValueError) as error:
                raise WorkflowConfigurationError("执行后端配置无效") from error
            client = DeepSeekHarnessClient(LLMConfig(ENDPOINT, credential(), model), executable)
            self.gateway = ModelGateway(root, client)
        self.autoloop = AutoloopClient()
        self.ready = False
        self.error = "正在启动插件"
        self.control_traces = OrderedDict()

    @property
    def execution_backend(self):
        return {
            "name": "DeepSeek Harness" if self.gateway.provider == ModelProvider.DEEPSEEK_HARNESS else "模型网关",
            "model": self.gateway.config.model,
            "enabled": self.gateway.enabled,
        }

    def preview(self, item_id, objective, previous=None, choice=None, answer_text=""):
        item = self.store.item(item_id)
        if not item:
            raise KeyError(item_id)
        if self.store.item_archived(item_id):
            raise ValueError("此工作项已归档，请新建工作项")
        objective = objective.strip()
        if not objective or len(objective) > 4000:
            raise ValueError("任务目标须为 1–4000 字")
        payload = {"title": item["title"], "objective": objective, "role": "research"}
        decision_turn, selected = previous, choice
        reply = (answer_text or "").strip()
        if len(reply) > 4000 or (reply and choice is not None):
            raise ValueError("请选择一个选项或填写 4000 字以内的文字")
        while decision_turn and decision_turn["state"] in ("failed", "cancelled"):
            if decision_turn["has_answer"]:
                selected, reply = None, self.store.private_answer(decision_turn)
            elif decision_turn["choice"] is not None:
                selected, reply = decision_turn["choice"], ""
            decision_turn = self.store.turn(decision_turn["previous_id"]) if decision_turn["previous_id"] else None
        if decision_turn and decision_turn["state"] == "decision":
            decision = self.store.payload(decision_turn["id"])
            if not reply and selected not in range(len(decision["options"])):
                raise ValueError("请选择一个有效选项")
            payload["decision"] = {"question": decision["question"], "answer": reply or decision["options"][selected]}
        elif reply:
            raise ValueError("此工作项没有可填写文字的决策")
        material = json.dumps(payload, ensure_ascii=False, indent=2)
        wire = AGENT_INSTRUCTION + "\n" + material
        gateway = self.gateway
        fingerprint = hashlib.sha256(json.dumps([
            item_id, previous["id"] if previous else "", choice, gateway.provider.value,
            gateway.config.base_url, gateway.config.model, wire,
        ]).encode()).hexdigest()
        policy = POLICIES[ModelTaskKind.AGENT]
        if estimate_tokens(wire) > policy.max_input_tokens:
            raise ValueError("任务材料超过模型输入上限")
        return {"fingerprint": fingerprint, "instruction": AGENT_INSTRUCTION, "material": material,
                "model": gateway.config.model, "provider": self.execution_backend["name"],
                "output_limit": policy.max_output_tokens, "answered": "decision" in payload}

    def approve(self, item_id, objective, previous, card, choice, fingerprint, answer_text=""):
        preview = self.preview(item_id, objective, previous, choice, answer_text)
        if not self.gateway.enabled or preview["fingerprint"] != fingerprint:
            raise ValueError("模型不可用或预览已失效，请重新确认")
        self.store.save_approval(item_id, objective, previous, card, choice, fingerprint, answer_text)
