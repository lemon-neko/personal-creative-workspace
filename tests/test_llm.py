from __future__ import annotations

import json

from app.llm import LLMConfig, OpenAICompatibleClient


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
