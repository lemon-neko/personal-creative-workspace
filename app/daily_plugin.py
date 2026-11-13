"""Launch and authenticate the local Super Productivity Web service."""

import asyncio
import hashlib
import hmac
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from app.plugin_packages import verify_packages
from app.plugin_paths import DAILY_ORIGIN, WORKBENCH_ORIGIN
from app.process_logs import ProcessLogs
from app.process_supervisor import SetupError, child_process, process_environment

HEALTH_ENV = "YUBAI_WEB_HEALTH_SECRET"
CHALLENGE = "x-yubai-web-challenge"
PROOF = "x-yubai-web-proof"


def health_proof(secret: str, challenge: str) -> str:
    return hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()


async def daily_available(secret: str) -> bool:
    challenge = secrets.token_hex(16)
    try:
        async with httpx.AsyncClient(timeout=1, trust_env=False) as http:
            response = await http.head(DAILY_ORIGIN, headers={CHALLENGE: challenge})
    except httpx.HTTPError:
        return False
    ancestors = [
        part.strip().split() for part in response.headers.get("content-security-policy", "").split(";")
        if part.strip() and part.strip().split()[0] == "frame-ancestors"
    ]
    proof = response.headers.get(PROOF, "")
    return (
        response.status_code == 200
        and ancestors == [["frame-ancestors", WORKBENCH_ORIGIN]]
        and hmac.compare_digest(proof.encode(), health_proof(secret, challenge).encode())
    )


class DailyWeb:
    def __init__(self, root: Path, logs: ProcessLogs):
        self.root = root
        self.logs = logs
        self._secret = ""

    async def available(self) -> bool:
        secret = self._secret
        return bool(secret and await daily_available(secret) and self._secret == secret)

    @asynccontextmanager
    async def launch(self):
        try:
            await asyncio.to_thread(verify_packages, self.root, package="web")
        except (OSError, ValueError) as error:
            detail = str(error) if isinstance(error, ValueError) else "无法读取 Super Productivity 包"
            raise SetupError(detail) from error
        self._secret = secrets.token_hex(32)
        try:
            async with child_process(
                (sys.executable, "-m", "app.plugin_web", str(self.root / "web")),
                env=process_environment() | {HEALTH_ENV: self._secret}, logs=self.logs, health=self.available,
            ) as service:
                yield service
        finally:
            self._secret = ""
