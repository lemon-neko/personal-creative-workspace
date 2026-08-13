from __future__ import annotations

import json
from pathlib import Path

from app.llm import LLMConfig, OpenAICompatibleClient
from app.workspace import create_item


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


def test_disabled_client_without_complete_config() -> None:
    client = OpenAICompatibleClient(LLMConfig("", "", ""))
    assert client.enabled is False


def test_polish_uses_compatible_chat_completions(monkeypatch) -> None:
    payload = json.dumps(
        {
            "title": "如果想法也会迷路",
            "markdown": "## 写 / Writing\n\n候选正文。",
            "image_suggestions": ["开头放一张发呆猫咪"],
        },
        ensure_ascii=False,
    )
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse(payload)

    monkeypatch.setattr("app.llm.httpx.post", fake_post)
    client = OpenAICompatibleClient(
        LLMConfig("https://provider.example/v1", "secret", "model-name"),
    )

    result = client.polish(title="原题", body="原文", mode="essay")

    assert captured["url"] == "https://provider.example/v1/chat/completions"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer secret"
    assert result.title == "如果想法也会迷路"
    assert result.mode == "essay"
    assert result.image_suggestions == ("开头放一张发呆猫咪",)


def test_invalid_model_payload_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.llm.httpx.post",
        lambda *_args, **_kwargs: FakeResponse("not json"),
    )
    client = OpenAICompatibleClient(
        LLMConfig("https://provider.example/v1", "secret", "model"),
    )

    try:
        client.polish(title="原题", body="原文", mode="auto")
    except ValueError as error:
        assert "JSON" in str(error)
    else:
        raise AssertionError("invalid payload must fail")


def test_general_summary_does_not_use_publishing_style(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_post(_url, **kwargs):
        captured["messages"] = kwargs["json"]["messages"]
        captured["temperature"] = kwargs["json"]["temperature"]
        return FakeResponse("## 本周概览\n\n直接汇总。")

    monkeypatch.setattr("app.llm.httpx.post", fake_post)
    client = OpenAICompatibleClient(
        LLMConfig("https://provider.example/v1", "secret", "model"),
    )
    item = create_item(tmp_path, body="一条普通记录。")

    result = client.summarize([item])

    assert "本周概览" in result
    assert "不使用中英双标题" in captured["messages"][0]["content"]
    assert "羽白的幻想栈" not in captured["messages"][0]["content"]
    assert captured["temperature"] == 0.2


def test_knowledge_analysis_validates_model_ids(monkeypatch, tmp_path: Path) -> None:
    item = create_item(tmp_path, body="一条关于记忆的记录。")
    payload = json.dumps(
        {
            "suggestions": [
                {
                    "item_id": item.id,
                    "subjects": ["技术"],
                    "concepts": ["记忆系统"],
                    "relations": [],
                },
            ],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        "app.llm.httpx.post",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )
    client = OpenAICompatibleClient(
        LLMConfig("https://provider.example/v1", "secret", "model"),
    )

    suggestions = client.analyze_knowledge([item], [item], ["技术", "哲学"])

    assert suggestions[0].item_id == item.id
    assert suggestions[0].concepts == ("记忆系统",)
