"""Private Android PWA pairing, sessions, and idempotent capture service."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from app.database import (
    MOBILE_REGISTRY,
    apply_migrations,
    connect_database,
)

from app.atomic import atomic_write_bytes, content_lock
from app.content import ContentItem, load_items
from app.workspace import create_item, items_directory


PAIRING_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=180)
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 25 * 1024 * 1024
MOBILE_SESSION_COOKIE = "pcw_mobile_session"
IMAGE_SIGNATURES = {
    "png": ((b"\x89PNG\r\n\x1a\n",), ".png"),
    "jpeg": ((b"\xff\xd8\xff",), ".jpg"),
    "webp": ((b"RIFF",), ".webp"),
}


@dataclass(frozen=True)
class MobileDevice:
    id: str
    name: str
    created_at: str
    last_seen_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class MobileSession:
    id: str
    device_id: str
    csrf_token: str
    expires_at: str


@dataclass(frozen=True)
class OfflineCapture:
    idempotency_key: str
    body: str
    title: str = ""
    tags: str = ""
    category: str = ""
    created_at: datetime | None = None


@dataclass(frozen=True)
class CaptureReceipt:
    content_id: str
    created: bool
    image_count: int


@dataclass(frozen=True)
class CaptureIdempotencyRecord:
    idempotency_key: str
    content_id: str
    created_at: str


@dataclass(frozen=True)
class MobileConfig:
    enabled: bool
    tailnet_host: str

    @property
    def base_url(self) -> str:
        return f"https://{self.tailnet_host}" if self.tailnet_host else ""


def _utc_now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


class MobileStore:
    """Private SQLite metadata; authored data remains Markdown on the Mac."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.path = self.data_root / "mobile.db"
        self.secret_path = self.data_root / "mobile.secret"
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_root.chmod(0o700)
        if not self.secret_path.exists():
            atomic_write_bytes(self.secret_path, secrets.token_bytes(32))
        self.secret = self.secret_path.read_bytes()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_database(self.path)

    def _initialize(self) -> None:
        apply_migrations(
            self.path,
            registry=MOBILE_REGISTRY,
            subsystem="mobile_gateway",
            snapshot_root=self.data_root / "working" / "db-migrations",
            migrations={
                1: """
                CREATE TABLE IF NOT EXISTS mobile_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    tailnet_host TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO mobile_config(id) VALUES (1);
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS mobile_devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS mobile_sessions (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES mobile_devices(id),
                    token_hash TEXT NOT NULL UNIQUE,
                    csrf_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS capture_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    content_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """,
            },
        )

    def _hash(self, value: str) -> str:
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def config(self) -> MobileConfig:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT enabled, tailnet_host FROM mobile_config WHERE id=1"
            ).fetchone()
        return MobileConfig(bool(row["enabled"]), str(row["tailnet_host"]))

    def save_config(self, *, enabled: bool, tailnet_host: str) -> MobileConfig:
        host = tailnet_host.strip().lower().rstrip(".")
        if host.startswith("https://"):
            host = host[8:].split("/", 1)[0]
        if host.startswith("http://") or "/" in host or ":" in host:
            raise ValueError("请输入不带协议、端口和路径的 Tailscale HTTPS 主机名")
        if enabled and (not host or not host.endswith(".ts.net")):
            raise ValueError("启用手机同步前需要填写 .ts.net 主机名")
        with self._connect() as connection:
            connection.execute(
                "UPDATE mobile_config SET enabled=?, tailnet_host=? WHERE id=1",
                (int(enabled), host),
            )
        return MobileConfig(enabled, host)

    def create_pairing_code(self) -> tuple[str, str]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires = _utc_now() + PAIRING_TTL
        with self._connect() as connection:
            connection.execute("DELETE FROM pairing_codes")
            connection.execute(
                "INSERT INTO pairing_codes(code_hash, expires_at) VALUES (?, ?)",
                (self._hash(code), _iso(expires)),
            )
        return code, _iso(expires)

    def pair(self, code: str, device_name: str) -> tuple[MobileDevice, str]:
        config = self.config()
        if not config.enabled:
            raise PermissionError("手机同步尚未启用")
        cleaned_name = " ".join(device_name.split())[:80] or "Android 设备"
        now = _utc_now()
        code_hash = self._hash(code.strip())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT expires_at, used_at FROM pairing_codes WHERE code_hash=?",
                (code_hash,),
            ).fetchone()
            if (
                row is None
                or row["used_at"]
                or datetime.fromisoformat(row["expires_at"]) < now
            ):
                raise ValueError("配对码无效或已过期")
            device_id = uuid4().hex
            session_id = uuid4().hex
            token = secrets.token_urlsafe(48)
            csrf = secrets.token_urlsafe(32)
            created_at = _iso(now)
            expires_at = _iso(now + SESSION_TTL)
            connection.execute(
                "INSERT INTO mobile_devices VALUES (?, ?, ?, ?, NULL)",
                (device_id, cleaned_name, created_at, created_at),
            )
            connection.execute(
                "INSERT INTO mobile_sessions VALUES (?, ?, ?, ?, ?, NULL)",
                (session_id, device_id, self._hash(token), csrf, expires_at),
            )
            connection.execute(
                "UPDATE pairing_codes SET used_at=? WHERE code_hash=?",
                (created_at, code_hash),
            )
        return MobileDevice(device_id, cleaned_name, created_at, created_at, None), token

    def authenticate(self, token: str) -> MobileSession | None:
        if not token or not self.config().enabled:
            return None
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.device_id, s.csrf_token, s.expires_at,
                       s.revoked_at, d.revoked_at AS device_revoked
                FROM mobile_sessions s JOIN mobile_devices d ON d.id=s.device_id
                WHERE s.token_hash=?
                """,
                (self._hash(token),),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"]
                or row["device_revoked"]
                or datetime.fromisoformat(row["expires_at"]) < now
            ):
                return None
            connection.execute(
                "UPDATE mobile_devices SET last_seen_at=? WHERE id=?",
                (_iso(now), row["device_id"]),
            )
        return MobileSession(
            row["id"], row["device_id"], row["csrf_token"], row["expires_at"]
        )

    def devices(self) -> tuple[MobileDevice, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mobile_devices ORDER BY created_at DESC"
            ).fetchall()
        return tuple(
            MobileDevice(
                row["id"], row["name"], row["created_at"],
                row["last_seen_at"], row["revoked_at"]
            )
            for row in rows
        )

    def revoke_device(self, device_id: str) -> None:
        now = _iso(_utc_now())
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE mobile_devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (now, device_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(device_id)
            connection.execute(
                "UPDATE mobile_sessions SET revoked_at=? WHERE device_id=?",
                (now, device_id),
            )

    def revoke_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE mobile_sessions SET revoked_at=? WHERE id=?",
                (_iso(_utc_now()), session_id),
            )

    def receipt(self, key: str) -> CaptureIdempotencyRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM capture_idempotency WHERE idempotency_key=?", (key,)
            ).fetchone()
        return (
            CaptureIdempotencyRecord(row["idempotency_key"], row["content_id"], row["created_at"])
            if row else None
        )

    def save_receipt(self, key: str, content_id: str) -> CaptureIdempotencyRecord:
        created_at = _iso(_utc_now())
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO capture_idempotency VALUES (?, ?, ?)",
                (key, content_id, created_at),
            )
        return CaptureIdempotencyRecord(key, content_id, created_at)


def _detect_image(data: bytes) -> str:
    if data.startswith(IMAGE_SIGNATURES["png"][0][0]):
        return ".png"
    if data.startswith(IMAGE_SIGNATURES["jpeg"][0][0]):
        return ".jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("图片格式无效，只接受 PNG、JPEG 或 WebP")


class MobileCaptureService:
    def __init__(self, data_root: Path, content_root: Path, store: MobileStore) -> None:
        self.data_root = data_root.resolve()
        self.content_root = content_root.resolve()
        self.store = store

    def recent(self, limit: int = 20) -> tuple[ContentItem, ...]:
        return tuple(
            item for item in load_items(items_directory(self.content_root)).items
            if item.kind == "thought" and item.status == "draft"
        )[: max(1, min(limit, 50))]

    def create_capture(
        self,
        capture: OfflineCapture,
        images: Sequence[bytes] = (),
    ) -> CaptureReceipt:
        key = capture.idempotency_key.strip()
        if not key or len(key) > 160:
            raise ValueError("幂等键无效")
        previous = self.store.receipt(key)
        if previous:
            return CaptureReceipt(previous.content_id, False, 0)
        if len(images) > MAX_IMAGES:
            raise ValueError(f"每条记录最多上传 {MAX_IMAGES} 张图片")
        if any(len(image) > MAX_IMAGE_BYTES for image in images):
            raise ValueError("单张图片不能超过 10 MB")
        if sum(map(len, images)) > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError("图片总大小不能超过 25 MB")

        image_specs = [(_detect_image(data), data) for data in images]
        with content_lock(self.content_root):
            previous = self.store.receipt(key)
            if previous:
                return CaptureReceipt(previous.content_id, False, 0)
            stable_id = f"mobile-{hashlib.sha256(key.encode()).hexdigest()[:24]}"
            existing = load_items(items_directory(self.content_root)).get(stable_id)
            if existing:
                self.store.save_receipt(key, existing.id)
                return CaptureReceipt(existing.id, False, 0)

            written: list[Path] = []
            created_item: ContentItem | None = None
            try:
                markdown_images: list[str] = []
                for index, (suffix, data) in enumerate(image_specs, start=1):
                    name = f"mobile-{uuid4().hex}{suffix}"
                    path = self.content_root / "assets" / name
                    atomic_write_bytes(path, data)
                    written.append(path)
                    markdown_images.append(f"![手机配图 {index}](/assets/{name})")
                body = capture.body.strip()
                if markdown_images:
                    body = f"{body}\n\n" + "\n\n".join(markdown_images)
                created_item = create_item(
                    self.content_root,
                    body=body,
                    title=capture.title,
                    tags=capture.tags,
                    category=capture.category,
                    now=capture.created_at,
                    item_id=stable_id,
                )
                self.store.save_receipt(key, created_item.id)
                return CaptureReceipt(created_item.id, True, len(written))
            except Exception:
                if created_item is not None:
                    created_item.source.unlink(missing_ok=True)
                for path in written:
                    path.unlink(missing_ok=True)
                raise


def manifest_payload() -> str:
    return json.dumps(
        {
            "name": "羽白工作台",
            "short_name": "羽白工作台",
            "description": "随时接住想法，并在 Tailnet 中阅读 Mac 上的分层知识库。",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f5f3ed",
            "theme_color": "#168da2",
            "icons": [
                {
                    "src": "/mobile-assets/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/mobile-assets/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        },
        ensure_ascii=False,
    )
