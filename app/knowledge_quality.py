"""Deterministic maintenance diagnostics for the canonical knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass

from app.content import ContentItem, semantic_revision
from app.knowledge_store import KnowledgeStore
from app.obsidian import obsidian_uri


@dataclass(frozen=True)
class KnowledgeQualityIssue:
    code: str
    severity: str
    title: str
    detail: str
    href: str
    obsidian_url: str


def inspect_knowledge_quality(
    sources: tuple[ContentItem, ...],
    store: KnowledgeStore,
) -> tuple[KnowledgeQualityIssue, ...]:
    source_lookup = {
        item.id: item
        for item in sources
        if item.kind != "weekly-review" and item.status != "archived"
    }
    map_lookup = {item.id: item for item in store.maps}
    card_lookup = {item.id: item for item in store.cards}
    active_cards = tuple(card for card in store.cards if card.status == "active")
    topics = tuple(item for item in store.maps if item.kind == "topic")
    subjects = tuple(item for item in store.maps if item.kind == "subject")
    issues: list[KnowledgeQualityIssue] = []

    covered_sources = {
        source_id for card in active_cards for source_id in card.source_ids
    }
    for item in source_lookup.values():
        if item.kind != "thought":
            continue
        if item.id not in covered_sources:
            issues.append(
                KnowledgeQualityIssue(
                    "uncovered-source",
                    "notice",
                    f"来源尚未拆卡：{item.title}",
                    "这条原始记录还没有进入正式知识结构。",
                    f"/ideas/{item.id}",
                    obsidian_uri(item.source),
                )
            )

    for card in active_cards:
        missing_sources = [value for value in card.source_ids if value not in source_lookup]
        if missing_sources:
            issues.append(
                KnowledgeQualityIssue(
                    "missing-source",
                    "error",
                    f"知识卡来源失效：{card.title}",
                    "引用的原始来源不存在、已归档或不可参与正式图谱。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )
        if not card.map_ids:
            issues.append(
                KnowledgeQualityIssue(
                    "unmapped-card",
                    "warning",
                    f"知识卡尚未归入主题：{card.title}",
                    "请在 Obsidian 中为它选择至少一个主题地图。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )
        elif any(value not in map_lookup for value in card.map_ids):
            issues.append(
                KnowledgeQualityIssue(
                    "invalid-map",
                    "error",
                    f"知识卡地图失效：{card.title}",
                    "卡片引用了不存在的知识地图。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )
        known_card_sources = tuple(
            source_lookup[value]
            for value in card.source_ids
            if value in source_lookup
        )
        unconfirmed = tuple(
            item.id
            for item in known_card_sources
            if item.id not in card.source_revisions
        )
        changed = tuple(
            item.id
            for item in known_card_sources
            if item.id in card.source_revisions
            and card.source_revisions[item.id] != semantic_revision(item)
        )
        if unconfirmed:
            issues.append(
                KnowledgeQualityIssue(
                    "unconfirmed-source-revision",
                    "warning",
                    f"来源 Revision 尚未确认：{card.title}",
                    "这张旧知识卡尚未记录来源版本，请人工复核后确认。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )
        elif changed:
            issues.append(
                KnowledgeQualityIssue(
                    "stale-card",
                    "warning",
                    f"来源更新后尚未复核：{card.title}",
                    "原始来源比知识卡更新，请重新确认结论是否仍然成立。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )
        if any(edge.relation == "contrasts" for edge in card.relations):
            issues.append(
                KnowledgeQualityIssue(
                    "contrast-review",
                    "notice",
                    f"存在对照观点：{card.title}",
                    "这是保留差异的正常关系，可在复盘时确认是否需要补充边界。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )

    def reaches_subject(map_id: str, visited: set[str] | None = None) -> bool:
        item = map_lookup.get(map_id)
        if item is None:
            return False
        if item.kind == "subject":
            return True
        seen = set(visited or ())
        if map_id in seen:
            return False
        seen.add(map_id)
        return any(reaches_subject(parent, seen) for parent in item.parent_ids)

    for subject in subjects:
        if not any(subject.id in topic.parent_ids for topic in topics):
            issues.append(
                KnowledgeQualityIssue(
                    "empty-subject",
                    "notice",
                    f"学科还没有主题：{subject.title}",
                    "学科地图目前是空入口，可补充主题或暂时归档。",
                    f"/knowledge/maps/{subject.id}",
                    obsidian_uri(subject.source),
                )
            )
    for topic in topics:
        if not reaches_subject(topic.id):
            issues.append(
                KnowledgeQualityIssue(
                    "orphan-topic",
                    "warning",
                    f"主题没有学科上级：{topic.title}",
                    "主题无法从知识首页的学科路径进入。",
                    f"/knowledge/maps/{topic.id}",
                    obsidian_uri(topic.source),
                )
            )
        if not any(topic.id in card.map_ids for card in active_cards):
            issues.append(
                KnowledgeQualityIssue(
                    "empty-topic",
                    "notice",
                    f"主题还没有知识卡：{topic.title}",
                    "这个主题目前没有承载有效知识。",
                    f"/knowledge/maps/{topic.id}",
                    obsidian_uri(topic.source),
                )
            )

    for card in store.cards:
        if card.status != "superseded":
            continue
        successor = card_lookup.get(card.superseded_by or "")
        if successor is None or successor.id == card.id:
            issues.append(
                KnowledgeQualityIssue(
                    "broken-supersession",
                    "error",
                    f"替代链异常：{card.title}",
                    "已被替代的卡片没有指向有效后继卡。",
                    f"/knowledge/cards/{card.id}",
                    obsidian_uri(card.source),
                )
            )

    severity_order = {"error": 0, "warning": 1, "notice": 2}
    return tuple(
        sorted(issues, key=lambda item: (severity_order[item.severity], item.title))
    )
