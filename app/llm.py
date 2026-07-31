"""Configurable OpenAI-compatible style polishing and weekly synthesis."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.content import ContentItem


STYLE_GUIDE = """
你是“羽白的幻想栈”的编辑。文章必须忠于原意，不伪造经历或事实。
核心风格：
- 清楚，但不要端着；有趣来自克制吐槽、反差和偶尔抽象的比喻。
- 多用短段落、设问、自问自答和加粗的一句话判断。
- 随想结构：经历 → 联想 → 抽象主题 → 回到自己。
- 说明结构：问题 → 概念演进 → 核心判断 → 写在最后。
- 章节标题使用“中文短词 / English”形式。
- 可以建议生活照片或表情包的位置，但不能声称图片已经存在。
- 结尾保留“写在最后”，不堆热梗，不把严肃观点写成段子。
""".strip()


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            base_url=os.getenv("LLM_BASE_URL", "").strip(),
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            model=os.getenv("LLM_MODEL", "").strip(),
        )


@dataclass(frozen=True)
class PolishResult:
    title: str
    markdown: str
    image_suggestions: tuple[str, ...]
    mode: str


class StyleClient(Protocol):
    @property
    def enabled(self) -> bool: ...

    def polish(self, *, title: str, body: str, mode: str) -> PolishResult: ...

    def summarize(self, items: Sequence[ContentItem]) -> str: ...


class OpenAICompatibleClient:
    """Small chat-completions client with no provider-specific dependency."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        timeout: float = 45,
    ) -> None:
        self.config = config or LLMConfig.from_env()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _chat(self, system: str, user: str) -> str:
        if not self.enabled:
            raise RuntimeError("尚未配置兼容模型")
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "temperature": 0.7,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("模型返回格式不完整") from error
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型没有返回可用内容")
        return content.strip()

    @staticmethod
    def _json_object(text: str) -> dict:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as error:
            raise ValueError("模型没有返回约定的 JSON") from error
        if not isinstance(data, dict):
            raise ValueError("模型返回内容必须是对象")
        return data

    def polish(self, *, title: str, body: str, mode: str) -> PolishResult:
        mode_labels = {
            "auto": "根据原文自动判断",
            "essay": "观察随想",
            "explainer": "概念拆解",
        }
        if mode not in mode_labels:
            raise ValueError("润色模式无效")
        raw = self._chat(
            STYLE_GUIDE,
            f"""表达模式：{mode_labels[mode]}

标题：{title}

原文：
{body}

仅返回 JSON：
{{
  "title": "候选标题",
  "markdown": "完整 Markdown 候选稿",
  "image_suggestions": ["在何处放什么类型的图片或表情包"]
}}""",
        )
        data = self._json_object(raw)
        candidate_title = str(data.get("title", "")).strip()
        markdown = str(data.get("markdown", "")).strip()
        suggestions = data.get("image_suggestions", [])
        if not candidate_title or not markdown:
            raise ValueError("模型返回的标题或正文为空")
        if not isinstance(suggestions, list):
            suggestions = []
        return PolishResult(
            title=candidate_title[:120],
            markdown=markdown,
            image_suggestions=tuple(str(item).strip() for item in suggestions if str(item).strip())[:6],
            mode=mode,
        )

    def summarize(self, items: Sequence[ContentItem]) -> str:
        material = "\n\n".join(
            f"- {item.created_at.isoformat()} | {item.title}\n  {item.body[:1600]}"
            for item in items
        )
        return self._chat(
            STYLE_GUIDE,
            f"""请把下面一周的记录整理成 Markdown 周回顾。
提炼重复主题、记录之间的关联、尚未解决的矛盾和下周值得探索的问题。
不要覆盖、评判或伪造原始经历。使用“本周 / This Week”“线索 / Threads”
“还没想明白 / Open Questions”“写在最后 / Afterword”等克制的小节。

记录：
{material}""",
        )
