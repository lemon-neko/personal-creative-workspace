"""Confirmed atomic knowledge cards and multi-parent knowledge maps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

import yaml

from app.atomic import atomic_write_text
from app.content import (
    ContentItem,
    combine_managed_links,
    load_items,
    render_markdown,
    split_managed_links,
)
from app.workspace import SHANGHAI


CARD_TYPES = {"concept", "claim", "question", "method", "observation"}
CARD_STATUSES = {"active", "superseded", "archived"}
MAP_KINDS = {"subject", "topic"}
EDGE_TYPES = {"related", "extends", "supports", "contrasts"}
CARD_FIELDS = {
    "id", "title", "card_type", "status", "created_at", "updated_at",
    "subjects", "map_ids", "concepts", "source_ids", "relations",
    "valid_from", "valid_to", "superseded_by",
}
MAP_FIELDS = {"id", "title", "kind", "summary", "parent_ids", "created_at", "updated_at"}


def _knowledge_filename(title: str, item_id: str) -> str:
    """Keep stable IDs while making newly created Obsidian nodes readable."""

    readable = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", title.strip())
    readable = re.sub(r"\s+", " ", readable).strip(" .-")[:72] or "未命名知识"
    suffix = item_id.rsplit("-", 1)[-1]
    return f"{readable}--{suffix}.md"


@dataclass(frozen=True)
class KnowledgeEdge:
    target_id: str
    relation: str
    note: str = ""


@dataclass(frozen=True)
class KnowledgeCard:
    id: str
    title: str
    card_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    body: str
    subjects: tuple[str, ...]
    map_ids: tuple[str, ...]
    concepts: tuple[str, ...]
    source_ids: tuple[str, ...]
    relations: tuple[KnowledgeEdge, ...] = ()
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by: str | None = None
    source: Path = Path()
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    managed_links: str = ""

    @property
    def html(self) -> str:
        return render_markdown(self.body)


@dataclass(frozen=True)
class KnowledgeMap:
    id: str
    title: str
    kind: str
    summary: str
    parent_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    body: str = ""
    source: Path = Path()
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    managed_links: str = ""


@dataclass(frozen=True)
class KnowledgeStore:
    cards: tuple[KnowledgeCard, ...]
    maps: tuple[KnowledgeMap, ...]
    diagnostics: tuple[str, ...] = ()

    def card(self, card_id: str) -> KnowledgeCard | None:
        return next((card for card in self.cards if card.id == card_id), None)

    def map(self, map_id: str) -> KnowledgeMap | None:
        return next((item for item in self.maps if item.id == map_id), None)


@dataclass(frozen=True)
class CoreKnowledgeGraph:
    """A quiet graph projection: maps and cards first, provenance on demand."""

    nodes: tuple[dict, ...]
    edges: tuple[dict, ...]
    sources: tuple[dict, ...]
    source_edges: tuple[dict, ...]

    def as_dict(self) -> dict[str, list[dict]]:
        return {
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "sources": list(self.sources),
            "source_edges": list(self.source_edges),
        }


def cards_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "cards"


def maps_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "maps"


def indexes_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "indexes"


def _split(text: str) -> tuple[dict, str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("缺少 YAML front matter")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError("缺少 YAML front matter 结束标记") from error
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(metadata, dict):
        raise ValueError("front matter 必须是键值映射")
    body, managed_links = split_managed_links("\n".join(lines[end + 1 :]).strip())
    return metadata, body, managed_links


def _extras(metadata: dict, reserved: set[str]) -> dict[str, Any]:
    values = {str(key): value for key, value in metadata.items() if key not in reserved}
    if len(values) > 50 or len(yaml.safe_dump(values, allow_unicode=True).encode()) > 20_000:
        raise ValueError("Obsidian 自定义属性数量或大小超限")
    return values


def _text(metadata: dict, key: str, maximum: int) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{key}` 必须是非空文本")
    return value.strip()[:maximum]


def _values(
    metadata: dict,
    key: str,
    maximum: int,
    item_maximum: int,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    raw = metadata.get(key, [])
    if not isinstance(raw, list):
        raise ValueError(f"`{key}` 必须是列表")
    values: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"`{key}` 包含无效值")
        cleaned = value.strip()
        if len(cleaned) > item_maximum:
            raise ValueError(f"`{key}` 单项过长")
        if cleaned not in values:
            values.append(cleaned)
    if required and not values:
        raise ValueError(f"`{key}` 不能为空")
    if len(values) > maximum:
        raise ValueError(f"`{key}` 最多包含 {maximum} 项")
    return tuple(values)


def _datetime(value: object, key: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        raise ValueError(f"`{key}` 必须是 ISO 8601 时间")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _optional_datetime(metadata: dict, key: str) -> datetime | None:
    value = metadata.get(key)
    return None if value in (None, "") else _datetime(value, key)


def parse_card(path: Path) -> KnowledgeCard:
    metadata, body, managed_links = _split(path.read_text(encoding="utf-8"))
    card_type = metadata.get("card_type")
    status = metadata.get("status")
    if card_type not in CARD_TYPES:
        raise ValueError("知识卡类型无效")
    if status not in CARD_STATUSES:
        raise ValueError("知识卡状态无效")
    if not body:
        raise ValueError("知识卡正文不能为空")
    raw_relations = metadata.get("relations", [])
    if not isinstance(raw_relations, list) or len(raw_relations) > 12:
        raise ValueError("知识卡关系无效")
    relations: list[KnowledgeEdge] = []
    for raw in raw_relations:
        if not isinstance(raw, dict) or raw.get("type") not in EDGE_TYPES:
            raise ValueError("知识卡包含未知关系")
        target = str(raw.get("target_id", "")).strip()
        note = str(raw.get("note", "")).strip()
        if not target or len(note) > 160:
            raise ValueError("知识卡关系目标或说明无效")
        relations.append(KnowledgeEdge(target, str(raw["type"]), note))
    valid_from = _optional_datetime(metadata, "valid_from")
    valid_to = _optional_datetime(metadata, "valid_to")
    if valid_from and valid_to and valid_to < valid_from:
        raise ValueError("知识卡有效时间范围无效")
    return KnowledgeCard(
        id=_text(metadata, "id", 160),
        title=_text(metadata, "title", 160),
        card_type=card_type,
        status=status,
        created_at=_datetime(metadata.get("created_at"), "created_at"),
        updated_at=_datetime(metadata.get("updated_at"), "updated_at"),
        body=body,
        subjects=_values(metadata, "subjects", 3, 30, required=True),
        map_ids=_values(metadata, "map_ids", 8, 160),
        concepts=_values(metadata, "concepts", 8, 40),
        source_ids=_values(metadata, "source_ids", 20, 160, required=True),
        relations=tuple(relations),
        valid_from=valid_from,
        valid_to=valid_to,
        superseded_by=(str(metadata.get("superseded_by", "")).strip() or None),
        source=path,
        extra_metadata=_extras(metadata, CARD_FIELDS),
        managed_links=managed_links,
    )


def parse_map(path: Path) -> KnowledgeMap:
    metadata, body, managed_links = _split(path.read_text(encoding="utf-8"))
    kind = metadata.get("kind")
    if kind not in MAP_KINDS:
        raise ValueError("知识地图类型无效")
    return KnowledgeMap(
        id=_text(metadata, "id", 160),
        title=_text(metadata, "title", 160),
        kind=kind,
        summary=_text(metadata, "summary", 500),
        parent_ids=_values(metadata, "parent_ids", 3, 160),
        created_at=_datetime(metadata.get("created_at"), "created_at"),
        updated_at=_datetime(metadata.get("updated_at"), "updated_at"),
        body=body,
        source=path,
        extra_metadata=_extras(metadata, MAP_FIELDS),
        managed_links=managed_links,
    )


def load_knowledge_store(content_root: Path) -> KnowledgeStore:
    cards: list[KnowledgeCard] = []
    maps: list[KnowledgeMap] = []
    diagnostics: list[str] = []
    seen: set[str] = set()
    sources = [
        (path, parse_card, cards)
        for path in sorted(cards_directory(content_root).glob("*.md"))
    ]
    sources.extend(
        (path, parse_map, maps)
        for path in sorted(maps_directory(content_root).glob("*.md"))
    )
    for path, parser, target in sources:
        try:
            value = parser(path)
            if value.id in seen:
                raise ValueError(f"重复 ID：{value.id}")
            seen.add(value.id)
            target.append(value)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
            diagnostics.append(f"{path.name}: {error}")
    cards.sort(key=lambda card: (card.updated_at, card.id), reverse=True)
    maps.sort(key=lambda item: (item.kind, item.title, item.id))
    try:
        validate_map_graph(tuple(maps))
    except ValueError as error:
        diagnostics.append(str(error))
    source_ids = {
        item.id
        for item in load_items(content_root).items
        if item.kind != "weekly-review"
    }
    map_ids = {item.id for item in maps}
    card_ids = {item.id for item in cards}
    known_targets = source_ids | map_ids | card_ids
    for card in cards:
        if not set(card.source_ids) <= source_ids:
            diagnostics.append(f"{card.source.name}: 引用了不存在的原始来源")
        if not set(card.map_ids) <= map_ids:
            diagnostics.append(f"{card.source.name}: 引用了不存在的知识地图")
        if any(edge.target_id not in known_targets for edge in card.relations):
            diagnostics.append(f"{card.source.name}: 引用了不存在的关系目标")
        if card.superseded_by and card.superseded_by not in card_ids:
            diagnostics.append(f"{card.source.name}: 替代卡片不存在")
    return KnowledgeStore(tuple(cards), tuple(maps), tuple(diagnostics))


def validate_map_graph(maps: tuple[KnowledgeMap, ...]) -> None:
    known = {item.id for item in maps}
    parents = {item.id: item.parent_ids for item in maps}
    for item in maps:
        if item.id in item.parent_ids or not set(item.parent_ids) <= known:
            raise ValueError(f"知识地图 `{item.id}` 包含无效父节点")

    def visit(node: str, active: set[str], complete: set[str]) -> None:
        if node in active:
            raise ValueError("知识地图父级关系存在循环")
        if node in complete:
            return
        active.add(node)
        for parent in parents[node]:
            visit(parent, active, complete)
        active.remove(node)
        complete.add(node)

    complete: set[str] = set()
    for node in parents:
        visit(node, set(), complete)


def _write(
    path: Path,
    metadata: dict,
    body: str,
    *,
    extra_metadata: dict[str, Any] | None = None,
    managed_links: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    values = dict(extra_metadata or {})
    values.update(metadata)
    front = yaml.safe_dump(values, allow_unicode=True, sort_keys=False).strip()
    combined = combine_managed_links(body, managed_links)
    atomic_write_text(path, f"---\n{front}\n---\n\n{combined}\n")


def knowledge_semantic_revision(value: KnowledgeCard | KnowledgeMap) -> str:
    """Hash authored meaning while ignoring timestamps and generated links."""

    if isinstance(value, KnowledgeCard):
        payload = {
            "id": value.id,
            "title": value.title,
            "card_type": value.card_type,
            "status": value.status,
            "body": value.body,
            "subjects": value.subjects,
            "map_ids": value.map_ids,
            "concepts": value.concepts,
            "source_ids": value.source_ids,
            "relations": [
                (edge.target_id, edge.relation, edge.note) for edge in value.relations
            ],
            "valid_from": value.valid_from.isoformat() if value.valid_from else None,
            "valid_to": value.valid_to.isoformat() if value.valid_to else None,
            "superseded_by": value.superseded_by,
            "extra_metadata": value.extra_metadata,
        }
    else:
        payload = {
            "id": value.id,
            "title": value.title,
            "kind": value.kind,
            "summary": value.summary,
            "parent_ids": value.parent_ids,
            "body": value.body,
            "extra_metadata": value.extra_metadata,
        }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reconcile_knowledge_external_edit(
    content_root: Path,
    item_id: str,
    *,
    expected_revision: str,
    now: datetime | None = None,
) -> KnowledgeCard | KnowledgeMap:
    """Accept one valid Obsidian edit and only refresh its update timestamp."""

    store = load_knowledge_store(content_root)
    value: KnowledgeCard | KnowledgeMap | None = store.card(item_id) or store.map(item_id)
    if value is None:
        raise KeyError(item_id)
    if knowledge_semantic_revision(value) != expected_revision:
        raise ValueError("知识文件在扫描期间再次变化，请重新扫描")
    stamp = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).replace(
        microsecond=0
    )
    if isinstance(value, KnowledgeCard):
        metadata = {
            "id": value.id,
            "title": value.title,
            "card_type": value.card_type,
            "status": value.status,
            "created_at": value.created_at.isoformat(),
            "updated_at": stamp.isoformat(),
            "subjects": list(value.subjects),
            "map_ids": list(value.map_ids),
            "concepts": list(value.concepts),
            "source_ids": list(value.source_ids),
            "relations": [
                {
                    "target_id": edge.target_id,
                    "type": edge.relation,
                    "note": edge.note,
                }
                for edge in value.relations
            ],
            "valid_from": value.valid_from.isoformat() if value.valid_from else None,
            "valid_to": value.valid_to.isoformat() if value.valid_to else None,
            "superseded_by": value.superseded_by,
        }
    else:
        metadata = {
            "id": value.id,
            "title": value.title,
            "kind": value.kind,
            "summary": value.summary,
            "parent_ids": list(value.parent_ids),
            "created_at": value.created_at.isoformat(),
            "updated_at": stamp.isoformat(),
        }
    metadata = {key: item for key, item in metadata.items() if item is not None}
    _write(
        value.source,
        metadata,
        value.body,
        extra_metadata=value.extra_metadata,
        managed_links=value.managed_links,
    )
    return parse_card(value.source) if isinstance(value, KnowledgeCard) else parse_map(value.source)


def create_knowledge_card(
    content_root: Path,
    *,
    title: str,
    body: str,
    card_type: str,
    subjects: tuple[str, ...],
    source_ids: tuple[str, ...],
    map_ids: tuple[str, ...] = (),
    concepts: tuple[str, ...] = (),
    relations: tuple[KnowledgeEdge, ...] = (),
    now: datetime | None = None,
) -> KnowledgeCard:
    if card_type not in CARD_TYPES or not title.strip() or not body.strip():
        raise ValueError("知识卡标题、正文或类型无效")
    clean_subjects = tuple(dict.fromkeys(value.strip() for value in subjects if value.strip()))
    clean_sources = tuple(dict.fromkeys(value.strip() for value in source_ids if value.strip()))
    clean_maps = tuple(dict.fromkeys(value.strip() for value in map_ids if value.strip()))
    clean_concepts = tuple(dict.fromkeys(value.strip() for value in concepts if value.strip()))
    if not clean_sources:
        raise ValueError("知识卡必须关联至少一个原始来源")
    if not clean_subjects or len(clean_subjects) > 3:
        raise ValueError("知识卡必须包含 1–3 个学科")
    if len(clean_concepts) > 8 or len(clean_maps) > 8 or len(clean_sources) > 20:
        raise ValueError("知识卡概念、地图或来源数量超限")
    if any(len(value) > 30 for value in clean_subjects) or any(
        len(value) > 40 for value in clean_concepts
    ):
        raise ValueError("知识卡学科或概念过长")
    if len(relations) > 12 or any(
        edge.relation not in EDGE_TYPES
        or not edge.target_id.strip()
        or len(edge.note) > 160
        for edge in relations
    ):
        raise ValueError("知识卡关系无效")
    store = load_knowledge_store(content_root)
    if clean_maps and not set(clean_maps) <= {item.id for item in store.maps}:
        raise ValueError("知识卡引用了不存在的知识地图")
    known_sources = {
        item.id
        for item in load_items(content_root).items
        if item.kind != "weekly-review"
    }
    if not set(clean_sources) <= known_sources:
        raise ValueError("知识卡引用了不存在的原始来源")
    known_targets = known_sources | {item.id for item in store.cards} | {
        item.id for item in store.maps
    }
    if any(edge.target_id not in known_targets for edge in relations):
        raise ValueError("知识卡引用了不存在的关系目标")
    stamp = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).replace(microsecond=0)
    card_id = f"card-{stamp:%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
    path = cards_directory(content_root) / _knowledge_filename(title, card_id)
    _write(
        path,
        {
            "id": card_id,
            "title": title.strip()[:160],
            "card_type": card_type,
            "status": "active",
            "created_at": stamp.isoformat(),
            "updated_at": stamp.isoformat(),
            "subjects": list(clean_subjects),
            "map_ids": list(clean_maps),
            "concepts": list(clean_concepts),
            "source_ids": list(clean_sources),
            "relations": [
                {"target_id": edge.target_id, "type": edge.relation, "note": edge.note}
                for edge in relations[:12]
            ],
        },
        body,
    )
    return parse_card(path)


def create_knowledge_map(
    content_root: Path,
    *,
    title: str,
    kind: str,
    summary: str,
    parent_ids: tuple[str, ...] = (),
    body: str = "",
    now: datetime | None = None,
) -> KnowledgeMap:
    if kind not in MAP_KINDS or not title.strip() or not summary.strip():
        raise ValueError("知识地图标题、摘要或类型无效")
    existing = load_knowledge_store(content_root)
    if existing.diagnostics:
        raise ValueError("请先修复现有知识库诊断，再创建地图")
    if len(tuple(dict.fromkeys(parent_ids))) > 3:
        raise ValueError("知识地图最多包含 3 个父节点")
    if not set(parent_ids) <= {item.id for item in existing.maps}:
        raise ValueError("知识地图引用了不存在的父节点")
    stamp = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).replace(microsecond=0)
    map_id = f"map-{uuid4().hex[:10]}"
    path = maps_directory(content_root) / _knowledge_filename(title, map_id)
    candidate = KnowledgeMap(
        id=map_id,
        title=title.strip()[:160],
        kind=kind,
        summary=summary.strip()[:500],
        parent_ids=tuple(dict.fromkeys(parent_ids))[:3],
        created_at=stamp,
        updated_at=stamp,
        body=body.strip(),
        source=path,
    )
    validate_map_graph((*existing.maps, candidate))
    _write(
        path,
        {
            "id": candidate.id,
            "title": candidate.title,
            "kind": candidate.kind,
            "summary": candidate.summary,
            "parent_ids": list(candidate.parent_ids),
            "created_at": candidate.created_at.isoformat(),
            "updated_at": candidate.updated_at.isoformat(),
        },
        candidate.body,
    )
    return parse_map(path)


def supersede_knowledge_card(
    content_root: Path,
    card_id: str,
    replacement_id: str,
    *,
    now: datetime | None = None,
) -> KnowledgeCard:
    """Retire an old card while preserving its body and provenance."""

    store = load_knowledge_store(content_root)
    card = store.card(card_id)
    replacement = store.card(replacement_id)
    if (
        card is None
        or replacement is None
        or card.id == replacement.id
        or card.status != "active"
    ):
        raise ValueError("替代关系中的知识卡无效")
    stamp = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).replace(
        microsecond=0
    )
    metadata = {
        "id": card.id,
        "title": card.title,
        "card_type": card.card_type,
        "status": "superseded",
        "created_at": card.created_at.isoformat(),
        "updated_at": stamp.isoformat(),
        "subjects": list(card.subjects),
        "map_ids": list(card.map_ids),
        "concepts": list(card.concepts),
        "source_ids": list(card.source_ids),
        "relations": [
            {
                "target_id": edge.target_id,
                "type": edge.relation,
                "note": edge.note,
            }
            for edge in card.relations
        ],
        "valid_from": (card.valid_from or card.created_at).isoformat(),
        "valid_to": stamp.isoformat(),
        "superseded_by": replacement.id,
    }
    _write(
        card.source,
        metadata,
        card.body,
        extra_metadata=card.extra_metadata,
        managed_links=card.managed_links,
    )
    return parse_card(card.source)


def core_knowledge_graph(
    sources: tuple[ContentItem, ...],
    store: KnowledgeStore,
) -> CoreKnowledgeGraph:
    """Project the canonical hierarchy without legacy concept/source noise."""

    source_lookup = {
        item.id: item
        for item in sources
        if item.kind != "weekly-review" and item.status != "archived"
    }
    map_lookup = {item.id: item for item in store.maps}
    visible_cards = tuple(card for card in store.cards if card.status != "archived")
    card_ids = {card.id for card in visible_cards}
    nodes: list[dict] = []
    edges: list[dict] = []

    subject_cache: dict[str, tuple[str, ...]] = {}

    def subject_ids(map_id: str, active: set[str] | None = None) -> tuple[str, ...]:
        if map_id in subject_cache:
            return subject_cache[map_id]
        item = map_lookup.get(map_id)
        if item is None:
            return ()
        if item.kind == "subject":
            subject_cache[map_id] = (item.id,)
            return (item.id,)
        path = set(active or ())
        if map_id in path:
            return ()
        path.add(map_id)
        result = tuple(
            sorted(
                {
                    subject
                    for parent in item.parent_ids
                    for subject in subject_ids(parent, path)
                },
            ),
        )
        subject_cache[map_id] = result
        return result

    for item in store.maps:
        subjects = subject_ids(item.id)
        nodes.append(
            {
                "id": item.id,
                "label": item.title,
                "type": item.kind,
                "status": "active",
                "subjects": [map_lookup[value].title for value in subjects],
                "cluster": subjects[0] if subjects else item.id,
                "summary": item.summary,
                "href": f"/knowledge/maps/{item.id}",
            },
        )
        edges.extend(
            {
                "source": item.id,
                "target": parent,
                "type": "child_of",
            }
            for parent in item.parent_ids
            if parent in map_lookup
        )

    referenced_sources: set[str] = set()
    source_edges: list[dict] = []
    for card in visible_cards:
        mapped_subjects = {
            map_lookup[value].title
            for map_id in card.map_ids
            for value in subject_ids(map_id)
            if value in map_lookup
        }
        subjects = sorted(mapped_subjects or set(card.subjects))
        cluster_ids = sorted(
            {
                value
                for map_id in card.map_ids
                for value in subject_ids(map_id)
            },
        )
        nodes.append(
            {
                "id": card.id,
                "label": card.title,
                "type": "card",
                "kind": card.card_type,
                "status": card.status,
                "subjects": subjects,
                "concepts": list(card.concepts),
                "cluster": cluster_ids[0] if cluster_ids else "unmapped",
                "summary": card.body[:160],
                "href": f"/knowledge/cards/{card.id}",
                "source_count": sum(
                    source_id in source_lookup for source_id in card.source_ids
                ),
            },
        )
        edges.extend(
            {
                "source": card.id,
                "target": map_id,
                "type": "belongs_to",
            }
            for map_id in card.map_ids
            if map_id in map_lookup
        )
        edges.extend(
            {
                "source": card.id,
                "target": edge.target_id,
                "type": edge.relation,
                "note": edge.note,
            }
            for edge in card.relations
            if edge.target_id in card_ids or edge.target_id in map_lookup
        )
        if card.superseded_by and card.superseded_by in card_ids:
            edges.append(
                {
                    "source": card.id,
                    "target": card.superseded_by,
                    "type": "superseded_by",
                },
            )
        for source_id in card.source_ids:
            if source_id not in source_lookup:
                continue
            referenced_sources.add(source_id)
            source_edges.append(
                {
                    "source": card.id,
                    "target": source_id,
                    "type": "derived_from",
                },
            )

    deferred_sources = tuple(
        {
            "id": item.id,
            "label": item.title,
            "type": "source",
            "kind": item.kind,
            "status": item.status,
            "summary": item.summary,
            "href": f"/ideas/{item.id}",
        }
        for item in sorted(
            (source_lookup[value] for value in referenced_sources),
            key=lambda value: (value.title, value.id),
        )
    )
    return CoreKnowledgeGraph(
        tuple(nodes),
        tuple(edges),
        deferred_sources,
        tuple(source_edges),
    )


def layered_graph(
    sources: tuple[ContentItem, ...],
    store: KnowledgeStore,
) -> dict[str, list[dict]]:
    """Backward-compatible name for callers migrating to the core projection."""

    return core_knowledge_graph(sources, store).as_dict()
