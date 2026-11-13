"""Run the installed DeepSeek Harness against one approved model request."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import selectors
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import yaml

from app.llm import LLMConfig, OpenAICompatibleClient

DEFAULT_DSH = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")
ENDPOINT = "https://api.deepseek.com/anthropic"
MODEL = "deepseek-flash"
SESSION = "workbench"
PATCH = """\
- id: persistent-bash
  disabled: true
- id: persistent-pwsh
  disabled: true
- id: tool-fs
  disabled: true
- id: tool-working-directory
  disabled: true
- id: mcp-resources
  disabled: true
- id: session-log-deepseek
  disabled: true
- id: plugin-package-inventory-deepseek
  disabled: true
- id: deepseek-llm-api-extensions
  disabled: true
"""


def credential():
    if key := os.getenv("DEEPSEEK_API_KEY", "").strip():
        return key
    try:
        document = yaml.safe_load((Path.home() / ".dsh" / ".credentials.yaml").read_text())
        key = document["refs"]["DEEPSEEK_API_KEY"]
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        return ""
    return key if isinstance(key, str) and key.startswith("sk-") else ""


class DeepSeekHarnessClient(OpenAICompatibleClient):
    def __init__(self, config: LLMConfig, executable: Path = DEFAULT_DSH):
        super().__init__(config, timeout=70)
        self.executable = executable

    @property
    def enabled(self):
        return self.config.enabled and self.executable.is_file() and os.access(self.executable, os.X_OK)

    def telemetry_for(self, session_id):
        if getattr(self._state, "telemetry_session", None) != session_id:
            return []
        return list(getattr(self._state, "telemetry", []))

    def agent_candidate(self, instruction, material, *, cancelled=lambda: False, session_id=SESSION):
        self._state.telemetry_session = session_id
        self._state.telemetry = []
        if not self.enabled:
            raise RuntimeError("DeepSeek Harness 或 API Key 尚未配置")
        self._state.usage = {}
        limit = int(getattr(self._state, "max_tokens", 2500))
        usage = {}
        try:
            with (
                tempfile.TemporaryDirectory(prefix="pcw-dsh-") as folder,
                approved_request(self.config, instruction, material, limit, usage, cancelled) as (url, token),
            ):
                patch = Path(folder) / "no-tools.yml"
                patch.write_text(PATCH)
                env = {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG") if key in os.environ}
                env.update(
                    HOME=folder,
                    DSH_HOME=folder,
                    DSH_SYSTEM_PROMPT=instruction,
                    DEEPSEEK_BASE_URL=url,
                    DEEPSEEK_API_KEY=token,
                )
                reply = run_sdk(
                    self.executable, folder, patch, env, self.config.model, limit, material,
                    cancelled, session_id, self._state.telemetry,
                )
                return self._json_object(reply)
        finally:
            self._state.usage = usage.copy()


def run_sdk(executable, folder, patch, env, model, limit, material, cancelled, session_id, telemetry):
    command = [str(executable), "--profile", "sdk-minimal", "--patch", str(patch)]
    finish, final_text = {}, ""
    end = time.monotonic() + 95
    with (
        subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         cwd=folder, env=env, start_new_session=True) as child,
        selectors.DefaultSelector() as selector,
    ):
        selector.register(child.stdout, selectors.EVENT_READ)
        pending = bytearray()

        def request(sequence, method, params=None):
            nonlocal finish, final_text
            if cancelled():
                raise RuntimeError("DeepSeek Harness 运行已停止")
            msg = {"jsonrpc": "2.0", "id": sequence, "method": method}
            if params is not None:
                msg["params"] = params
            child.stdin.write(json.dumps(msg).encode() + b"\n")
            child.stdin.flush()
            while time.monotonic() < end and not cancelled():
                if not selector.select(timeout=0.25):
                    continue
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending.extend(chunk)
                if len(pending) > 1_000_000:
                    raise RuntimeError("DeepSeek Harness SDK 响应超过大小限制")
                while (offset := pending.find(b"\n")) >= 0:
                    response = json.loads(pending[:offset])
                    del pending[:offset + 1]
                    if response.get("method") == "session.event":
                        event = response["params"]
                        if event["sessionId"] == session_id:
                            payload = event["event"]
                            if payload["type"] == "turn/end":
                                finish = payload["data"].get("reason") or {}
                                if len(telemetry) < 32:
                                    telemetry.append({
                                        "type": "agent.finish", "at": time.time_ns() // 1_000_000,
                                        "outcome": "completed" if finish.get("kind") == "completed" else "interrupted",
                                    })
                            elif payload["type"] == "assistant/message":
                                data = payload["data"]
                                content = data.get("message", data).get("content") or []
                                body = "".join(block["text"] for block in content
                                               if block.get("type") == "text" and isinstance(block.get("text"), str))
                                if body.strip():
                                    final_text = body
                    if response.get("id") == sequence:
                        if "result" not in response:
                            raise RuntimeError("DeepSeek Harness 未完成 SDK 请求")
                        return response["result"]
            raise RuntimeError("DeepSeek Harness 已停止、超时或提前退出")

        try:
            result = request(1, "initialize", {
                "cwd": folder, "provider": "deepseek-official", "model": model, "maxTokens": limit,
            })
            if result["serverInfo"]["name"] != "deepseek-harness-sdk-runtime":
                raise RuntimeError("DeepSeek Harness SDK 协议不兼容")
            telemetry.append({"type": "session.ready", "at": time.time_ns() // 1_000_000})
            request(2, "session/prompt", {"sessionId": session_id, "contentBlocks": [{"type": "text", "text": material}]})
            request(3, "session/wait", {"sessionId": session_id})
            request(4, "shutdown")
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("DeepSeek Harness SDK 响应无效") from error
        finally:
            with suppress(ProcessLookupError):
                child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()

    if finish.get("kind") != "completed":
        status = (finish.get("error") or {}).get("status")
        suffix = f"（HTTP {status}）" if type(status) is int and 400 <= status <= 599 else ""
        raise RuntimeError("DeepSeek Harness 未正常结束本轮" + suffix)
    if final_text:
        return final_text
    raise RuntimeError("DeepSeek Harness 未返回候选产物")


@contextmanager
def approved_request(config, instruction, material, limit, usage, cancelled):
    """Allow one request per approval. The child never receives the real credential."""
    token = secrets.token_urlsafe(32)
    accepted = threading.Lock()

    class Relay(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            received = self.headers.get("x-api-key") or self.headers.get("Authorization", "").removeprefix("Bearer ")
            if self.path != "/v1/messages" or not hmac.compare_digest(received.encode(), token.encode()):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 256_000:
                    raise ValueError
                self.connection.settimeout(10)
                data = json.loads(self.rfile.read(size))
                if data["model"] != config.model or data.get("tools") or data.get("stream") is not True:
                    raise ValueError
            except (ValueError, KeyError, TypeError, OSError):
                self.send_error(422)
                return
            if cancelled() or not accepted.acquire(blocking=False):
                self.send_error(409)
                return

            payload = {
                "model": config.model,
                "system": instruction,
                "messages": [{"role": "user", "content": material}],
                "max_tokens": limit,
                "thinking": {"type": "disabled"},
                "stream": True,
            }
            try:
                with httpx.Client(trust_env=False, timeout=70) as http, http.stream(
                    "POST", config.base_url.rstrip("/") + "/v1/messages",
                    headers={"x-api-key": config.api_key, "anthropic-version": "2023-06-01"}, json=payload,
                ) as response:
                    if not response.is_success:
                        self.send_error(response.status_code if 400 <= response.status_code <= 599 else 502)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for line in response.iter_lines():
                        if cancelled():
                            break
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            if event.get("type") == "message_delta":
                                stats = event.get("usage") or {}
                                for key, name in (
                                    ("input_tokens", "prompt_tokens"),
                                    ("output_tokens", "completion_tokens"),
                                    ("cache_read_input_tokens", "prompt_cache_hit_tokens"),
                                ):
                                    if type(stats.get(key)) is int and stats[key] >= 0:
                                        usage[name] = stats[key]
                                if "prompt_tokens" in usage:
                                    usage["prompt_tokens"] += usage.get("prompt_cache_hit_tokens", 0)
                        self.wfile.write(line.encode() + b"\n")
                        self.wfile.flush()
            except (ValueError, OSError, httpx.HTTPError):
                self.close_connection = True

    with ThreadingHTTPServer(("127.0.0.1", 0), Relay) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", token
        finally:
            server.shutdown()
            thread.join()
