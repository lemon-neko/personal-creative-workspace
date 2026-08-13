"""Confirmed knowledge metadata, derived indexes, and graph projections."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from app.content import (
    VALID_RELATION_TYPES,
    ContentCollection,
    ContentItem,
    KnowledgeRelation,
)
from app.workspace import SHANGHAI


DEFAULT_SUBJECTS = (
    "技术",
    "哲学",
    "经济学",
    "心理学",
    "社会学",
    "自然科学",
    "生活观察",
    "艺术与写作",
    "其他",
)
SUBJECT_COLORS = {
    "技术": "#078fa9",
    "哲学": "#7b68a6",
    "经济学": "#d28a34",
    "心理学": "#d56879",
    "社会学": "#4d7f9c",
    "自然科学": "#3e8a6a",
    "生活观察": "#c69b26",
    "艺术与写作": "#a66275",
    "其他": "#8b9293",
    "未分类": "#a7acab",
}
RELATION_LABELS = {
    "related": "相关",
    "extends": "延伸",
    "supports": "支持",
    "contrasts": "对照",
    "derived_from": "来源于",
    "mentions": "涉及",
    "cooccurs": "共同出现",
}


@dataclass(frozen=True)
class KnowledgeSuggestion:
    """One model-proposed, not-yet-confirmed knowledge annotation."""

    item_id: str
    subjects: tuple[str, ...]
    concepts: tuple[str, ...]
    relations: tuple[KnowledgeRelation, ...] = ()


@dataclass(frozen=True)
class SubjectSummary:
    """A deterministic or model-assisted summary for one subject."""

    name: str
    summary: str
    source_ids: tuple[str, ...]
    concepts: tuple[str, ...]
    color: str


@dataclass(frozen=True)
class KnowledgeIndex:
    """Derived subject index persisted outside the creative content stream."""

    updated_at: datetime | None
    subjects: tuple[SubjectSummary, ...]
    persisted: bool = False


@dataclass(frozen=True)
class KnowledgeGraph:
    """Browser-safe graph projection."""

    nodes: tuple[dict, ...]
    edges: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {"nodes": list(self.nodes), "edges": list(self.edges)}


def eligible_items(collection: ContentCollection) -> tuple[ContentItem, ...]:
    """Return active authored content used by the private knowledge graph."""

    return tuple(
        item
        for item in collection.items
        if item.kind != "weekly-review" and item.status != "archived"
    )


def stale_items(collection: ContentCollection) -> tuple[ContentItem, ...]:
    """Return items never analysed or changed since their last confirmation."""

    return tuple(
        item
        for item in eligible_items(collection)
        if item.knowledge_updated_at is None
        or item.knowledge_updated_at < item.updated_at
    )


def _clean_text_list(
    value: object,
    *,
    label: str,
    maximum: int,
    item_maximum: int,
    required: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label}必须是列表")
    cleaned: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{label}必须由非空文本组成")
        item = raw.strip()
        if len(item) > item_maximum:
            raise ValueError(f"{label}中的文本不能超过 {item_maximum} 个字符")
        if item not in cleaned:
            cleaned.append(item)
    if required and not cleaned:
        raise ValueError(f"{label}不能为空")
    if len(cleaned) > maximum:
        raise ValueError(f"{label}最多包含 {maximum} 项")
    return tuple(cleaned)


def validate_suggestions(
    payload: object,
    items: Sequence[ContentItem],
) -> tuple[KnowledgeSuggestion, ...]:
    """Validate model output against the exact active content collection."""

    if not isinstance(payload, dict) or not isinstance(payload.get("suggestions"), list):
        raise ValueError("模型没有返回建议列表")
    known_ids = {item.id for item in items}
    suggestions: list[KnowledgeSuggestion] = []
    seen: set[str] = set()
    for raw in payload["suggestions"]:
        if not isinstance(raw, dict):
            raise ValueError("每条知识建议必须是对象")
        item_id = raw.get("item_id")
        if not isinstance(item_id, str) or item_id not in known_ids or item_id in seen:
            raise ValueError("建议包含未知或重复的内容 ID")
        subjects = _clean_text_list(
            raw.get("subjects"),
            label="学科",
            maximum=3,
            item_maximum=30,
            required=True,
        )
        concepts = _clean_text_list(
            raw.get("concepts", []),
            label="概念",
            maximum=8,
            item_maximum=40,
            required=False,
        )
        raw_relations = raw.get("relations", [])
        if not isinstance(raw_relations, list) or len(raw_relations) > 12:
            raise ValueError("关联必须是不超过 12 项的列表")
        relations: list[KnowledgeRelation] = []
        for relation in raw_relations:
            if not isinstance(relation, dict):
                raise ValueError("关联建议必须是对象")
            target_id = relation.get("target_id")
            relation_type = relation.get("type")
            note = relation.get("note", "")
            if (
                not isinstance(target_id, str)
                or target_id not in known_ids
                or target_id == item_id
            ):
                raise ValueError("建议包含未知或无效的关联目标")
            if relation_type not in VALID_RELATION_TYPES:
                raise ValueError("建议包含未知的关联类型")
            if not isinstance(note, str) or len(note.strip()) > 160:
                raise ValueError("关联说明必须是不超过 160 个字符的文本")
            relations.append(
                KnowledgeRelation(target_id, relation_type, note.strip()),
            )
        seen.add(item_id)
        suggestions.append(
            KnowledgeSuggestion(item_id, subjects, concepts, tuple(relations)),
        )
    if not suggestions:
        raise ValueError("模型没有返回可用建议")
    return tuple(suggestions)


def _working_path(content_root: Path) -> Path:
    data_root = content_root.parent if content_root.name == "content" else content_root
    return data_root / "working" / "knowledge-suggestions.yaml"


def save_pending_suggestions(
    content_root: Path,
    suggestions: Sequence[KnowledgeSuggestion],
    items: Sequence[ContentItem],
) -> None:
    path = _working_path(content_root)
    updated_times = {item.id: item.updated_at.isoformat() for item in items}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "created_at": datetime.now(SHANGHAI).replace(microsecond=0).isoformat(),
                "suggestions": [
                    {
                        "item_id": suggestion.item_id,
                        "source_updated_at": updated_times.get(suggestion.item_id),
                        "subjects": list(suggestion.subjects),
                        "concepts": list(suggestion.concepts),
                        "relations": [
                            {
                                "target_id": relation.target_id,
                                "type": relation.relation,
                                "note": relation.note,
                            }
                            for relation in suggestion.relations
                        ],
                    }
                    for suggestion in suggestions
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def load_pending_suggestions(
    content_root: Path,
    items: Sequence[ContentItem],
) -> tuple[KnowledgeSuggestion, ...]:
    path = _working_path(content_root)
    if not path.exists():
        return ()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        suggestions = validate_suggestions(payload, items)
        updated_times = {item.id: item.updated_at.isoformat() for item in items}
        saved_times = {
            value.get("item_id"): value.get("source_updated_at")
            for value in payload.get("suggestions", [])
            if isinstance(value, dict)
        }
        return tuple(
            suggestion
            for suggestion in suggestions
            if saved_times.get(suggestion.item_id)
            == updated_times.get(suggestion.item_id)
        )
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return ()


def clear_pending_suggestions(content_root: Path) -> None:
    path = _working_path(content_root)
    if path.exists():
        path.unlink()


def parse_relation_lines(
    value: str,
    *,
    item_id: str,
    known_ids: set[str],
) -> tuple[KnowledgeRelation, ...]:
    """Parse editable `target | type | note` relation lines."""

    relations: list[KnowledgeRelation] = []
    for raw_line in value.splitlines():
        if not raw_line.strip():
            continue
        parts = [part.strip() for part in raw_line.split("|", 2)]
        if len(parts) < 2:
            raise ValueError("关联格式应为：内容 ID | 类型 | 说明")
        target_id, relation = parts[:2]
        note = parts[2] if len(parts) == 3 else ""
        if target_id == item_id or target_id not in known_ids:
            raise ValueError("关联目标不存在或无效")
        if relation not in VALID_RELATION_TYPES:
            raise ValueError("关联类型只能是 related、extends、supports 或 contrasts")
        if len(note) > 160:
            raise ValueError("关联说明不能超过 160 个字符")
        relations.append(KnowledgeRelation(target_id, relation, note))
    if len(relations) > 12:
        raise ValueError("关联最多包含 12 项")
    return tuple(relations)


def format_relation_lines(relations: Sequence[KnowledgeRelation]) -> str:
    return "\n".join(
        f"{relation.target_id} | {relation.relation}"
        f"{f' | {relation.note}' if relation.note else ''}"
        for relation in relations
    )


def _subject_color(subject: str) -> str:
    if subject in SUBJECT_COLORS:
        return SUBJECT_COLORS[subject]
    digest = int(hashlib.sha1(subject.encode("utf-8")).hexdigest()[:6], 16)
    hue = digest % 360
    return f"hsl({hue} 38% 48%)"


def build_subject_summaries(
    items: Sequence[ContentItem],
    model_summaries: Mapping[str, str] | None = None,
) -> tuple[SubjectSummary, ...]:
    grouped: dict[str, list[ContentItem]] = defaultdict(list)
    for item in items:
        for subject in item.subjects or ("未分类",):
            grouped[subject].append(item)
    ordered_names = [name for name in DEFAULT_SUBJECTS if name in grouped]
    ordered_names.extend(
        sorted(name for name in grouped if name not in DEFAULT_SUBJECTS and name != "未分类"),
    )
    if "未分类" in grouped:
        ordered_names.append("未分类")
    summaries: list[SubjectSummary] = []
    for name in ordered_names:
        subject_items = grouped[name]
        concepts = Counter(
            concept for item in subject_items for concept in item.concepts
        )
        common = tuple(
            concept
            for concept, _ in sorted(
                concepts.items(),
                key=lambda pair: (-pair[1], pair[0]),
            )[:8]
        )
        fallback = f"收录 {len(subject_items)} 条内容"
        if common:
            fallback += f"，主要涉及{'、'.join(common[:5])}。"
        else:
            fallback += "，尚未提炼出稳定概念。"
        model_summary = (model_summaries or {}).get(name, "").strip()
        summaries.append(
            SubjectSummary(
                name=name,
                summary=model_summary[:500] or fallback,
                source_ids=tuple(item.id for item in subject_items),
                concepts=common,
                color=_subject_color(name),
            ),
        )
    return tuple(summaries)


def _index_path(content_root: Path) -> Path:
    return content_root / "knowledge" / "indexes" / "subject-index.yaml"


def rebuild_knowledge_index(
    content_root: Path,
    items: Sequence[ContentItem],
    *,
    model_summaries: Mapping[str, str] | None = None,
) -> KnowledgeIndex:
    updated_at = datetime.now(SHANGHAI).replace(microsecond=0)
    summaries = build_subject_summaries(items, model_summaries)
    path = _index_path(content_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "updated_at": updated_at.isoformat(),
                "subjects": [
                    {
                        "name": subject.name,
                        "summary": subject.summary,
                        "source_ids": list(subject.source_ids),
                        "concepts": list(subject.concepts),
                        "color": subject.color,
                    }
                    for subject in summaries
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return KnowledgeIndex(updated_at, summaries, persisted=True)


def load_knowledge_index(
    content_root: Path,
    items: Sequence[ContentItem],
) -> KnowledgeIndex:
    """Load saved summaries, falling back to a live deterministic projection."""

    path = _index_path(content_root)
    legacy_path = content_root / "knowledge" / "index.yaml"
    if not path.exists() and legacy_path.exists():
        path = legacy_path
    if not path.exists():
        return KnowledgeIndex(None, build_subject_summaries(items))
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        saved = {
            str(value["name"]): str(value["summary"])
            for value in payload.get("subjects", [])
            if isinstance(value, dict) and value.get("name") and value.get("summary")
        }
        return KnowledgeIndex(
            updated_at.astimezone(SHANGHAI),
            build_subject_summaries(items, saved),
            persisted=True,
        )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError):
        return KnowledgeIndex(None, build_subject_summaries(items))


def build_knowledge_graph(items: Sequence[ContentItem]) -> KnowledgeGraph:
    """Build item, concept, lineage, co-occurrence, and confirmed relation edges."""

    active = {item.id: item for item in items}
    nodes: list[dict] = []
    edges: list[dict] = []
    concept_subjects: dict[str, set[str]] = defaultdict(set)
    concept_counts: Counter[str] = Counter()
    concept_pairs: Counter[tuple[str, str]] = Counter()

    for item in items:
        primary_subject = item.subjects[0] if item.subjects else "未分类"
        nodes.append(
            {
                "id": f"item:{item.id}",
                "item_id": item.id,
                "type": "item",
                "label": item.title,
                "summary": item.summary,
                "subject": primary_subject,
                "subjects": list(item.subjects),
                "status": item.status,
                "kind": item.kind,
                "href": f"/ideas/{item.id}",
                "color": _subject_color(primary_subject),
            },
        )
        for concept in item.concepts:
            concept_subjects[concept].update(item.subjects or ("未分类",))
            concept_counts[concept] += 1
            edges.append(
                {
                    "source": f"item:{item.id}",
                    "target": _concept_id(concept),
                    "type": "mentions",
                    "label": RELATION_LABELS["mentions"],
                    "weight": 1,
                },
            )
        unique_concepts = sorted(set(item.concepts))
        for index, left in enumerate(unique_concepts):
            for right in unique_concepts[index + 1 :]:
                concept_pairs[(left, right)] += 1
        if item.parent_id and item.parent_id in active:
            edges.append(
                {
                    "source": f"item:{item.id}",
                    "target": f"item:{item.parent_id}",
                    "type": "derived_from",
                    "label": RELATION_LABELS["derived_from"],
                    "weight": 2,
                },
            )
        for relation in item.relations:
            if relation.target_id in active:
                edges.append(
                    {
                        "source": f"item:{item.id}",
                        "target": f"item:{relation.target_id}",
                        "type": relation.relation,
                        "label": RELATION_LABELS[relation.relation],
                        "note": relation.note,
                        "weight": 2,
                    },
                )

    for concept, subjects in sorted(concept_subjects.items()):
        ordered_subjects = sorted(subjects)
        primary_subject = ordered_subjects[0] if ordered_subjects else "未分类"
        nodes.append(
            {
                "id": _concept_id(concept),
                "type": "concept",
                "label": concept,
                "summary": f"出现在 {concept_counts[concept]} 条内容中",
                "subject": primary_subject,
                "subjects": ordered_subjects,
                "count": concept_counts[concept],
                "color": _subject_color(primary_subject),
            },
        )
    for (left, right), count in concept_pairs.items():
        edges.append(
            {
                "source": _concept_id(left),
                "target": _concept_id(right),
                "type": "cooccurs",
                "label": RELATION_LABELS["cooccurs"],
                "weight": count,
            },
        )
    return KnowledgeGraph(tuple(nodes), tuple(edges))


def _concept_id(concept: str) -> str:
    digest = hashlib.sha1(concept.encode("utf-8")).hexdigest()[:12]
    return f"concept:{digest}"
