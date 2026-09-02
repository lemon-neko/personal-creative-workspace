"""Private WeChat Official Account draft delivery.

The module deliberately keeps credentials in macOS Keychain, full article HTML
in a short-lived private intent file, and only minimal delivery metadata in the
workspace database.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Protocol, TypeVar
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from app.database import WORKSPACE_REGISTRY, apply_migrations, connect_database


SHANGHAI = ZoneInfo("Asia/Shanghai")
KEYCHAIN_SERVICE = "personal-creative-workspace.wechat"
APP_ID_ACCOUNT = "official-account-app-id"
APP_SECRET_ACCOUNT = "official-account-app-secret"
WECHAT_APP_ID_ENV = "WECHAT_APP_ID"
WECHAT_APP_SECRET_ENV = "WECHAT_APP_SECRET"
WECHAT_API_ORIGIN = "https://api.weixin.qq.com"
WECHAT_CDN_HOSTS = {"mmbiz.qpic.cn"}
TOKEN_INVALID_CODES = {"40001", "40014", "42001"}
_T = TypeVar("_T")
INTENT_TTL_SECONDS = 24 * 60 * 60
MAX_EXPORT_HTML_BYTES = 5 * 1024 * 1024
MAX_FINAL_CONTENT_BYTES = 1024 * 1024
MAX_FINAL_CONTENT_CHARACTERS = 20_000
MAX_BODY_IMAGE_BYTES = 1024 * 1024
MAX_BODY_IMAGES = 32
MAX_COVER_BYTES = 10 * 1024 * 1024
ALLOWED_BODY_MIMES = {"image/png", "image/jpeg", "image/gif"}
ALLOWED_COVER_MIMES = {"image/png", "image/jpeg"}
APP_ID_PATTERN = re.compile(r"^wx[A-Za-z0-9]{16}$")
DATA_IMAGE_PATTERN = re.compile(
    r"^data:(image/(?:png|jpeg|gif));base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE,
)


WECHAT_MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS wechat_draft_pushes (
        id TEXT PRIMARY KEY,
        article_id TEXT NOT NULL,
        article_revision TEXT NOT NULL,
        dedupe_key TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        cover_asset TEXT NOT NULL,
        cover_hash TEXT NOT NULL,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        digest TEXT NOT NULL,
        status TEXT NOT NULL,
        image_count INTEGER NOT NULL DEFAULT 0,
        formula_count INTEGER NOT NULL DEFAULT 0,
        media_id TEXT,
        error_stage TEXT,
        error_code TEXT,
        duplicate_of TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_wechat_pushes_dedupe
        ON wechat_draft_pushes(dedupe_key, status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_wechat_pushes_article
        ON wechat_draft_pushes(article_id, created_at DESC);
    """,
}


def _now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def _sha256(value: bytes | str) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class WechatCredentials:
    app_id: str
    app_secret: str


@dataclass(frozen=True)
class WechatCredentialStatus:
    configured: bool
    masked_app_id: str
    keychain_available: bool
    error: str = ""
    storage: str = "macOS 钥匙串"


@dataclass(frozen=True)
class WechatConnectionReport:
    token_available: bool
    draft_api_available: bool
    message: str


class CredentialStore(Protocol):
    def status(self) -> WechatCredentialStatus: ...

    def load(self) -> WechatCredentials: ...

    def save(self, credentials: WechatCredentials) -> None: ...

    def delete(self) -> None: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]


