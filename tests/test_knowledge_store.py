from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.knowledge_store import (
    KnowledgeEdge,
    create_knowledge_card,
    create_knowledge_map,
    layered_graph,
    load_knowledge_store,
    supersede_knowledge_card,
    validate_map_graph,
)
from app.vault import apply_vault_migration, plan_vault_migration
from app.workspace import SHANGHAI, create_item


def test_multi_parent_maps_cards_and_provenance(tmp_path: Path) -> None:
    content = tmp_path / "content"
    source = create_item(content, body="Agent 记忆同时涉及技术与认知。")
    technology = create_knowledge_map(
        content,
        title="技术",
        kind="subject",
        summary="实现机制",
    )
    cognition = create_knowledge_map(
        content,
        title="认知科学",
        kind="subject",
        summary="人的记忆机制",
    )
    memory = create_knowledge_map(
        content,
        title="Agent 记忆",
        kind="topic",
        summary="跨学科记忆主题",
        parent_ids=(technology.id, cognition.id),
    )
    card = create_knowledge_card(
        content,
        title="记忆是选择性压缩",
        body="系统保留可复用事实，同时丢弃部分上下文。",
        card_type="claim",
        subjects=("技术", "认知科学"),
        concepts=("记忆", "压缩"),
        source_ids=(source.id,),
        map_ids=(memory.id,),
        relations=(KnowledgeEdge(source.id, "supports", "来源中的观察"),),
    )

    store = load_knowledge_store(content)
    graph = layered_graph((source,), store)
    assert technology.source.name.startswith("技术--")
    assert card.source.name.startswith("记忆是选择性压缩--")
    assert store.map(memory.id).parent_ids == (technology.id, cognition.id)
    assert store.card(card.id).source_ids == (source.id,)
    assert any(
        edge["source"] == card.id
        and edge["target"] == source.id
        and edge["type"] == "derived_from"
        for edge in graph["source_edges"]
    )
    assert {node["type"] for node in graph["nodes"]} == {
        "subject",
        "topic",
        "card",
    }
    assert not any(edge["type"] == "mentions" for edge in graph["edges"])
    assert [value["id"] for value in graph["sources"]] == [source.id]


def test_map_cycle_and_invalid_card_are_rejected(tmp_path: Path) -> None:
    content = tmp_path / "content"
    first = create_knowledge_map(
        content,
        title="第一层",
        kind="subject",
        summary="第一层摘要",
    )
    second = create_knowledge_map(
        content,
        title="第二层",
        kind="topic",
        summary="第二层摘要",
        parent_ids=(first.id,),
    )
    with pytest.raises(ValueError, match="循环"):
        validate_map_graph(
            (
                replace(first, parent_ids=(second.id,)),
                second,
            )
        )


def test_superseding_card_preserves_history_and_valid_time(tmp_path: Path) -> None:
    content = tmp_path / "content"
    source = create_item(content, body="最初的判断，后来有了修正。")
    old = create_knowledge_card(
        content,
        title="旧判断",
        body="这是旧观点，正文需要保留。",
        card_type="claim",
        subjects=("哲学",),
        source_ids=(source.id,),
    )
    replacement = create_knowledge_card(
        content,
        title="新判断",
        body="这是经过修正的新观点。",
        card_type="claim",
        subjects=("哲学",),
        source_ids=(source.id,),
    )
    retired = supersede_knowledge_card(content, old.id, replacement.id)
    assert retired.status == "superseded"
    assert retired.superseded_by == replacement.id
    assert retired.valid_to is not None
    assert retired.body == "这是旧观点，正文需要保留。"
    with pytest.raises(ValueError, match="1–3"):
        create_knowledge_card(
            content,
            title="没有学科",
            body="无效卡片",
            card_type="claim",
            subjects=(),
            source_ids=(source.id,),
        )


def test_vault_migration_is_dry_run_checksummed_and_keeps_rollback(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    item = create_item(
        content,
        body="旧目录中的原始想法",
        now=datetime(2026, 8, 1, 12, tzinfo=SHANGHAI),
    )
    legacy = content / "items"
    legacy.mkdir(parents=True)
    legacy_file = legacy / item.source.name
    shutil.copy2(item.source, legacy_file)
    item.source.unlink()

    plan = plan_vault_migration(content)
    assert len(plan) == 1 and plan[0].action == "copy"
    assert not plan[0].destination.exists()
    rollback = apply_vault_migration(content, plan)
    assert plan[0].destination.exists()
    assert rollback is not None and (rollback / legacy_file.name).exists()
    assert plan_vault_migration(content) == ()
