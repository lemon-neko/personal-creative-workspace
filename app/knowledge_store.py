"""Confirmed atomic knowledge cards and multi-parent knowledge maps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import yaml

from app.content import ContentItem, load_items, render_markdown
from app.workspace import SHANGHAI


CARD_TYPES = {"concept", "claim", "question", "method", "observation"}
CARD_STATUSES = {"active", "superseded", "archived"}
MAP_KINDS = {"subject", "topic"}
EDGE_TYPES = {"related", "extends", "supports", "contrasts"}


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


@dataclass(frozen=True)
class KnowledgeStore:
    cards: tuple[KnowledgeCard, ...]
    maps: tuple[KnowledgeMap, ...]
    diagnostics: tuple[str, ...] = ()

    def card(self, card_id: str) -> KnowledgeCard | None:
        return next((card for card in self.cards if card.id == card_id), None)

    def map(self, map_id: str) -> KnowledgeMap | None:
        return next((item for item in self.maps if item.id == map_id), None)


def cards_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "cards"


def maps_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "maps"


def indexes_directory(content_root: Path) -> Path:
    return content_root / "knowledge" / "indexes"


def _split(text: str) -> tuple[dict, str]:
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
    return metadata, "\n".join(lines[end + 1 :]).strip()


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
    metadata, body = _split(path.read_text(encoding="utf-8"))
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
    )


def parse_map(path: Path) -> KnowledgeMap:
    metadata, body = _split(path.read_text(encoding="utf-8"))
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


def _write(path: Path, metadata: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    front = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{front}\n---\n\n{body.strip()}\n", encoding="utf-8")
    path.chmod(0o600)


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
    path = cards_directory(content_root) / f"{card_id}.md"
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
    path = maps_directory(content_root) / f"{map_id}.md"
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
    _write(card.source, metadata, card.body)
    return parse_card(card.source)


def layered_graph(
    sources: tuple[ContentItem, ...],
    store: KnowledgeStore,
) -> dict[str, list[dict]]:
    source_ids = {item.id for item in sources}
    card_ids = {card.id for card in store.cards}
    map_ids = {item.id for item in store.maps}
    nodes: list[dict] = []
    edges: list[dict] = []
    concepts: set[str] = set()
    for source in sources:
        nodes.append(
            {
                "id": source.id,
                "label": source.title,
                "type": "source",
                "kind": source.kind,
                "status": source.status,
                "subjects": list(source.subjects),
                "summary": source.summary,
                "href": f"/ideas/{source.id}",
            },
        )
        if source.parent_id and source.parent_id in source_ids:
            edges.append(
                {
                    "source": source.id,
                    "target": source.parent_id,
                    "type": "derived_from",
                }
            )
        edges.extend(
            {
                "source": source.id,
                "target": edge.target_id,
                "type": edge.relation,
                "note": edge.note,
            }
            for edge in source.relations
            if edge.target_id in source_ids
        )
        for concept in source.concepts:
            concepts.add(concept)
            edges.append(
                {
                    "source": source.id,
                    "target": f"concept:{concept}",
                    "type": "mentions",
                }
            )
    for item in store.maps:
        nodes.append(
            {"id": item.id, "label": item.title, "type": item.kind, "summary": item.summary, "href": f"/knowledge/maps/{item.id}"},
        )
        edges.extend(
            {"source": item.id, "target": parent, "type": "child_of"}
            for parent in item.parent_ids
            if parent in map_ids
        )
    for card in store.cards:
        nodes.append(
            {
                "id": card.id,
                "label": card.title,
                "type": "card",
                "kind": card.card_type,
                "status": card.status,
                "subjects": list(card.subjects),
                "summary": card.body[:160],
                "href": f"/knowledge/cards/{card.id}",
            },
        )
        edges.extend(
            {"source": card.id, "target": source, "type": "derived_from"}
            for source in card.source_ids
            if source in source_ids
        )
        edges.extend(
            {"source": card.id, "target": map_id, "type": "belongs_to"}
            for map_id in card.map_ids
            if map_id in map_ids
        )
        for concept in card.concepts:
            concept_id = f"concept:{concept}"
            concepts.add(concept)
            edges.append({"source": card.id, "target": concept_id, "type": "mentions"})
        edges.extend(
            {"source": card.id, "target": edge.target_id, "type": edge.relation, "note": edge.note}
            for edge in card.relations
            if edge.target_id in source_ids | card_ids | map_ids
        )
        if card.superseded_by and card.superseded_by in card_ids:
            edges.append(
                {"source": card.id, "target": card.superseded_by, "type": "superseded_by"},
            )
    nodes.extend(
        {"id": f"concept:{concept}", "label": concept, "type": "concept"}
        for concept in sorted(concepts)
    )
    return {"nodes": nodes, "edges": edges}
