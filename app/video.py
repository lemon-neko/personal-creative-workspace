"""Private video-project handoff packages for the local OpenCut integration."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

from app.content import ContentItem


SHANGHAI = ZoneInfo("Asia/Shanghai")
MANIFEST_VERSION = 1
VIDEO_STATUSES = {"planning", "editing", "exported", "archived"}
VIDEO_STATUS_LABELS = {
    "planning": "待剪辑",
    "editing": "剪辑中",
    "exported": "已导出",
    "archived": "归档",
}
OPENCUT_FORK_URL = "https://github.com/lemon-neko/OpenCut"
OPENCUT_UPSTREAM_URL = "https://github.com/OpenCut-app/OpenCut"
IMAGE_PATTERN = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)",
)
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class VideoAsset:
    """One copied workspace image inside a private video handoff package."""

    alt: str
    source_url: str
    stored_name: str
    size: int


@dataclass(frozen=True)
class VideoProject:
    """A private, file-backed video project linked to one article."""

    id: str
    title: str
    source_id: str
    source_title: str
    status: str
    notes: str
    assets: tuple[VideoAsset, ...]
    created_at: datetime
    updated_at: datetime
    directory: Path

    @property
    def date_label(self) -> str:
        return self.updated_at.astimezone(SHANGHAI).strftime("%m-%d %H:%M")

    @property
    def brief_path(self) -> Path:
        return self.directory / "brief.md"


@dataclass(frozen=True)
class OpenCutInstallation:
    """Detected local state of the user's OpenCut fork."""

    repository_path: Path
    source_available: bool
    git_checkout: bool
    editor_ready: bool
    web_url: str = "http://127.0.0.1:5173/editor"
    launch_command: str = "proto use && moon run web:dev"
    fork_url: str = OPENCUT_FORK_URL
    upstream_url: str = OPENCUT_UPSTREAM_URL

    @property
    def state_label(self) -> str:
        if not self.source_available:
            return "未找到本地源码"
        if not self.editor_ready:
            return "上游重写中"
        return "可启动"


def inspect_opencut(default_path: Path) -> OpenCutInstallation:
    """Inspect the local checkout without executing repository code."""

    configured = os.getenv("OPENCUT_REPO_DIR", "").strip()
    repository_path = (
        Path(configured).expanduser().resolve()
        if configured
        else default_path.expanduser().resolve()
    )
    readme = repository_path / "README.md"
    editor = repository_path / "apps" / "web" / "src" / "routes" / "editor.tsx"
    source_available = readme.is_file()
    editor_ready = False
    if editor.is_file():
        try:
            editor_ready = "Coming soon" not in editor.read_text(encoding="utf-8")
        except OSError:
            editor_ready = False
    return OpenCutInstallation(
        repository_path=repository_path,
        source_available=source_available,
        git_checkout=(repository_path / ".git").exists(),
        editor_ready=editor_ready,
    )


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _private_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _parse_datetime(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"视频项目的 {field} 时间无效") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _safe_project_id(value: str) -> bool:
    return bool(re.fullmatch(r"video-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}", value))


