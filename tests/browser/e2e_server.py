"""Isolated ASGI applications used by Playwright acceptance tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.llm import LLMConfig, OpenAICompatibleClient
from app.main import create_app
from app.mobile_main import create_mobile_app


DATA_ROOT = Path(os.environ["E2E_DATA_ROOT"]).resolve()
CONTENT_ROOT = DATA_ROOT / "content"


class DeterministicAssistantClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(LLMConfig("http://127.0.0.1:9999/v1", "", "browser-fake"))

    def assistant_candidate(self, material: str) -> dict:
        payload = json.loads(material)
        source_id = payload["allowed_sources"][0]["id"]
        self._state.usage = {"prompt_tokens": 120, "completion_tokens": 80}
        return {
            "user_intent_summary": "判断当前最先推进的事项",
            "assistant_summary": "先完成一个可以验证的小闭环。",
            "priority_title": "完成最小可靠性闭环",
            "reason": "它会同时产生学习反馈和可展示证据。",
            "steps": ["明确验收条件", "完成最小实现", "运行测试并记录结果"],
            "success_criteria": "形成一个测试通过且可以复盘的提交。",
            "evidence": [{"source_id": source_id, "reason": "当前活跃来源"}],
            "assumptions": ["今天有一段连续时间"],
            "clarifying_question": "",
            "suggested_actions": [
                {
                    "type": "create-thought",
                    "title": "记录可靠性闭环",
                    "body": "记录验收条件、实现结果和下一次改进。",
                    "skill_id": "",
                    "priority": 3,
                }
            ],
        }


desktop_app = create_app(
    content_root=CONTENT_ROOT,
    data_root=DATA_ROOT,
    enable_scheduler=False,
    llm_client=DeterministicAssistantClient(),
    enforce_security=False,
)
mobile_app = create_mobile_app(
    data_root=DATA_ROOT,
    content_root=CONTENT_ROOT,
    enforce_security=False,
)
