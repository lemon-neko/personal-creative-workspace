import hashlib
import json
from collections.abc import Callable
from hmac import compare_digest

from app.agent_runtime.application.ports import Candidate, Decision, ModelPort
from app.agent_runtime.domain.exceptions import InputLimitError, PreviewError
from app.agent_runtime.domain.models import AgentRun, WorkspaceTask


class ModelExecutor:
    def __init__(self, model: ModelPort | None):
        self.model = model

    @property
    def enabled(self) -> bool:
        return self.model is not None and self.model.policy() is not None

    def preview(self, run: AgentRun, task: WorkspaceTask, decision: dict | None) -> dict | None:
        policy = self.model.policy() if self.model is not None else None
        if run.status != "planned" or self.model is None or policy is None or (decision and not decision["answer"]):
            return None
        payload = {"title": task.title, "objective": task.objective, "role": run.role_key}
        if decision:
            payload["decision"] = {"question": decision["question"], "answer": decision["answer"]}
        material = json.dumps(payload, ensure_ascii=False, indent=2)
        wire_text = policy.instruction + "\n" + material
        fingerprint = hashlib.sha256(json.dumps([
            run.id, task.revision, policy.provider, policy.endpoint, policy.model, wire_text,
        ]).encode()).hexdigest()
        return {
            "material": material, "instruction": policy.instruction, "fingerprint": fingerprint,
            "tokens": self.model.estimate_tokens(wire_text), "input_limit": policy.max_input_tokens,
            "output_limit": policy.max_output_tokens, "model": policy.model, "external": policy.provider == "external",
        }

    def confirm(
        self, run: AgentRun, task: WorkspaceTask, decision: dict | None, fingerprint: str,
    ) -> Callable[[], dict]:
        preview = self.preview(run, task, decision)
        model = self.model
        if model is None or not preview or not compare_digest(fingerprint.encode(), preview["fingerprint"].encode()):
            raise PreviewError("预览已失效，请刷新后重新确认。")
        if preview["tokens"] > preview["input_limit"]:
            raise InputLimitError("任务材料超过模型输入上限。")
        answer = decision["answer"] if decision else ""
        def call() -> dict:
            current = self.preview(run, task, decision)
            if not current or current["fingerprint"] != preview["fingerprint"]:
                raise PreviewError("预览已失效，请刷新后重新确认。")
            if current["tokens"] > current["input_limit"]:
                raise InputLimitError("任务材料超过模型输入上限。")
            return model.candidate(preview["material"], answered=bool(answer))

        return call

    @staticmethod
    def execute(task: WorkspaceTask, call: Callable[[], dict], *, answered: bool) -> Candidate | Decision:
        result = call()
        if isinstance(result, dict) and set(result) == {"draft"}:
            draft = result["draft"]
            if isinstance(draft, str) and 0 < len(draft.strip()) <= 16_000:
                return Candidate(f"# {task.title}\n\n> AI 候选产物，未核实；由作者验收。\n\n{draft.strip()}\n",
                                 "AI 候选；等待作者确认。")
        elif isinstance(result, dict) and not answered and set(result) == {"question", "options"}:
            question, options = result["question"], result["options"]
            if (isinstance(question, str) and 0 < len(question.strip()) <= 240
                and isinstance(options, list) and 2 <= len(options) <= 4
                and all(isinstance(option, str) and 0 < len(option.strip()) <= 100 for option in options)
                and len({option.strip() for option in options}) == len(options)):
                return Decision(question.strip(), [option.strip() for option in options])
        raise ValueError("模型未返回合规的候选产物或决策选项")