def _resolve_workspace_asset(content_root: Path, raw_url: str) -> Path | None:
    """Resolve only same-workspace image URLs; never read arbitrary file paths."""

    parsed = urlsplit(raw_url)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/assets/"):
        return None
    name = PurePosixPath(unquote(parsed.path)).name
    if not name or name != unquote(parsed.path).removeprefix("/assets/"):
        return None
    if Path(name).suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        return None
    candidate = (content_root / "assets" / name).resolve()
    asset_root = (content_root / "assets").resolve()
    try:
        candidate.relative_to(asset_root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class VideoProjectRepository:
    """Manage private article-to-video handoff packages outside Git."""

    def __init__(self, data_root: Path, content_root: Path) -> None:
        self.root = _private_directory(data_root / "video-projects")
        self.content_root = content_root.resolve()

    def _manifest_path(self, project_id: str) -> Path:
        if not _safe_project_id(project_id):
            raise KeyError(project_id)
        return self.root / project_id / "manifest.yaml"

    def _load_path(self, path: Path) -> VideoProject:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(f"无法读取视频项目：{path.parent.name}") from error
        if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
            raise ValueError("视频项目版本不受支持")
        project_id = str(raw.get("id", ""))
        status = str(raw.get("status", ""))
        if not _safe_project_id(project_id) or path.parent.name != project_id:
            raise ValueError("视频项目 ID 无效")
        if status not in VIDEO_STATUSES:
            raise ValueError("视频项目状态无效")
        raw_assets = raw.get("assets", [])
        if not isinstance(raw_assets, list):
            raise ValueError("视频项目素材列表无效")
        assets: list[VideoAsset] = []
        for value in raw_assets:
            if not isinstance(value, dict):
                raise ValueError("视频项目素材信息无效")
            stored_name = str(value.get("stored_name", ""))
            if Path(stored_name).name != stored_name:
                raise ValueError("视频项目素材文件名无效")
            assets.append(
                VideoAsset(
                    alt=str(value.get("alt", ""))[:200],
                    source_url=str(value.get("source_url", ""))[:1000],
                    stored_name=stored_name,
                    size=max(0, int(value.get("size", 0))),
                ),
            )
        return VideoProject(
            id=project_id,
            title=str(raw.get("title", "")).strip()[:120],
            source_id=str(raw.get("source_id", "")).strip()[:160],
            source_title=str(raw.get("source_title", "")).strip()[:120],
            status=status,
            notes=str(raw.get("notes", "")).strip()[:5000],
            assets=tuple(assets),
            created_at=_parse_datetime(raw.get("created_at"), "created_at"),
            updated_at=_parse_datetime(raw.get("updated_at"), "updated_at"),
            directory=path.parent,
        )

    def _write_manifest(self, project: VideoProject) -> VideoProject:
        payload = {
            "version": MANIFEST_VERSION,
            "id": project.id,
            "title": project.title,
            "source_id": project.source_id,
            "source_title": project.source_title,
            "status": project.status,
            "notes": project.notes,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
            "brief_file": "brief.md",
            "assets": [
                {
                    "alt": asset.alt,
                    "source_url": asset.source_url,
                    "stored_name": asset.stored_name,
                    "size": asset.size,
                }
                for asset in project.assets
            ],
        }
        path = project.directory / "manifest.yaml"
        _private_write(
            path,
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        )
        return self._load_path(path)

    def projects(self) -> tuple[VideoProject, ...]:
        projects: list[VideoProject] = []
        for path in self.root.glob("video-*/manifest.yaml"):
            try:
                projects.append(self._load_path(path))
            except ValueError:
                continue
        return tuple(sorted(projects, key=lambda project: project.updated_at, reverse=True))

    def get(self, project_id: str) -> VideoProject | None:
        try:
            path = self._manifest_path(project_id)
        except KeyError:
            return None
        if not path.is_file():
            return None
        try:
            return self._load_path(path)
        except ValueError:
            return None

    def create(self, source: ContentItem, *, notes: str = "") -> VideoProject:
        """Create a handoff package without modifying the source article."""

        if source.kind != "article":
            raise ValueError("视频项目只能从文章草稿或已成稿创建")
        cleaned_notes = notes.strip()
        if len(cleaned_notes) > 5000:
            raise ValueError("剪辑备注不能超过 5000 个字符")
        now = datetime.now(SHANGHAI).replace(microsecond=0)
        project_id = f"video-{now:%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
        directory = _private_directory(self.root / project_id)
        assets_directory = _private_directory(directory / "assets")
        copied: dict[str, VideoAsset] = {}
        replacements: dict[str, str] = {}

        for match in IMAGE_PATTERN.finditer(source.body):
            raw_url = match.group("target")
            asset_path = _resolve_workspace_asset(self.content_root, raw_url)
            if asset_path is None:
                continue
            asset = copied.get(raw_url)
            if asset is None:
                suffix = asset_path.suffix.lower()
                stored_name = f"asset-{len(copied) + 1:02d}{suffix}"
                destination = assets_directory / stored_name
                shutil.copyfile(asset_path, destination)
                destination.chmod(0o600)
                asset = VideoAsset(
                    alt=match.group("alt")[:200],
                    source_url=raw_url,
                    stored_name=stored_name,
                    size=destination.stat().st_size,
                )
                copied[raw_url] = asset
            replacements[raw_url] = f"assets/{asset.stored_name}"

        def replace_image(match: re.Match[str]) -> str:
            replacement = replacements.get(match.group("target"))
            return (
                f"![{match.group('alt')}]({replacement})" if replacement else match.group(0)
            )

        body = IMAGE_PATTERN.sub(replace_image, source.body).strip()
        brief = (
            f"# {source.title}\n\n"
            f"> 来源：羽白工作台 `{source.id}` · 生成于 {now:%Y-%m-%d %H:%M}\n\n"
            f"{body}\n"
        )
        _private_write(directory / "brief.md", brief)
        project = VideoProject(
            id=project_id,
            title=source.title,
            source_id=source.id,
            source_title=source.title,
            status="planning",
            notes=cleaned_notes,
            assets=tuple(copied.values()),
            created_at=now,
            updated_at=now,
            directory=directory,
        )
        return self._write_manifest(project)

    def update_status(self, project_id: str, status: str) -> VideoProject:
        if status not in VIDEO_STATUSES:
            raise ValueError("视频项目状态无效")
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        return self._write_manifest(
            replace(
                project,
                status=status,
                updated_at=datetime.now(SHANGHAI).replace(microsecond=0),
            ),
        )

    def resolve_file(self, project_id: str, relative_name: str) -> Path | None:
        project = self.get(project_id)
        if project is None or not relative_name:
            return None
        relative = PurePosixPath(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        candidate = (project.directory / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(project.directory.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None
