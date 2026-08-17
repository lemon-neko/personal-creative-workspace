"""Private video planning, storyboard and editor handoff packages."""

from __future__ import annotations

import json
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

from app.atomic import atomic_write_text
from app.content import ContentItem


SHANGHAI = ZoneInfo("Asia/Shanghai")
MANIFEST_VERSION = 2
SUPPORTED_MANIFEST_VERSIONS = {1, MANIFEST_VERSION}
VIDEO_STATUSES = {"planning", "editing", "exported", "archived"}
VIDEO_STATUS_LABELS = {
    "planning": "待剪辑",
    "editing": "剪辑中",
    "exported": "已导出",
    "archived": "归档",
}
VIDEO_PLATFORMS = {
    "general": "通用",
    "wechat-channels": "视频号",
    "bilibili": "哔哩哔哩",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
}
VIDEO_ASPECT_RATIOS = {"16:9", "9:16", "1:1"}
VIDEO_TYPES = {
    "knowledge-explainer": "知识讲解",
    "talking-head": "真人口播",
    "mixed": "混合表达",
}
MIN_TARGET_DURATION = 15
MAX_TARGET_DURATION = 3600
MAX_SCENES = 40
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
class VideoScene:
    """One editable scene in a private storyboard."""

    id: str
    duration_seconds: int
    narration: str
    visual: str
    caption: str
    assets: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoProject:
    """A private, file-backed video project linked to one article."""

    id: str
    title: str
    source_id: str
    source_title: str
    status: str
    notes: str
    platform: str
    aspect_ratio: str
    target_duration: int
    video_type: str
    audience: str
    tone: str
    scenes: tuple[VideoScene, ...]
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

    @property
    def planned_duration(self) -> int:
        return sum(scene.duration_seconds for scene in self.scenes)

    @property
    def exports_ready(self) -> bool:
        return (self.directory / "storyboard.yaml").is_file()


def _default_spec() -> dict[str, object]:
    return {
        "platform": "general",
        "aspect_ratio": "16:9",
        "target_duration": 90,
        "video_type": "knowledge-explainer",
        "audience": "对主题感兴趣的普通读者",
        "tone": "清晰、克制、保留个人观察",
    }


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
    atomic_write_text(path, text, mode=0o600)


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


def _validate_project_spec(
    *,
    platform: str,
    aspect_ratio: str,
    target_duration: int,
    video_type: str,
    audience: str,
    tone: str,
) -> None:
    if platform not in VIDEO_PLATFORMS:
        raise ValueError("视频发布平台无效")
    if aspect_ratio not in VIDEO_ASPECT_RATIOS:
        raise ValueError("视频画面比例无效")
    if video_type not in VIDEO_TYPES:
        raise ValueError("视频表达类型无效")
    if not MIN_TARGET_DURATION <= target_duration <= MAX_TARGET_DURATION:
        raise ValueError("视频目标时长需要在 15 秒到 60 分钟之间")
    if not audience.strip() or len(audience.strip()) > 300:
        raise ValueError("视频受众需要填写且不能超过 300 个字符")
    if not tone.strip() or len(tone.strip()) > 300:
        raise ValueError("视频表达风格需要填写且不能超过 300 个字符")


