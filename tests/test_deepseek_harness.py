"""Verify the real local Harness binary without billing or sending data outside loopback."""

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.deepseek_harness import MODEL, DeepSeekHarnessClient
from app.llm import LLMConfig


@contextmanager
def harness_provider(candidate):
    requests = []
    stats = {"input_tokens": 10, "output_tokens": 8, "cache_read_input_tokens": 5}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers["x-api-key"], data))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in (
                {"type": "message_start", "message": {
                    "id": "test", "type": "message", "role": "assistant", "model": MODEL, "content": [],
                    "stop_reason": None, "usage": {"input_tokens": 10, "output_tokens": 0},
                }},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {
                    "type": "text_delta", "text": json.dumps(candidate(data), ensure_ascii=False),
                }},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": stats},
                {"type": "message_stop"},
            ):
                self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.skipif(not os.getenv("WORKBENCH_E2E_DSH"), reason="requires installed DeepSeek Harness executable")
def test_harness_sends_one_approved_request_and_returns_native_result():
    with harness_provider(lambda _: {"draft": "示例产物"}) as (endpoint, requests):
        adapter = DeepSeekHarnessClient(
            LLMConfig(endpoint, "synthetic", MODEL), Path(os.environ["WORKBENCH_E2E_DSH"]),
        )
        with adapter.output_limit(120):
            assert adapter.agent_candidate("只返回 JSON", "虚构任务") == {"draft": "示例产物"}
        assert adapter.last_usage == {"prompt_tokens": 15, "completion_tokens": 8, "prompt_cache_hit_tokens": 5}
        telemetry = adapter.telemetry_for("workbench")
        assert [event["type"] for event in telemetry] == ["session.ready", "agent.finish"]
        assert telemetry[-1]["outcome"] == "completed" and telemetry[-1]["at"] >= telemetry[0]["at"]
        assert not adapter.telemetry_for("different-session")
    assert requests == [("/v1/messages", "synthetic", {
        "model": MODEL, "system": "只返回 JSON", "messages": [{"role": "user", "content": "虚构任务"}],
        "max_tokens": 120, "thinking": {"type": "disabled"}, "stream": True,
    })]
