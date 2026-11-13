from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
