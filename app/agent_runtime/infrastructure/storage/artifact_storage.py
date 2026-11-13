import hashlib
from pathlib import Path

from app.atomic import atomic_write_text, content_lock


class ArtifactStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def _path(self, key: str) -> Path:
        if not key or Path(key).name != key or key in {".", ".."}:
            raise FileNotFoundError(key)
        return self.root / key

    def write(self, key: str, body: str) -> str:
        path = self._path(key)
        with content_lock(self.root):
            if path.exists() or path.is_symlink():
                raise FileExistsError(key)
            try:
                atomic_write_text(path, body, mode=0o600)
            except OSError:
                path.unlink(missing_ok=True)
                raise
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def read(self, key: str, expected_hash: str) -> str:
        path = self._path(key)
        with content_lock(self.root):
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(key)
            body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != expected_hash:
            raise ValueError("产物内容校验失败")
        return body.decode("utf-8")

    def remove(self, key: str) -> None:
        with content_lock(self.root):
            self._path(key).unlink(missing_ok=True)
