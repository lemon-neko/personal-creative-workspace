"""Plugin-free bridge between the private workspace and an Obsidian vault."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import yaml

from app.atomic import atomic_write_bytes, atomic_write_text, content_lock
from app.content import (
    MANAGED_LINKS_END,
    MANAGED_LINKS_START,
    ContentItem,
    combine_managed_links,
    load_items,
    semantic_revision,
    split_managed_links,
)
from app.knowledge_store import (
    CARD_TYPES,
    MAP_KINDS,
    KnowledgeCard,
    KnowledgeMap,
    create_knowledge_card,
    create_knowledge_map,
    knowledge_semantic_revision,
    load_knowledge_store,
    reconcile_knowledge_external_edit,
)
from app.workspace import (
    SHANGHAI,
    ContentConflictError,
    create_item,
    reconcile_external_edit,
)


OBSIDIAN_APP = Path("/Applications/Obsidian.app")
OBSIDIAN_CONFIG = Path.home() / "Library" / "Application Support" / "obsidian"
INBOX_LIMIT = 50_000
LEGACY_GENERATED_INDEX = "工作台知识导航.md"
KNOWLEDGE_HOME = "知识首页.md"
KNOWLEDGE_TEMPLATE_TYPES = {"knowledge-card", "knowledge-map"}
LEGACY_KNOWLEDGE_FIELDS = {
    "subjects",
    "concepts",
    "relations",
    "knowledge_updated_at",
    "knowledge_source_revision",
}


@dataclass(frozen=True)
class SemanticRevision:
    value: str


@dataclass(frozen=True)
class VaultFileState:
    relative_path: str
    item_id: str
    revision: SemanticRevision
    metadata_updated_at: str
    observed_mtime_ns: int
    externally_changed_at: str | None = None


@dataclass(frozen=True)
class InboxDraft:
    id: str
    relative_path: str
    title: str
    body: str
    preview: str
    revision: str
    size: int
    error: str = ""


@dataclass(frozen=True)
class KnowledgeInboxDraft:
    id: str
    relative_path: str
    workspace_type: str
    title: str
    body: str
    preview: str
    revision: str
    card_type: str = "concept"
    map_kind: str = "topic"
    summary: str = ""
    subjects: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class KnowledgeReconciliation:
    item_id: str
    title: str
    subjects: tuple[str, ...]
    concepts: tuple[str, ...]
    card_ids: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class VaultRename:
    item_id: str
    title: str
    source: str
    destination: str
    conflict: str = ""


@dataclass(frozen=True)
class ObsidianMigrationPreview:
    reconciliations: tuple[KnowledgeReconciliation, ...]
    renames: tuple[VaultRename, ...]
    can_apply: bool
    rollback_available: bool = False


@dataclass(frozen=True)
class ObsidianLinkProjection:
    source_id: str
    relative_path: str
    block: str


@dataclass(frozen=True)
class ObsidianIntegrationState:
    installed: bool
    version: str
    vault_registered: bool
    vault_path: str
    last_scan_at: str
    tracked_files: int
    external_changes: int
    inbox_count: int
    knowledge_inbox_count: int
    issues: tuple[str, ...]


def inbox_directory(content_root: Path) -> Path:
    return content_root / "sources" / "inbox"


def knowledge_inbox_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "inbox"


def templates_directory(content_root: Path) -> Path:
    return content_root / "_templates"


def obsidian_index_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "indexes" / "obsidian"


def obsidian_uri(path: Path) -> str:
    return f"obsidian://open?path={quote(str(path.resolve()), safe='')}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _app_version() -> str:
    info = OBSIDIAN_APP / "Contents" / "Info.plist"
    try:
        with info.open("rb") as stream:
            return str(plistlib.load(stream).get("CFBundleShortVersionString", ""))
    except (OSError, plistlib.InvalidFileException):
        return ""


def _registered_vault(content_root: Path) -> bool:
    config = OBSIDIAN_CONFIG / "obsidian.json"
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    for value in (payload.get("vaults") or {}).values():
        try:
            if (
                Path(str(value.get("path", ""))).expanduser().resolve()
                == content_root.resolve()
            ):
                return True
        except (AttributeError, OSError):
            continue
    return False


def _read_front_matter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as error:
        raise ValueError("front matter 缺少结束标记") from error
    metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(metadata, dict):
        raise ValueError("front matter 必须是键值映射")
    return metadata, "\n".join(lines[end + 1 :]).strip()


def _draft_title(metadata: dict, body: str, fallback: str) -> str:
    value = metadata.get("title")
    if isinstance(value, str) and value.strip():
        return value.strip()[:120]
    heading = re.search(r"^#{1,6}\s+(.+)$", body, flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip()[:120]
    sentence = (
        re.sub(r"[#>*_`~|]+", " ", body).strip().splitlines()[0] if body.strip() else ""
    )
    return (sentence.strip() or fallback)[:120]


def _readable_filename(title: str, item_id: str) -> str:
    readable = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", title.strip())
    readable = re.sub(r"\s+", " ", readable).strip(" .-")[:72] or "未命名知识"
    suffix = item_id.rsplit("-", 1)[-1][:10]
    return f"{readable}--{suffix}.md"


def _rewrite_links(text: str, mapping: dict[str, str]) -> str:
    updated = text
    for old, new in sorted(mapping.items(), key=lambda value: len(value[0]), reverse=True):
        old_encoded = quote(old, safe="/")
        new_encoded = quote(new, safe="/")
        updated = re.sub(
            rf"(?<=\()({re.escape(old)}|{re.escape(old_encoded)})(?=[)#\s])",
            lambda match: new_encoded if match.group(0) == old_encoded else new,
            updated,
        )
        updated = updated.replace(f"[[{old.removesuffix('.md')}", f"[[{new.removesuffix('.md')}")
    return updated


class ObsidianBridge:
    """Track external edits without storing private note bodies in SQLite."""

    def __init__(self, data_root: Path, content_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.content_root = content_root.resolve()
        self.database_path = self.data_root / "workspace.db"
        inbox_directory(self.content_root).mkdir(
            parents=True, exist_ok=True, mode=0o700
        )
        inbox_directory(self.content_root).chmod(0o700)
        knowledge_inbox_directory(self.content_root).mkdir(
            parents=True, exist_ok=True, mode=0o700
        )
        knowledge_inbox_directory(self.content_root).chmod(0o700)
        self.migration_root = self.data_root / "migrations" / "obsidian-knowledge"
        self.migration_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.migration_root.chmod(0o700)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS obsidian_file_state (
                    relative_path TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    semantic_revision TEXT NOT NULL,
                    metadata_updated_at TEXT NOT NULL,
                    observed_mtime_ns INTEGER NOT NULL,
                    externally_changed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS obsidian_integration_state (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    last_scan_at TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO obsidian_integration_state(id) VALUES(1);
                """,
            )
        self.database_path.chmod(0o600)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def inbox(self) -> tuple[InboxDraft, ...]:
        drafts: list[InboxDraft] = []
        root = inbox_directory(self.content_root)
        for path in sorted(
            root.glob("*.md"), key=lambda value: value.stat().st_mtime, reverse=True
        ):
            relative = path.relative_to(self.content_root).as_posix()
            data = path.read_bytes()
            draft_id = hashlib.sha256(relative.encode()).hexdigest()[:20]
            error = ""
            body = ""
            title = path.stem
            if len(data) > INBOX_LIMIT * 4:
                error = "文件超过收件箱大小限制"
            else:
                try:
                    text = data.decode("utf-8")
                    metadata, body = _read_front_matter(text)
                    if not body:
                        raise ValueError("正文不能为空")
                    title = _draft_title(metadata, body, path.stem)
                except (UnicodeError, ValueError, yaml.YAMLError) as exception:
                    error = str(exception)
            drafts.append(
                InboxDraft(
                    id=draft_id,
                    relative_path=relative,
                    title=title,
                    body=body,
                    preview=body[:240],
                    revision=_sha256(data),
                    size=len(data),
                    error=error,
                ),
            )
        return tuple(drafts)

    def knowledge_inbox(self) -> tuple[KnowledgeInboxDraft, ...]:
        drafts: list[KnowledgeInboxDraft] = []
        root = knowledge_inbox_directory(self.content_root)
        for path in sorted(
            root.glob("*.md"), key=lambda value: value.stat().st_mtime, reverse=True
        ):
            relative = path.relative_to(self.content_root).as_posix()
            data = path.read_bytes()
            draft_id = hashlib.sha256(relative.encode()).hexdigest()[:20]
            error = ""
            metadata: dict = {}
            body = ""
            title = path.stem
            workspace_type = ""
            try:
                if len(data) > INBOX_LIMIT * 4:
                    raise ValueError("文件超过知识模板大小限制")
                metadata, body = _read_front_matter(data.decode("utf-8"))
                workspace_type = str(metadata.get("workspace_type", "")).strip()
                if workspace_type not in KNOWLEDGE_TEMPLATE_TYPES:
                    raise ValueError("请选择知识卡或知识地图模板后再导入")
                title = _draft_title(metadata, body, path.stem)
                if workspace_type == "knowledge-card" and not body:
                    raise ValueError("知识卡正文不能为空")
            except (UnicodeError, ValueError, yaml.YAMLError) as exception:
                error = str(exception)
            raw_subjects = metadata.get("subjects", [])
            raw_concepts = metadata.get("concepts", [])
            subjects = tuple(
                str(value).strip()
                for value in raw_subjects
                if isinstance(value, str) and str(value).strip()
            ) if isinstance(raw_subjects, list) else ()
            concepts = tuple(
                str(value).strip()
                for value in raw_concepts
                if isinstance(value, str) and str(value).strip()
            ) if isinstance(raw_concepts, list) else ()
            drafts.append(
                KnowledgeInboxDraft(
                    id=draft_id,
                    relative_path=relative,
                    workspace_type=workspace_type,
                    title=title,
                    body=body,
                    preview=body[:240],
                    revision=_sha256(data),
                    card_type=str(metadata.get("card_type", "concept")).strip(),
                    map_kind=str(metadata.get("kind", "topic")).strip(),
                    summary=str(metadata.get("summary", "")).strip()[:500],
                    subjects=subjects,
                    concepts=concepts,
                    error=error,
                )
            )
        return tuple(drafts)

    def _stored_states(self) -> dict[str, sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM obsidian_file_state").fetchall()
        return {str(row["relative_path"]): row for row in rows}

    def scan(self) -> ObsidianIntegrationState:
        collection = load_items(self.content_root)
        states = self._stored_states()
        states_by_id = {str(value["item_id"]): value for value in states.values()}
        now = datetime.now(SHANGHAI).replace(microsecond=0)
        external_changes = 0
        observed: list[VaultFileState] = []
        issues = [
            f"{value.source.name}: {value.message}" for value in collection.diagnostics
        ]

        for item in collection.items:
            relative = item.source.relative_to(self.content_root).as_posix()
            revision = semantic_revision(item)
            stored = states.get(relative) or states_by_id.get(item.id)
            external_at = (
                str(stored["externally_changed_at"])
                if stored and stored["externally_changed_at"]
                else None
            )
            if stored and str(stored["relative_path"]) != relative:
                external_at = now.isoformat()
                external_changes += 1
            if stored and stored["semantic_revision"] != revision:
                if str(stored["metadata_updated_at"]) == item.updated_at.isoformat():
                    try:
                        item = reconcile_external_edit(
                            self.content_root,
                            item.id,
                            expected_revision=revision,
                            now=now,
                        )
                        external_at = now.isoformat()
                        external_changes += 1
                    except (ContentConflictError, KeyError, ValueError) as error:
                        issues.append(f"{item.source.name}: {error}")
                revision = semantic_revision(item)
            expected_parent = (
                self.content_root / "archive"
                if item.status == "archived"
                else self.content_root / "sources" / "thoughts"
                if item.kind == "thought"
                else self.content_root / "outputs" / "articles"
                if item.kind == "article"
                else self.content_root / "outputs" / "reviews"
            )
            if item.source.parent != expected_parent:
                issues.append(f"{item.source.name}: 状态或类型与生命周期目录不一致")
            mode = item.source.stat().st_mode & 0o777
            if mode != 0o600:
                issues.append(f"{item.source.name}: 权限应为 0600，当前为 {mode:04o}")
            observed.append(
                VaultFileState(
                    relative,
                    item.id,
                    SemanticRevision(revision),
                    item.updated_at.isoformat(),
                    item.source.stat().st_mtime_ns,
                    external_at,
                ),
            )

        store = load_knowledge_store(self.content_root)
        issues.extend(store.diagnostics)
        for value in (*store.maps, *store.cards):
            relative = value.source.relative_to(self.content_root).as_posix()
            revision = knowledge_semantic_revision(value)
            stored = states.get(relative) or states_by_id.get(value.id)
            external_at = (
                str(stored["externally_changed_at"])
                if stored and stored["externally_changed_at"]
                else None
            )
            renamed = bool(stored and str(stored["relative_path"]) != relative)
            if renamed:
                external_at = now.isoformat()
                external_changes += 1
            if stored and stored["semantic_revision"] != revision:
                if str(stored["metadata_updated_at"]) == value.updated_at.isoformat():
                    try:
                        value = reconcile_knowledge_external_edit(
                            self.content_root,
                            value.id,
                            expected_revision=revision,
                            now=now,
                        )
                        external_at = now.isoformat()
                        external_changes += 1
                    except (KeyError, ValueError) as error:
                        issues.append(f"{value.source.name}: {error}")
                revision = knowledge_semantic_revision(value)
            expected_parent = (
                self.content_root / "knowledge" / "cards"
                if isinstance(value, KnowledgeCard)
                else self.content_root / "knowledge" / "maps"
            )
            if value.source.parent != expected_parent:
                issues.append(f"{value.source.name}: 知识类型与目录不一致")
            mode = value.source.stat().st_mode & 0o777
            if mode != 0o600:
                issues.append(
                    f"{value.source.name}: 权限应为 0600，当前为 {mode:04o}"
                )
            observed.append(
                VaultFileState(
                    relative,
                    value.id,
                    SemanticRevision(revision),
                    value.updated_at.isoformat(),
                    value.source.stat().st_mtime_ns,
                    external_at,
                )
            )

        content_mode = self.content_root.stat().st_mode & 0o777
        if content_mode != 0o700:
            issues.append(f"内容目录权限应为 0700，当前为 {content_mode:04o}")
        with self.connect() as connection:
            connection.execute("DELETE FROM obsidian_file_state")
            connection.executemany(
                """INSERT INTO obsidian_file_state(
                relative_path,item_id,semantic_revision,metadata_updated_at,
                observed_mtime_ns,externally_changed_at) VALUES(?,?,?,?,?,?)""",
                [
                    (
                        value.relative_path,
                        value.item_id,
                        value.revision.value,
                        value.metadata_updated_at,
                        value.observed_mtime_ns,
                        value.externally_changed_at,
                    )
                    for value in observed
                ],
            )
            connection.execute(
                "UPDATE obsidian_integration_state SET last_scan_at=? WHERE id=1",
                (now.isoformat(),),
            )
        return self.state(issues=tuple(issues), external_changes=external_changes)

    def state(
        self,
        *,
        issues: tuple[str, ...] = (),
        external_changes: int = 0,
    ) -> ObsidianIntegrationState:
        with self.connect() as connection:
            last_scan = connection.execute(
                "SELECT last_scan_at FROM obsidian_integration_state WHERE id=1",
            ).fetchone()
            tracked = connection.execute(
                "SELECT COUNT(*) FROM obsidian_file_state"
            ).fetchone()[0]
        return ObsidianIntegrationState(
            installed=OBSIDIAN_APP.is_dir(),
            version=_app_version(),
            vault_registered=_registered_vault(self.content_root),
            vault_path=str(self.content_root),
            last_scan_at=str(last_scan[0]) if last_scan else "",
            tracked_files=int(tracked),
            external_changes=external_changes,
            inbox_count=len(self.inbox()),
            knowledge_inbox_count=len(self.knowledge_inbox()),
            issues=issues,
        )

    def repair_permissions(self) -> int:
        changed = 0
        for root, directories, files in os.walk(self.content_root):
            current = Path(root)
            if current.name == ".obsidian":
                directories[:] = []
                continue
            if current.stat().st_mode & 0o777 != 0o700:
                current.chmod(0o700)
                changed += 1
            for name in files:
                path = current / name
                if path.name == ".content.lock" or path.suffix.lower() in {
                    ".md",
                    ".yaml",
                    ".yml",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                }:
                    if path.stat().st_mode & 0o777 != 0o600:
                        path.chmod(0o600)
                        changed += 1
        return changed

    def _resource_index(self) -> dict[str, tuple[str, str]]:
        resources: dict[str, tuple[str, str]] = {}
        for item in load_items(self.content_root).items:
            resources[item.id] = (
                item.title,
                item.source.relative_to(self.content_root).as_posix(),
            )
        store = load_knowledge_store(self.content_root)
        for card in store.cards:
            resources[card.id] = (
                card.title,
                card.source.relative_to(self.content_root).as_posix(),
            )
        for item in store.maps:
            resources[item.id] = (
                item.title,
                item.source.relative_to(self.content_root).as_posix(),
            )
        return resources

    @staticmethod
    def _managed_block(links: list[tuple[str, str, str]]) -> str:
        if not links:
            return ""
        rows = [
            MANAGED_LINKS_START,
            "",
            "## 工作台关联",
            "",
            "> 此区块由羽白工作台维护，请勿手动修改。",
            "",
        ]
        for relation, title, relative in links:
            rows.append(f"- **{relation}**：[ {title} ]({quote(relative, safe='/')})")
        rows.extend(["", MANAGED_LINKS_END])
        return "\n".join(rows)

    def projections(self) -> tuple[ObsidianLinkProjection, ...]:
        collection = load_items(self.content_root)
        store = load_knowledge_store(self.content_root)
        resources = self._resource_index()
        projections: list[ObsidianLinkProjection] = []

        def resolve(target_id: str, relation: str) -> tuple[str, str, str] | None:
            target = resources.get(target_id)
            return (relation, target[0], target[1]) if target else None

        for item in collection.items:
            projections.append(
                ObsidianLinkProjection(
                    item.id,
                    item.source.relative_to(self.content_root).as_posix(),
                    "",
                ),
            )
        for card in store.cards:
            links = []
            for target_id, label in (
                *((source_id, "原始来源") for source_id in card.source_ids),
                *((map_id, "知识地图") for map_id in card.map_ids),
                *((edge.target_id, edge.relation) for edge in card.relations),
            ):
                value = resolve(target_id, label)
                if value:
                    links.append(value)
            if card.superseded_by:
                value = resolve(card.superseded_by, "已被替代")
                if value:
                    links.append(value)
            projections.append(
                ObsidianLinkProjection(
                    card.id,
                    card.source.relative_to(self.content_root).as_posix(),
                    self._managed_block(links),
                ),
            )
        for knowledge_map in store.maps:
            links = []
            if knowledge_map.kind == "topic":
                for parent_id in knowledge_map.parent_ids:
                    value = resolve(parent_id, "父级学科")
                    if value:
                        links.append(value)
            else:
                for child in store.maps:
                    if child.kind == "topic" and knowledge_map.id in child.parent_ids:
                        value = resolve(child.id, "下级主题")
                        if value:
                            links.append(value)
            for card in store.cards:
                if knowledge_map.kind == "topic" and knowledge_map.id in card.map_ids:
                    value = resolve(card.id, "知识卡")
                    if value:
                        links.append(value)
            projections.append(
                ObsidianLinkProjection(
                    knowledge_map.id,
                    knowledge_map.source.relative_to(self.content_root).as_posix(),
                    self._managed_block(links),
                ),
            )
        return tuple(projections)

    def rebuild_links(self) -> int:
        changed = 0
        with content_lock(self.content_root):
            for projection in self.projections():
                path = (self.content_root / projection.relative_path).resolve()
                if (
                    path.parent
                    == self.content_root / "knowledge" / "indexes" / "obsidian"
                ):
                    continue
                text = path.read_text(encoding="utf-8")
                metadata, raw_body = _read_front_matter(text)
                authored, current = split_managed_links(raw_body)
                if current == projection.block:
                    continue
                front = yaml.safe_dump(
                    metadata, allow_unicode=True, sort_keys=False
                ).strip()
                combined = combine_managed_links(authored, projection.block)
                atomic_write_text(path, f"---\n{front}\n---\n\n{combined}\n")
                changed += 1
            self._write_navigation_index()
        return changed

    def _write_navigation_index(self) -> None:
        store = load_knowledge_store(self.content_root)
        subjects = tuple(item for item in store.maps if item.kind == "subject")
        rows = [
            "---",
            "workspace_generated: true",
            "title: 知识首页",
            "---",
            "",
            "# 知识首页",
            "",
            "> 从学科进入主题，再进入知识卡和原始来源。本页只维护第一层入口。",
            "",
            "## 学科地图",
            "",
        ]
        for value in subjects:
            relative = value.source.relative_to(self.content_root).as_posix()
            rows.append(f"- [{value.title}]({quote(relative, safe='/')}) — {value.summary}")
        if not subjects:
            rows.append("- 暂无学科地图")
        directory = obsidian_index_directory(self.content_root)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        legacy = directory / LEGACY_GENERATED_INDEX
        legacy.unlink(missing_ok=True)
        atomic_write_text(self.content_root / KNOWLEDGE_HOME, "\n".join(rows).strip() + "\n")

    def initialize_templates(self) -> int:
        """Install Core Templates-compatible drafts without touching .obsidian."""

        directory = templates_directory(self.content_root)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        templates = {
            "知识卡模板.md": """---
workspace_type: knowledge-card
title: "{{title}}"
card_type: concept
subjects: []
concepts: []
---

# {{title}}

在这里写一个可以独立理解、可以追溯来源的知识结论。
""",
            "主题地图模板.md": """---
workspace_type: knowledge-map
title: "{{title}}"
kind: topic
summary: 请用一句话说明这个主题讨论什么
---

# {{title}}

说明这个主题的边界、核心问题和希望继续补充的方向。
""",
            "学科地图模板.md": """---
workspace_type: knowledge-map
title: "{{title}}"
kind: subject
summary: 请用一句话说明这个学科如何组织知识
---

# {{title}}

说明这个学科在个人知识库中的范围。
""",
        }
        changed = 0
        for name, text in templates.items():
            path = directory / name
            if path.exists() and path.read_text(encoding="utf-8") == text:
                continue
            atomic_write_text(path, text)
            changed += 1
        return changed

    def import_inbox(
        self,
        draft_id: str,
        *,
        expected_revision: str,
        title: str = "",
        tags: str = "",
        category: str = "",
    ) -> ContentItem:
        draft = next((value for value in self.inbox() if value.id == draft_id), None)
        if draft is None or draft.error:
            raise ValueError("收件箱文件不存在或无法导入")
        source = (self.content_root / draft.relative_path).resolve()
        if source.parent != inbox_directory(self.content_root).resolve():
            raise ValueError("收件箱路径无效")
        backups: dict[Path, bytes] = {}
        created: ContentItem | None = None
        with content_lock(self.content_root):
            data = source.read_bytes()
            if _sha256(data) != expected_revision:
                raise ValueError("收件箱内容已经变化，请刷新后重试")
            metadata, body = _read_front_matter(data.decode("utf-8"))
            selected_title = title.strip() or _draft_title(metadata, body, source.stem)
            raw_tags = tags or ",".join(
                value for value in metadata.get("tags", []) if isinstance(value, str)
            )
            selected_category = category or (
                str(metadata.get("category", "")).strip()
                if metadata.get("category") is not None
                else ""
            )
            try:
                created = create_item(
                    self.content_root,
                    body=body,
                    title=selected_title,
                    tags=raw_tags,
                    category=selected_category,
                )
                old = draft.relative_path
                new = created.source.relative_to(self.content_root).as_posix()
                old_encoded = quote(old, safe="/")
                new_encoded = quote(new, safe="/")
                for path in self.content_root.rglob("*.md"):
                    if (
                        path == source
                        or path == created.source
                        or ".obsidian" in path.parts
                    ):
                        continue
                    original = path.read_bytes()
                    text = original.decode("utf-8")
                    updated = re.sub(
                        rf"(?<=\()({re.escape(old)}|{re.escape(old_encoded)})(?=[)#\s])",
                        lambda match: (
                            new_encoded if match.group(0) == old_encoded else new
                        ),
                        text,
                    )
                    if updated != text:
                        backups[path] = original
                        atomic_write_text(path, updated)
                source.unlink()
            except Exception:
                for path, original in backups.items():
                    atomic_write_bytes(path, original)
                if created is not None:
                    created.source.unlink(missing_ok=True)
                raise
        return created

    def import_knowledge_inbox(
        self,
        draft_id: str,
        *,
        expected_revision: str,
        title: str,
        source_ids: tuple[str, ...] = (),
        map_ids: tuple[str, ...] = (),
        parent_ids: tuple[str, ...] = (),
        subjects: tuple[str, ...] = (),
        concepts: tuple[str, ...] = (),
        summary: str = "",
    ) -> KnowledgeCard | KnowledgeMap:
        draft = next(
            (value for value in self.knowledge_inbox() if value.id == draft_id),
            None,
        )
        if draft is None or draft.error:
            raise ValueError("知识模板不存在或无法导入")
        source = (self.content_root / draft.relative_path).resolve()
        if source.parent != knowledge_inbox_directory(self.content_root).resolve():
            raise ValueError("知识模板路径无效")
        created: KnowledgeCard | KnowledgeMap | None = None
        backups: dict[Path, bytes] = {}
        with content_lock(self.content_root):
            data = source.read_bytes()
            if _sha256(data) != expected_revision:
                raise ValueError("知识模板已经变化，请刷新后重试")
            try:
                if draft.workspace_type == "knowledge-card":
                    card_type = draft.card_type if draft.card_type in CARD_TYPES else "concept"
                    created = create_knowledge_card(
                        self.content_root,
                        title=title.strip() or draft.title,
                        body=draft.body,
                        card_type=card_type,
                        subjects=subjects or draft.subjects,
                        concepts=concepts or draft.concepts,
                        source_ids=source_ids,
                        map_ids=map_ids,
                    )
                else:
                    map_kind = draft.map_kind if draft.map_kind in MAP_KINDS else "topic"
                    created = create_knowledge_map(
                        self.content_root,
                        title=title.strip() or draft.title,
                        kind=map_kind,
                        summary=summary.strip() or draft.summary,
                        parent_ids=parent_ids,
                        body=draft.body,
                    )
                old = draft.relative_path
                new = created.source.relative_to(self.content_root).as_posix()
                for path in self.content_root.rglob("*.md"):
                    if path in {source, created.source} or ".obsidian" in path.parts:
                        continue
                    original = path.read_bytes()
                    updated = _rewrite_links(original.decode("utf-8"), {old: new})
                    if updated != original.decode("utf-8"):
                        backups[path] = original
                        atomic_write_text(path, updated)
                source.unlink()
            except Exception:
                for path, original in backups.items():
                    atomic_write_bytes(path, original)
                if created is not None:
                    created.source.unlink(missing_ok=True)
                raise
        return created

    def migration_preview(self) -> ObsidianMigrationPreview:
        collection = load_items(self.content_root)
        store = load_knowledge_store(self.content_root)
        reconciliations: list[KnowledgeReconciliation] = []
        for item in collection.items:
            if item.kind == "weekly-review" or item.status == "archived":
                continue
            if not (item.subjects or item.concepts or item.relations):
                continue
            cards = tuple(card for card in store.cards if item.id in card.source_ids)
            card_subjects = {value for card in cards for value in card.subjects}
            card_concepts = {value for card in cards for value in card.concepts}
            relation_keys = {
                (edge.target_id, edge.relation)
                for card in cards
                for edge in card.relations
            }
            relation_covered = all(
                (edge.target_id, edge.relation) in relation_keys
                for edge in item.relations
            )
            if not cards:
                state = "uncovered"
            elif (
                set(item.subjects) <= card_subjects
                and set(item.concepts) <= card_concepts
                and relation_covered
            ):
                state = "covered"
            else:
                state = "conflict"
            reconciliations.append(
                KnowledgeReconciliation(
                    item.id,
                    item.title,
                    item.subjects,
                    item.concepts,
                    tuple(card.id for card in cards),
                    state,
                )
            )

        values: tuple[ContentItem | KnowledgeCard | KnowledgeMap, ...] = (
            *tuple(item for item in collection.items if item.status != "archived"),
            *tuple(card for card in store.cards if card.status != "archived"),
            *store.maps,
        )
        renames: list[VaultRename] = []
        reserved_destinations: set[Path] = set()
        for value in values:
            destination = value.source.with_name(_readable_filename(value.title, value.id))
            if destination == value.source:
                continue
            conflict = ""
            if destination.exists() and destination != value.source:
                conflict = "目标文件已存在"
            if destination in reserved_destinations:
                conflict = "多个文件会得到相同名称"
            reserved_destinations.add(destination)
            renames.append(
                VaultRename(
                    value.id,
                    value.title,
                    value.source.relative_to(self.content_root).as_posix(),
                    destination.relative_to(self.content_root).as_posix(),
                    conflict,
                )
            )
        return ObsidianMigrationPreview(
            tuple(reconciliations),
            tuple(renames),
            not any(value.conflict for value in renames),
            any(self.migration_root.glob("*/manifest.json")),
        )

    def _snapshot_markdown(self, directory: Path, manifest: dict) -> None:
        files = []
        backup_root = directory / "files"
        for path in sorted(self.content_root.rglob("*.md")):
            if ".obsidian" in path.parts:
                continue
            relative = path.relative_to(self.content_root)
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, destination)
            destination.chmod(0o600)
            files.append(relative.as_posix())
        manifest["files"] = files
        atomic_write_text(
            directory / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    def _restore_snapshot(self, directory: Path) -> None:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for relative in manifest.get("created_paths", []):
            candidate = (self.content_root / str(relative)).resolve()
            if candidate.is_relative_to(self.content_root):
                candidate.unlink(missing_ok=True)
        for relative in manifest.get("files", []):
            source = directory / "files" / str(relative)
            destination = self.content_root / str(relative)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_bytes(destination, source.read_bytes())

    def apply_migration(self, confirmation: str) -> Path:
        if confirmation.strip() != "整理知识库":
            raise ValueError("请输入“整理知识库”确认")
        preview = self.migration_preview()
        if not preview.can_apply:
            raise ValueError("存在文件名冲突，请先处理后再应用")
        stamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S-%f")
        snapshot = self.migration_root / stamp
        snapshot.mkdir(parents=True, mode=0o700)
        mapping = {value.source: value.destination for value in preview.renames}
        manifest = {
            "created_at": datetime.now(SHANGHAI).isoformat(),
            "renames": mapping,
            "cleaned_ids": [
                value.item_id
                for value in preview.reconciliations
                if value.state == "covered"
            ],
            "created_paths": list(mapping.values()),
        }
        self._snapshot_markdown(snapshot, manifest)
        try:
            with content_lock(self.content_root):
                for old, new in mapping.items():
                    source = self.content_root / old
                    destination = self.content_root / new
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    source.replace(destination)
                    destination.chmod(0o600)
                for path in self.content_root.rglob("*.md"):
                    if ".obsidian" in path.parts:
                        continue
                    original = path.read_text(encoding="utf-8")
                    updated = _rewrite_links(original, mapping)
                    if updated != original:
                        atomic_write_text(path, updated)
                cleaned_ids = set(manifest["cleaned_ids"])
                for item in load_items(self.content_root).items:
                    if item.id not in cleaned_ids:
                        continue
                    text = item.source.read_text(encoding="utf-8")
                    metadata, body = _read_front_matter(text)
                    for field in LEGACY_KNOWLEDGE_FIELDS:
                        metadata.pop(field, None)
                    front = yaml.safe_dump(
                        metadata, allow_unicode=True, sort_keys=False
                    ).strip()
                    atomic_write_text(item.source, f"---\n{front}\n---\n\n{body}\n")
        except Exception:
            with content_lock(self.content_root):
                self._restore_snapshot(snapshot)
            raise
        return snapshot

    def rollback_latest_migration(self, confirmation: str) -> Path:
        if confirmation.strip() != "恢复整理前版本":
            raise ValueError("请输入“恢复整理前版本”确认")
        candidates = sorted(self.migration_root.glob("*/manifest.json"))
        if not candidates:
            raise ValueError("没有可恢复的知识库整理快照")
        snapshot = candidates[-1].parent
        with content_lock(self.content_root):
            self._restore_snapshot(snapshot)
        return snapshot
