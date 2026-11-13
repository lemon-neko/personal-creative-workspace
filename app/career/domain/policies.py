from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class LLMDisclosure:
    purpose: str
    source_ids: tuple[str, ...]
    outbound_text: str
    target: str