class MacOSKeychainCredentialStore:
    """Store the account credentials without command-line secret exposure."""

    def __init__(self, runner: Runner = subprocess.run) -> None:
        self.runner = runner

    @staticmethod
    def _security() -> str:
        executable = shutil.which("security")
        if not executable:
            raise RuntimeError("当前系统无法使用 macOS 钥匙串")
        return executable

    def _read(self, account: str) -> str:
        completed = self.runner(
            [
                self._security(),
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    def _exists(self, account: str) -> bool:
        completed = self.runner(
            [
                self._security(),
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                account,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0

    def _write(self, account: str, value: str) -> None:
        completed = self.runner(
            [
                self._security(),
                "add-generic-password",
                "-U",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
            ],
            input=f"{value}\n",
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError("写入 macOS 钥匙串失败")

    def status(self) -> WechatCredentialStatus:
        try:
            app_id = self._read(APP_ID_ACCOUNT)
            has_secret = self._exists(APP_SECRET_ACCOUNT)
        except RuntimeError as error:
            return WechatCredentialStatus(False, "", False, str(error))
        masked = f"{app_id[:4]}…{app_id[-4:]}" if len(app_id) >= 10 else ""
        return WechatCredentialStatus(bool(app_id and has_secret), masked, True)

    def load(self) -> WechatCredentials:
        app_id = self._read(APP_ID_ACCOUNT)
        secret = self._read(APP_SECRET_ACCOUNT)
        if not app_id or not secret:
            raise RuntimeError("微信公众号凭证尚未配置完整")
        return WechatCredentials(app_id, secret)

    def save(self, credentials: WechatCredentials) -> None:
        validate_credentials(credentials)
        self._write(APP_ID_ACCOUNT, credentials.app_id)
        try:
            self._write(APP_SECRET_ACCOUNT, credentials.app_secret)
        except Exception:
            self.delete()
            raise

    def delete(self) -> None:
        executable = self._security()
        for account in (APP_ID_ACCOUNT, APP_SECRET_ACCOUNT):
            self.runner(
                [
                    executable,
                    "delete-generic-password",
                    "-s",
                    KEYCHAIN_SERVICE,
                    "-a",
                    account,
                ],
                check=False,
                capture_output=True,
                text=True,
            )


class EnvironmentCredentialStore:
    """Read optional backend-only compatibility credentials from the process."""

    def status(self) -> WechatCredentialStatus:
        app_id = os.environ.get(WECHAT_APP_ID_ENV, "").strip()
        app_secret = os.environ.get(WECHAT_APP_SECRET_ENV, "").strip()
        configured = bool(app_id and app_secret)
        masked = f"{app_id[:4]}…{app_id[-4:]}" if len(app_id) >= 10 else ""
        return WechatCredentialStatus(
            configured,
            masked,
            True,
            storage="后端环境变量",
        )

    def load(self) -> WechatCredentials:
        credentials = WechatCredentials(
            os.environ.get(WECHAT_APP_ID_ENV, "").strip(),
            os.environ.get(WECHAT_APP_SECRET_ENV, "").strip(),
        )
        if not credentials.app_id or not credentials.app_secret:
            raise RuntimeError("微信公众号后端环境变量尚未配置完整")
        validate_credentials(credentials)
        return credentials

    def save(self, credentials: WechatCredentials) -> None:
        raise RuntimeError("环境变量只能在启动工作台前由作者配置")

    def delete(self) -> None:
        raise RuntimeError("请在启动工作台的终端中删除微信公众号环境变量")


class LayeredCredentialStore:
    """Prefer Keychain while keeping an explicit environment-only fallback."""

    def __init__(
        self,
        keychain: CredentialStore | None = None,
        environment: CredentialStore | None = None,
    ) -> None:
        self.keychain = keychain or MacOSKeychainCredentialStore()
        self.environment = environment or EnvironmentCredentialStore()

    def status(self) -> WechatCredentialStatus:
        keychain = self.keychain.status()
        if keychain.configured:
            return keychain
        environment = self.environment.status()
        if environment.configured:
            return environment
        return keychain

    def load(self) -> WechatCredentials:
        if self.keychain.status().configured:
            return self.keychain.load()
        return self.environment.load()

    def save(self, credentials: WechatCredentials) -> None:
        self.keychain.save(credentials)

    def delete(self) -> None:
        self.keychain.delete()


def validate_credentials(credentials: WechatCredentials) -> None:
    if not APP_ID_PATTERN.fullmatch(credentials.app_id.strip()):
        raise ValueError("AppID 格式不正确，应为 wx 开头的 18 位标识")
    if not 16 <= len(credentials.app_secret.strip()) <= 128:
        raise ValueError("AppSecret 格式不正确")


@dataclass(frozen=True)
class PreparedImage:
    source: str
    mime_type: str
    data: bytes

    @property
    def suffix(self) -> str:
        return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}[
            self.mime_type
        ]


@dataclass(frozen=True)
class PreparedWechatContent:
    html: str
    images: tuple[PreparedImage, ...]
    content_hash: str


class _PushHTMLInspector(HTMLParser):
    FORBIDDEN_TAGS = {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "form",
        "input",
        "button",
        "meta",
        "link",
        "base",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_sources: list[str] = []
        self.error = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in self.FORBIDDEN_TAGS:
            self.error = "正文包含不允许推送的 HTML 元素"
            return
        for raw_name, raw_value in attrs:
            name = raw_name.casefold()
            value = raw_value or ""
            if name.startswith("on"):
                self.error = "正文包含事件属性"
            elif name == "style" and re.search(
                r"(?:expression|javascript\s*:|url\s*\(|var\s*\()", value, re.I
            ):
                self.error = "正文包含不安全或未解析的样式"
            elif lowered == "a" and name == "href" and value:
                if urlparse(value).scheme.casefold() not in {"http", "https", "mailto"}:
                    self.error = "正文包含不安全链接"
            elif lowered == "img" and name == "src":
                self.image_sources.append(value)


class _ComparableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            self.skip_depth += 1
            return
        if any(name == "data-formula-source" for name, _value in attrs):
            self.skip_depth = 1

    def handle_endtag(self, _tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def value(self) -> str:
        return " ".join("".join(self.parts).replace("\xa0", " ").split())


def comparable_text(html: str) -> str:
    parser = _ComparableTextParser()
    parser.feed(html)
    parser.close()
    return parser.value()


def prepare_wechat_html(html: str, expected_html: str) -> PreparedWechatContent:
    encoded = html.encode("utf-8")
    if not html.strip() or len(encoded) > MAX_EXPORT_HTML_BYTES:
        raise ValueError("公众号正文为空或体积超过 5 MB")
    if comparable_text(html) != comparable_text(expected_html):
        raise ValueError("页面正文与当前文章版本不一致，请刷新后重新准备")
    inspector = _PushHTMLInspector()
    inspector.feed(html)
    inspector.close()
    if inspector.error:
        raise ValueError(inspector.error)
    if len(inspector.image_sources) > MAX_BODY_IMAGES:
        raise ValueError(f"正文图片不能超过 {MAX_BODY_IMAGES} 张")
    images: list[PreparedImage] = []
    for source in dict.fromkeys(inspector.image_sources):
        parsed_source = urlparse(source.strip())
        if (
            parsed_source.scheme == "https"
            and (parsed_source.hostname or "").casefold() in WECHAT_CDN_HOSTS
        ):
            continue
        matched = DATA_IMAGE_PATTERN.fullmatch(source.strip())
        if matched is None:
            raise ValueError("存在未内嵌的外部图片，请先处理后再推送")
        mime_type = matched.group(1).casefold()
        if mime_type not in ALLOWED_BODY_MIMES:
            raise ValueError("正文图片只支持 PNG、JPEG 或 GIF")
        try:
            data = base64.b64decode(matched.group(2), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("正文图片数据损坏") from error
        if not data or len(data) > MAX_BODY_IMAGE_BYTES:
            raise ValueError("单张正文图片必须小于 1 MB")
        validate_image_signature(data, mime_type)
        images.append(PreparedImage(source, mime_type, data))
    return PreparedWechatContent(html, tuple(images), _sha256(encoded))


def validate_final_wechat_content(html: str) -> None:
    """Validate the actual HTML after image URLs have been replaced."""

    if len(html) > MAX_FINAL_CONTENT_CHARACTERS:
        raise ValueError("微信最终正文不能超过 20000 个字符")
    if len(html.encode("utf-8")) > MAX_FINAL_CONTENT_BYTES:
        raise ValueError("微信最终正文不能超过 1 MB")


def detect_image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    raise ValueError("无法识别图片格式")


def validate_image_signature(data: bytes, mime_type: str) -> None:
    if detect_image_mime(data) != mime_type:
        raise ValueError("图片声明格式与真实内容不一致")


def save_cover_asset(content_root: Path, filename: str, data: bytes) -> str:
    if not data or len(data) > MAX_COVER_BYTES:
        raise ValueError("封面图片为空或超过 10 MB")
    mime_type = detect_image_mime(data)
    if mime_type not in ALLOWED_COVER_MIMES:
        raise ValueError("封面只支持 PNG 或 JPEG")
    suffix = ".png" if mime_type == "image/png" else ".jpg"
    directory = content_root / "assets"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    name = f"wechat-cover-{uuid.uuid4().hex}{suffix}"
    descriptor, temporary = tempfile.mkstemp(prefix=".wechat-cover-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, directory / name)
        (directory / name).chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return name


def read_cover_asset(content_root: Path, asset_name: str) -> tuple[bytes, str]:
    if Path(asset_name).name != asset_name:
        raise ValueError("封面文件名不合法")
    path = content_root / "assets" / asset_name
    if not path.is_file():
        raise ValueError("封面文件不存在")
    data = path.read_bytes()
    if len(data) > MAX_COVER_BYTES:
        raise ValueError("封面图片超过 10 MB")
    mime_type = detect_image_mime(data)
    if mime_type not in ALLOWED_COVER_MIMES:
        raise ValueError("封面只支持 PNG 或 JPEG")
    return data, mime_type


def list_cover_assets(content_root: Path, *, limit: int = 100) -> tuple[str, ...]:
    """Return reusable private PNG/JPEG assets without exposing filesystem paths."""

    root = content_root / "assets"
    if not root.is_dir():
        return ()
    values = [
        path
        for path in root.iterdir()
        if path.is_file()
        and path.name == Path(path.name).name
        and path.suffix.casefold() in {".png", ".jpg", ".jpeg"}
    ]
    values.sort(key=lambda value: value.stat().st_mtime, reverse=True)
    return tuple(value.name for value in values[:limit])


@dataclass(frozen=True)
class WechatPushIntent:
    id: str
    article_id: str
    article_revision: str
    title: str
    author: str
    digest: str
    source_url: str
    final_html: str
    content_hash: str
    cover_asset: str
    cover_hash: str
    image_count: int
    formula_count: int
    dedupe_key: str
    created_at: str
    expires_at: float


class WechatPushIntentStore:
    def __init__(self, data_root: Path) -> None:
        self.directory = data_root / "working" / "wechat-push" / "intents"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def cleanup(self) -> None:
        now = time.time()
        for path in self.directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if float(payload.get("expires_at", 0)) <= now:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                path.unlink(missing_ok=True)

    def save(self, intent: WechatPushIntent) -> None:
        self.cleanup()
        target = self.directory / f"{intent.id}.json"
        descriptor, temporary = tempfile.mkstemp(prefix=".intent-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(intent), handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            target.chmod(0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, intent_id: str) -> WechatPushIntent:
        if not re.fullmatch(r"[0-9a-f]{32}", intent_id):
            raise KeyError(intent_id)
        path = self.directory / f"{intent_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            intent = WechatPushIntent(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise KeyError(intent_id) from error
        if intent.expires_at <= time.time():
            path.unlink(missing_ok=True)
            raise ValueError("推送确认已过期，请重新准备")
        return intent

    def delete(self, intent_id: str) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", intent_id):
            (self.directory / f"{intent_id}.json").unlink(missing_ok=True)


@dataclass(frozen=True)
class WechatDraftPush:
    id: str
    article_id: str
    article_revision: str
    dedupe_key: str
    content_hash: str
    cover_asset: str
    cover_hash: str
    title: str
    author: str
    digest: str
    status: str
    image_count: int
    formula_count: int
    media_id: str
    error_stage: str
    error_code: str
    duplicate_of: str
    created_at: str
    updated_at: str


def _draft_push(row: sqlite3.Row | None) -> WechatDraftPush | None:
    if row is None:
        return None
    return WechatDraftPush(**{key: row[key] or "" for key in WechatDraftPush.__annotations__})


class WechatPushRepository:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "workspace.db"
        apply_migrations(
            self.path,
            registry=WORKSPACE_REGISTRY,
            subsystem="wechat_publishing",
            migrations=WECHAT_MIGRATIONS,
            snapshot_root=data_root / "working" / "db-migrations",
        )

    def successful(self, dedupe_key: str) -> WechatDraftPush | None:
        with connect_database(self.path) as connection:
            row = connection.execute(
                """SELECT * FROM wechat_draft_pushes
                WHERE dedupe_key=? AND status='succeeded'
                ORDER BY created_at DESC LIMIT 1""",
                (dedupe_key,),
            ).fetchone()
        return _draft_push(row)

    def blocking(self, dedupe_key: str) -> WechatDraftPush | None:
        """Return a completed or unresolved push that must not be retried blindly."""

        with connect_database(self.path) as connection:
            row = connection.execute(
                """SELECT * FROM wechat_draft_pushes
                WHERE dedupe_key=? AND status IN ('succeeded','unknown')
                ORDER BY created_at DESC LIMIT 1""",
                (dedupe_key,),
            ).fetchone()
        return _draft_push(row)

    def create(
        self,
        intent: WechatPushIntent,
        *,
        duplicate_of: str = "",
    ) -> WechatDraftPush:
        push_id = uuid.uuid4().hex
        now = _now()
        with connect_database(self.path) as connection:
            connection.execute(
                """INSERT INTO wechat_draft_pushes(
                    id,article_id,article_revision,dedupe_key,content_hash,
                    cover_asset,cover_hash,title,author,digest,status,image_count,
                    formula_count,media_id,error_stage,error_code,duplicate_of,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    push_id,
                    intent.article_id,
                    intent.article_revision,
                    intent.dedupe_key,
                    intent.content_hash,
                    intent.cover_asset,
                    intent.cover_hash,
                    intent.title,
                    intent.author,
                    intent.digest,
                    "uploading",
                    intent.image_count,
                    intent.formula_count,
                    "",
                    "",
                    "",
                    duplicate_of,
                    now,
                    now,
                ),
            )
        return self.get(push_id)  # type: ignore[return-value]

    def update(
        self,
        push_id: str,
        *,
        status: str,
        media_id: str = "",
        error_stage: str = "",
        error_code: str = "",
    ) -> WechatDraftPush:
        with connect_database(self.path) as connection:
            connection.execute(
                """UPDATE wechat_draft_pushes SET status=?,media_id=?,
                error_stage=?,error_code=?,updated_at=? WHERE id=?""",
                (status, media_id, error_stage, error_code, _now(), push_id),
            )
        value = self.get(push_id)
        if value is None:
            raise KeyError(push_id)
        return value

    def get(self, push_id: str) -> WechatDraftPush | None:
        with connect_database(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM wechat_draft_pushes WHERE id=?", (push_id,)
            ).fetchone()
        return _draft_push(row)


class WechatAPIError(RuntimeError):
    FRIENDLY_MESSAGES = {
        "40013": "AppID 不正确",
        "40125": "AppSecret 不正确",
        "40164": "当前公网 IP 未加入公众号白名单",
        "45009": "微信接口调用频率已达上限",
        "48001": (
            "当前公众号没有所调用接口的权限；若发生在草稿权限检查或创建草稿阶段，"
            "请检查公众号主体、认证状态和草稿接口权限，这通常不是代码故障"
        ),
    }

    def __init__(self, stage: str, code: str = "api-error") -> None:
        self.stage = stage
        self.code = code[:40]
        detail = self.FRIENDLY_MESSAGES.get(self.code, "请依据错误码检查公众号配置")
        super().__init__(f"微信接口在“{stage}”阶段返回错误（{self.code}）：{detail}")

    @property
    def token_invalid(self) -> bool:
        return self.code in TOKEN_INVALID_CODES


class WechatUnknownResult(WechatAPIError):
    pass


class WechatOfficialClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self._access_token = ""
        self._expires_at = 0.0

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=WECHAT_API_ORIGIN,
            timeout=httpx.Timeout(20.0, connect=8.0, read=20.0, write=20.0),
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        )

    @staticmethod
    def _payload(response: httpx.Response, stage: str) -> dict:
        try:
            value = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise WechatAPIError(stage, "invalid-json") from error
        if not isinstance(value, dict):
            raise WechatAPIError(stage, "invalid-response")
        code = value.get("errcode")
        if code not in (None, 0, "0"):
            raise WechatAPIError(stage, str(code))
        return value

    async def access_token(self, credentials: WechatCredentials) -> str:
        if self._access_token and self._expires_at > time.monotonic() + 120:
            return self._access_token
        async with self._client() as client:
            response = await client.get(
                "/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": credentials.app_id,
                    "secret": credentials.app_secret,
                },
            )
        payload = self._payload(response, "获取 Access Token")
        token = str(payload.get("access_token", ""))
        if not token:
            raise WechatAPIError("获取 Access Token", "missing-token")
        expires_in = max(300, int(payload.get("expires_in", 7200)))
        self._access_token = token
        self._expires_at = time.monotonic() + expires_in
        return token

    def invalidate_access_token(self) -> None:
        self._access_token = ""
        self._expires_at = 0.0

    async def draft_count(self, token: str) -> int:
        """Probe draft API permission without creating or modifying a draft."""

        async with self._client() as client:
            response = await client.get(
                "/cgi-bin/draft/count",
                params={"access_token": token},
            )
        payload = self._payload(response, "检查草稿接口权限")
        try:
            return max(0, int(payload.get("total_count", 0)))
        except (TypeError, ValueError) as error:
            raise WechatAPIError("检查草稿接口权限", "invalid-count") from error

    async def upload_body_image(self, token: str, image: PreparedImage) -> str:
        async with self._client() as client:
            response = await client.post(
                "/cgi-bin/media/uploadimg",
                params={"access_token": token},
                files={"media": (f"article{image.suffix}", image.data, image.mime_type)},
            )
        payload = self._payload(response, "上传正文图片")
        url = str(payload.get("url", ""))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise WechatAPIError("上传正文图片", "missing-image-url")
        return parsed._replace(scheme="https").geturl()

    async def upload_cover(
        self,
        token: str,
        data: bytes,
        mime_type: str,
    ) -> str:
        suffix = ".png" if mime_type == "image/png" else ".jpg"
        async with self._client() as client:
            response = await client.post(
                "/cgi-bin/material/add_material",
                params={"access_token": token, "type": "image"},
                files={"media": (f"cover{suffix}", data, mime_type)},
            )
        payload = self._payload(response, "上传封面")
        media_id = str(payload.get("media_id", ""))
        if not media_id:
            raise WechatAPIError("上传封面", "missing-media-id")
        return media_id

    async def add_draft(
        self,
        token: str,
        *,
        title: str,
        author: str,
        digest: str,
        source_url: str,
        content: str,
        thumb_media_id: str,
    ) -> str:
        body = {
            "articles": [
                {
                    "title": title,
                    "author": author,
                    "digest": digest,
                    "content": content,
                    "content_source_url": source_url,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 1,
                    "only_fans_can_comment": 0,
                }
            ]
        }
        try:
            async with self._client() as client:
                response = await client.post(
                    "/cgi-bin/draft/add",
                    params={"access_token": token},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise WechatUnknownResult("创建草稿", "timeout") from error
        payload = self._payload(response, "创建草稿")
        media_id = str(payload.get("media_id", ""))
        if not media_id:
            raise WechatAPIError("创建草稿", "missing-media-id")
        return media_id


class WechatPublisher:
    def __init__(
        self,
        data_root: Path,
        content_root: Path,
        *,
        credentials: CredentialStore | None = None,
        client: WechatOfficialClient | None = None,
    ) -> None:
        self.content_root = content_root
        self.credentials = credentials or LayeredCredentialStore()
        self.client = client or WechatOfficialClient()
        self.intents = WechatPushIntentStore(data_root)
        self.pushes = WechatPushRepository(data_root)
        self.last_connection_report: WechatConnectionReport | None = None

    def credential_status(self) -> WechatCredentialStatus:
        return self.credentials.status()

    async def test_connection(self) -> WechatConnectionReport:
        credentials = self.credentials.load()
        try:
            count = await self._with_token_retry(
                credentials,
                self.client.draft_count,
            )
        except Exception:
            self.last_connection_report = None
            raise
        report = WechatConnectionReport(
            token_available=True,
            draft_api_available=True,
            message=f"凭证、IP 白名单与草稿接口均可用；当前草稿数量 {count}。",
        )
        self.last_connection_report = report
        return report

    async def _with_token_retry(
        self,
        credentials: WechatCredentials,
        operation: Callable[[str], Awaitable[_T]],
    ) -> _T:
        """Run one WeChat operation and refresh an explicitly rejected token once."""

        token = await self.client.access_token(credentials)
        try:
            return await operation(token)
        except WechatAPIError as error:
            if not error.token_invalid:
                raise
        self.client.invalidate_access_token()
        refreshed = await self.client.access_token(credentials)
        return await operation(refreshed)

    def prepare_intent(
        self,
        *,
        article_id: str,
        article_revision: str,
        title: str,
        author: str,
        digest: str,
        source_url: str,
        final_html: str,
        expected_html: str,
        cover_asset: str,
        formula_count: int,
    ) -> tuple[WechatPushIntent, WechatDraftPush | None]:
        title = title.strip()
        author = author.strip()
        digest = digest.strip()
        source_url = source_url.strip()
        if not title or len(title) > 64:
            raise ValueError("标题不能为空且不能超过 64 个字符")
        if not author or len(author) > 16:
            raise ValueError("作者不能为空且不能超过 16 个字符")
        if len(digest) > 120:
            raise ValueError("摘要不能超过 120 个字符")
        if source_url:
            parsed = urlparse(source_url)
            if parsed.scheme != "https" or not parsed.hostname or len(source_url) > 500:
                raise ValueError("原文链接必须是有效的 HTTPS 地址")
        prepared = prepare_wechat_html(final_html, expected_html)
        cover, _mime = read_cover_asset(self.content_root, cover_asset)
        cover_hash = _sha256(cover)
        dedupe_key = _sha256(
            "|".join((article_id, article_revision, prepared.content_hash, cover_hash))
        )
        intent = WechatPushIntent(
            id=uuid.uuid4().hex,
            article_id=article_id,
            article_revision=article_revision,
            title=title,
            author=author,
            digest=digest,
            source_url=source_url,
            final_html=prepared.html,
            content_hash=prepared.content_hash,
            cover_asset=cover_asset,
            cover_hash=cover_hash,
            image_count=len(prepared.images),
            formula_count=max(0, formula_count),
            dedupe_key=dedupe_key,
            created_at=_now(),
            expires_at=time.time() + INTENT_TTL_SECONDS,
        )
        self.intents.save(intent)
        return intent, self.pushes.blocking(dedupe_key)

    async def push(
        self,
        intent: WechatPushIntent,
        *,
        current_revision: str,
        allow_duplicate: bool = False,
    ) -> WechatDraftPush:
        if current_revision != intent.article_revision:
            raise ValueError("文章已被修改，请重新准备推送")
        prepared = prepare_wechat_html(intent.final_html, intent.final_html)
        if prepared.content_hash != intent.content_hash:
            raise ValueError("待确认正文已发生变化，请重新准备推送")
        cover, cover_mime = read_cover_asset(
            self.content_root, intent.cover_asset
        )
        if _sha256(cover) != intent.cover_hash:
            raise ValueError("封面已发生变化，请重新准备推送")
        existing = self.pushes.blocking(intent.dedupe_key)
        if existing and not allow_duplicate:
            return existing
        push = self.pushes.create(
            intent,
            duplicate_of=existing.id if existing and allow_duplicate else "",
        )
        try:
            credentials = self.credentials.load()
            content = intent.final_html
            for image in prepared.images:
                uploaded_url = await self._with_token_retry(
                    credentials,
                    lambda token, current=image: self.client.upload_body_image(
                        token, current
                    ),
                )
                content = content.replace(image.source, uploaded_url)
            thumb_media_id = await self._with_token_retry(
                credentials,
                lambda token: self.client.upload_cover(token, cover, cover_mime),
            )
            validate_final_wechat_content(content)
            media_id = await self._with_token_retry(
                credentials,
                lambda token: self.client.add_draft(
                    token,
                    title=intent.title,
                    author=intent.author,
                    digest=intent.digest,
                    source_url=intent.source_url,
                    content=content,
                    thumb_media_id=thumb_media_id,
                ),
            )
        except WechatUnknownResult as error:
            return self.pushes.update(
                push.id,
                status="unknown",
                error_stage=error.stage,
                error_code=error.code,
            )
        except WechatAPIError as error:
            return self.pushes.update(
                push.id,
                status="failed",
                error_stage=error.stage,
                error_code=error.code,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            stage = "本地准备" if isinstance(error, ValueError) else "连接微信"
            return self.pushes.update(
                push.id,
                status="failed",
                error_stage=stage,
                error_code=type(error).__name__[:40],
            )
        self.intents.delete(intent.id)
        return self.pushes.update(push.id, status="succeeded", media_id=media_id)
