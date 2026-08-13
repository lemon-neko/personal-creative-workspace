"""Small cross-process primitives for private workspace files."""

from __future__ import annotations

import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import fcntl


_THREAD_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


@contextmanager
def content_lock(content_root: Path) -> Iterator[None]:
    """Serialize authored-content mutations across desktop and mobile processes."""

    with _THREAD_LOCK:
        depth = getattr(_LOCK_STATE, "depth", 0)
        if depth:
            _LOCK_STATE.depth = depth + 1
            try:
                yield
            finally:
                _LOCK_STATE.depth -= 1
            return

        content_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        content_root.chmod(0o700)
        lock_path = content_root / ".content.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            _LOCK_STATE.depth = 1
            yield
        finally:
            _LOCK_STATE.depth = 0
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write one private file durably without exposing a partial destination."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(mode)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)