def _parse_scene(value: object, index: int) -> VideoScene:
    if not isinstance(value, dict):
        raise ValueError("视频分镜信息无效")
    scene_id = str(value.get("id", f"scene-{index + 1:02d}"))
    if not re.fullmatch(r"scene-[0-9]{2}", scene_id):
        raise ValueError("视频分镜 ID 无效")
    try:
        duration = int(value.get("duration_seconds", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("视频分镜时长无效") from error
    if not 1 <= duration <= 600:
        raise ValueError("单个分镜时长需要在 1 到 600 秒之间")
    narration = str(value.get("narration", "")).strip()
    visual = str(value.get("visual", "")).strip()
    caption = str(value.get("caption", "")).strip()
    if not narration or len(narration) > 5000:
        raise ValueError("分镜旁白需要填写且不能超过 5000 个字符")
    if not visual or len(visual) > 2000:
        raise ValueError("分镜画面说明需要填写且不能超过 2000 个字符")
    if len(caption) > 500:
        raise ValueError("分镜字幕不能超过 500 个字符")
    raw_assets = value.get("assets", [])
    if not isinstance(raw_assets, (list, tuple)):
        raise ValueError("分镜素材列表无效")
    assets = tuple(str(item).strip() for item in raw_assets if str(item).strip())
    if len(assets) > 10 or any(Path(item).name != item for item in assets):
        raise ValueError("分镜素材文件名无效")
    return VideoScene(scene_id, duration, narration, visual, caption, assets)


def _initial_scenes(source: ContentItem, target_duration: int) -> tuple[VideoScene, ...]:
    paragraphs = tuple(
        value.strip()
        for value in re.split(r"\n\s*\n+", IMAGE_PATTERN.sub("", source.body))
        if value.strip() and not value.lstrip().startswith("#")
    )
    seed = paragraphs[:3] or (source.summary or source.title,)
    duration = max(3, target_duration // len(seed))
    scenes: list[VideoScene] = []
    for index, paragraph in enumerate(seed):
        narration = re.sub(r"[*_`>#-]", "", paragraph).strip()[:900]
        scenes.append(
            VideoScene(
                id=f"scene-{index + 1:02d}",
                duration_seconds=duration,
                narration=narration,
                visual="根据旁白选择配图、关键词或简洁动态图解",
                caption=narration[:80],
            )
        )
    return tuple(scenes)


def _srt_timestamp(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, second = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{second:02d},000"


def _render_srt(scenes: tuple[VideoScene, ...]) -> str:
    cursor = 0
    entries: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        end = cursor + scene.duration_seconds
        caption = scene.caption or scene.narration
        entries.append(
            f"{index}\n{_srt_timestamp(cursor)} --> {_srt_timestamp(end)}\n{caption}\n"
        )
        cursor = end
    return "\n".join(entries)


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
        if not isinstance(raw, dict) or raw.get("version") not in SUPPORTED_MANIFEST_VERSIONS:
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
        defaults = _default_spec()
        platform = str(raw.get("platform", defaults["platform"]))
        aspect_ratio = str(raw.get("aspect_ratio", defaults["aspect_ratio"]))
        video_type = str(raw.get("video_type", defaults["video_type"]))
        try:
            target_duration = int(raw.get("target_duration", defaults["target_duration"]))
        except (TypeError, ValueError) as error:
            raise ValueError("视频目标时长无效") from error
        _validate_project_spec(
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=str(raw.get("audience", defaults["audience"])),
            tone=str(raw.get("tone", defaults["tone"])),
        )
        raw_scenes = raw.get("scenes", [])
        if not isinstance(raw_scenes, list) or len(raw_scenes) > MAX_SCENES:
            raise ValueError("视频分镜列表无效")
        scenes = tuple(_parse_scene(value, index) for index, value in enumerate(raw_scenes))
        if not scenes and raw.get("version") == 1:
            source_title = str(raw.get("source_title", "未命名视频")).strip()[:120]
            scenes = (
                VideoScene(
                    id="scene-01",
                    duration_seconds=target_duration,
                    narration=source_title,
                    visual="根据原文补充画面说明",
                    caption=source_title,
                ),
            )
        return VideoProject(
            id=project_id,
            title=str(raw.get("title", "")).strip()[:120],
            source_id=str(raw.get("source_id", "")).strip()[:160],
            source_title=str(raw.get("source_title", "")).strip()[:120],
            status=status,
            notes=str(raw.get("notes", "")).strip()[:5000],
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=str(raw.get("audience", defaults["audience"])).strip()[:300],
            tone=str(raw.get("tone", defaults["tone"])).strip()[:300],
            scenes=scenes,
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
            "platform": project.platform,
            "aspect_ratio": project.aspect_ratio,
            "target_duration": project.target_duration,
            "video_type": project.video_type,
            "audience": project.audience,
            "tone": project.tone,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
            "brief_file": "brief.md",
            "source_file": "source.md",
            "assets": [
                {
                    "alt": asset.alt,
                    "source_url": asset.source_url,
                    "stored_name": asset.stored_name,
                    "size": asset.size,
                }
                for asset in project.assets
            ],
            "scenes": [
                {
                    "id": scene.id,
                    "duration_seconds": scene.duration_seconds,
                    "narration": scene.narration,
                    "visual": scene.visual,
                    "caption": scene.caption,
                    "assets": list(scene.assets),
                }
                for scene in project.scenes
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

    def create(
        self,
        source: ContentItem,
        *,
        notes: str = "",
        platform: str = "general",
        aspect_ratio: str = "16:9",
        target_duration: int = 90,
        video_type: str = "knowledge-explainer",
        audience: str = "对主题感兴趣的普通读者",
        tone: str = "清晰、克制、保留个人观察",
    ) -> VideoProject:
        """Create a private planning package without modifying the source article."""

        if source.kind != "article":
            raise ValueError("视频项目只能从文章草稿或已成稿创建")
        cleaned_notes = notes.strip()
        if len(cleaned_notes) > 5000:
            raise ValueError("剪辑备注不能超过 5000 个字符")
        _validate_project_spec(
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=audience,
            tone=tone,
        )
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
        _private_write(directory / "source.md", brief)
        initial_scenes = _initial_scenes(source, target_duration)
        copied_assets = tuple(copied.values())
        initial_scenes = tuple(
            replace(
                scene,
                assets=(copied_assets[index].stored_name,)
                if index < len(copied_assets)
                else (),
            )
            for index, scene in enumerate(initial_scenes)
        )
        project = VideoProject(
            id=project_id,
            title=source.title,
            source_id=source.id,
            source_title=source.title,
            status="planning",
            notes=cleaned_notes,
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=audience.strip(),
            tone=tone.strip(),
            scenes=initial_scenes,
            assets=copied_assets,
            created_at=now,
            updated_at=now,
            directory=directory,
        )
        project = self._write_manifest(project)
        self._write_exports(project)
        return project

    def update_plan(
        self,
        project_id: str,
        *,
        platform: str,
        aspect_ratio: str,
        target_duration: int,
        video_type: str,
        audience: str,
        tone: str,
        notes: str,
        scenes: tuple[VideoScene, ...],
    ) -> VideoProject:
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        if len(notes.strip()) > 5000:
            raise ValueError("剪辑备注不能超过 5000 个字符")
        _validate_project_spec(
            platform=platform,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            video_type=video_type,
            audience=audience,
            tone=tone,
        )
        if not scenes or len(scenes) > MAX_SCENES:
            raise ValueError("视频分镜需要 1 到 40 个")
        normalized = tuple(
            _parse_scene(
                {
                    "id": f"scene-{index + 1:02d}",
                    "duration_seconds": scene.duration_seconds,
                    "narration": scene.narration,
                    "visual": scene.visual,
                    "caption": scene.caption,
                    "assets": scene.assets,
                },
                index,
            )
            for index, scene in enumerate(scenes)
        )
        available_assets = {asset.stored_name for asset in project.assets}
        if any(name not in available_assets for scene in normalized for name in scene.assets):
            raise ValueError("分镜引用了不属于当前项目的素材")
        updated = self._write_manifest(
            replace(
                project,
                platform=platform,
                aspect_ratio=aspect_ratio,
                target_duration=target_duration,
                video_type=video_type,
                audience=audience.strip(),
                tone=tone.strip(),
                notes=notes.strip(),
                scenes=normalized,
                updated_at=datetime.now(SHANGHAI).replace(microsecond=0),
            )
        )
        self._write_exports(updated)
        return updated

    def _write_exports(self, project: VideoProject) -> None:
        storyboard = {
            "version": 1,
            "project_id": project.id,
            "title": project.title,
            "platform": project.platform,
            "aspect_ratio": project.aspect_ratio,
            "target_duration": project.target_duration,
            "video_type": project.video_type,
            "audience": project.audience,
            "tone": project.tone,
            "scenes": [
                {
                    "id": scene.id,
                    "duration": scene.duration_seconds,
                    "narration": scene.narration,
                    "visual": scene.visual,
                    "caption": scene.caption,
                    "assets": list(scene.assets),
                }
                for scene in project.scenes
            ],
        }
        _private_write(
            project.directory / "storyboard.yaml",
            yaml.safe_dump(storyboard, allow_unicode=True, sort_keys=False),
        )
        narration = "\n\n".join(
            f"## {scene.id} · {scene.duration_seconds} 秒\n\n{scene.narration}"
            for scene in project.scenes
        )
        _private_write(project.directory / "narration.md", f"# {project.title}\n\n{narration}\n")
        _private_write(project.directory / "captions.srt", _render_srt(project.scenes))
        props = {
            "title": project.title,
            "platform": project.platform,
            "aspectRatio": project.aspect_ratio,
            "targetDuration": project.target_duration,
            "audience": project.audience,
            "tone": project.tone,
            "scenes": [
                {
                    "id": scene.id,
                    "durationInSeconds": scene.duration_seconds,
                    "narration": scene.narration,
                    "visual": scene.visual,
                    "caption": scene.caption,
                    "assets": [f"assets/{name}" for name in scene.assets],
                }
                for scene in project.scenes
            ],
        }
        _private_write(
            project.directory / "remotion-props.json",
            json.dumps(props, ensure_ascii=False, indent=2) + "\n",
        )
        source_path = project.directory / "source.md"
        if not source_path.is_file():
            legacy_brief = project.directory / "brief.md"
            source_text = (
                legacy_brief.read_text(encoding="utf-8")
                if legacy_brief.is_file()
                else f"# {project.source_title}\n"
            )
            _private_write(source_path, source_text)
        else:
            source_text = source_path.read_text(encoding="utf-8")
        scene_sections = "\n\n".join(
            (
                f"### 镜头 {index} · {scene.duration_seconds} 秒\n\n"
                f"- 旁白：{scene.narration}\n"
                f"- 画面：{scene.visual}\n"
                f"- 字幕：{scene.caption or '跟随旁白'}\n"
                f"- 素材：{', '.join(scene.assets) or '待补充'}"
            )
            for index, scene in enumerate(project.scenes, start=1)
        )
        brief = (
            f"# {project.title}\n\n"
            f"> 来源：羽白工作台 `{project.source_id}` · 更新于 {project.updated_at:%Y-%m-%d %H:%M}\n\n"
            "## 视频规格\n\n"
            f"- 平台：{VIDEO_PLATFORMS[project.platform]}\n"
            f"- 比例：{project.aspect_ratio}\n"
            f"- 类型：{VIDEO_TYPES[project.video_type]}\n"
            f"- 目标时长：{project.target_duration} 秒\n"
            f"- 当前分镜时长：{project.planned_duration} 秒\n"
            f"- 受众：{project.audience}\n"
            f"- 风格：{project.tone}\n"
            f"- 备注：{project.notes or '无'}\n\n"
            f"## 镜头清单\n\n{scene_sections}\n\n"
            f"## 来源文章\n\n{source_text.strip()}\n"
        )
        _private_write(project.directory / "brief.md", brief)

    def update_status(self, project_id: str, status: str) -> VideoProject:
        if status not in VIDEO_STATUSES:
            raise ValueError("视频项目状态无效")
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        updated = self._write_manifest(
            replace(
                project,
                status=status,
                updated_at=datetime.now(SHANGHAI).replace(microsecond=0),
            ),
        )
        if updated.scenes:
            self._write_exports(updated)
        return updated

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
