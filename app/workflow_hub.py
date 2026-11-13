"""Authenticated HTTP transport to the local Autoloop Hub."""

import json
import os
from contextlib import asynccontextmanager

from pathlib import Path

import httpx

HUB_URL = "http://127.0.0.1:8768"
EVENT_TYPE = "workbench.approved"
RULE = "工作台任务"


def plugin_environment(home: Path) -> dict[str, str]:
    return {**{key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG") if key in os.environ},
            "AGENT_AUTOLOOP_HOME": str(home)}


class AutoloopClient:
    def __init__(self):
        self._http: httpx.AsyncClient | None = None
        self._keys: dict[str, str] = {}

    @property
    def connected(self):
        return self._http is not None

    @asynccontextmanager
    async def connect(self, base_url, keys, *, transport=None):
        async with httpx.AsyncClient(base_url=base_url, timeout=5, trust_env=False, transport=transport) as http:
            self._http = http
            self._keys = keys
            try:
                yield
            finally:
                self._http = None
                self._keys = {}

    async def request(self, path, *, method="GET", role="owner", token=None, body=None, params=None):
        if self._http is None:
            raise RuntimeError("Autoloop 当前离线")
        credential = self._keys[role] if token is None else token
        response = await self._http.request(
            method, path, headers={"Authorization": f"Bearer {credential}"}, json=body, params=params,
        )
        response.raise_for_status()
        return response.json()

    @asynccontextmanager
    async def facts(self, after):
        if self._http is None:
            raise RuntimeError("Autoloop 当前离线")
        async with self._http.stream(
            "GET", "/v1/stream", params={"after": after},
            headers={"Authorization": f"Bearer {self._keys['owner']}"},
            timeout=httpx.Timeout(5, read=None),
        ) as response:
            response.raise_for_status()
            yield self._read_facts(response)

    @staticmethod
    async def _read_facts(response):
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                yield json.loads(line[6:])
