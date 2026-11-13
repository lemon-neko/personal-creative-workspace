"""Bounded, private subprocess diagnostics. Unknown output is never persisted verbatim."""

import asyncio
import os
import re
import stat
from threading import Lock
from datetime import datetime, timezone
from pathlib import Path

MAX_LINE = 8192
MAX_FILE = 5_000_000
_SENSITIVE = re.compile(
    r"bearer|api[-_ ]?key|password|secret|authorization|credential|(?:owner|worker|source)[-_ ]?(?:key|token)"
    r"|prompt|messages|request[ _-]?body|environ", re.IGNORECASE,
)
# These exact infrastructure messages carry no user content. Everything else is classified.
_SAFE = re.compile(
    r"(?:INFO:\s+(?:Started server process \[\d+\]|Uvicorn running on http://127\.0\.0\.1:\d+ "
    r"\(Press CTRL\+C to quit\)|Shutting down|Finished server process \[\d+\])"
    r"|[\dT:.Z+-]+ \[hub\] listening on 127\.0\.0\.1:\d+)"
)


def safe_line(line: bytes) -> str:
    message = line.decode("utf-8", errors="replace").strip()
    if _SENSITIVE.search(message):
        return "[敏感输出已隐藏]"
    if _SAFE.fullmatch(message):
        return message
    lowered = message.lower()
    if "address already in use" in lowered or "eaddrinuse" in lowered:
        return "端口已被占用"
    if "permission denied" in lowered or "eacces" in lowered:
        return "权限不足"
    if "syntaxerror" in lowered:
        return "插件报告语法错误"
    return "[插件输出已隐藏]"


class ProcessLogs:
    def __init__(self, root: Path, name: str):
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise ValueError("无效服务名称")
        self.root = root
        self.path = root / f"{name}.log"
        self.previous = root / f"{name}.log.1"
        self._write_lock = Lock()

    def _append(self, data: bytes) -> None:
        with self._write_lock:
            if self.root.is_symlink() or self.root.parent.is_symlink():
                raise OSError("日志目录无效")
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.root.chmod(0o700)
            if self.path.is_symlink() or self.previous.is_symlink():
                raise OSError("日志路径无效")
            if self.path.exists() and self.path.stat().st_size + len(data) > MAX_FILE:
                self.path.replace(self.previous)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            with os.fdopen(fd, "ab") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise OSError("日志文件无效")
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)

    async def capture(self, stream: asyncio.StreamReader, source: str) -> None:
        pending = bytearray()
        overflow = False
        while True:
            chunk = await stream.read(4096)
            records = []
            lines = chunk.split(b"\n")
            for index, line in enumerate(lines):
                if len(pending) + len(line) > MAX_LINE:
                    overflow = True
                    pending.clear()
                elif not overflow:
                    pending.extend(line)
                if index < len(lines) - 1 or (not chunk and (pending or overflow)):
                    body = "[超长输出已隐藏]" if overflow else safe_line(pending)
                    records.append(body)
                    pending.clear()
                    overflow = False
            if records:
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                data = "".join(f"{stamp} [{source}] {body}\n" for body in records).encode()
                try:
                    await asyncio.to_thread(self._append, data)
                except OSError:
                    # A full disk must not prevent draining child pipes.
                    pass
            if not chunk:
                return

    def tail(self) -> str:
        if self.root.is_symlink() or self.root.parent.is_symlink() or not self.path.is_file():
            return ""
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                stream.seek(max(0, os.fstat(stream.fileno()).st_size - MAX_LINE))
                data = stream.read(MAX_LINE).decode("utf-8", errors="replace")
            # Persisted logs may predate this process or have been edited.
            rows = []
            for line in data.splitlines()[-12:]:
                prefix, _, body = line.partition("] ")
                if re.fullmatch(r"[\dT:.Z+-]+ \[(?:stdout|stderr)", prefix):
                    safe = body if body in {
                        "端口已被占用", "权限不足", "插件报告语法错误", "[插件输出已隐藏]",
                        "[敏感输出已隐藏]", "[超长输出已隐藏]",
                    } else safe_line(body.encode())
                    rows.append(f"{prefix}] {safe}")
            return "\n".join(rows)
        except OSError:
            return ""
