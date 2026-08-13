from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.content import KnowledgeRelation, load_items
from app.knowledge import (
    build_knowledge_graph,
    eligible_items,
    load_knowledge_index,
    rebuild_knowledge_index,
    stale_items,
    validate_suggestions,
)
from app.workspace import (
    SHANGHAI,
    create_item,
    items_directory,
    update_item,
    update_knowledge_metadata,
)


def test_confirmed_metadata_preserves_content_and_becomes_stale_after_edit(
    tmp_path: Path,
) -> None:
    created = create_item(
        tmp_path,
        title="一条跨学科想法",
        body="技术也会改变我们理解自己的方式。",
        now=datetime(2026, 8, 1, 9, 0, tzinfo=SHANGHAI),
    )
    confirmed = update_knowledge_metadata(
        tmp_path,
        created.id,
        subjects="技术，哲学",
        concepts="人工智能，自我理解",
        now=datetime(2026, 8, 1, 10, 0, tzinfo=SHANGHAI),
    )

    assert confirmed.body == created.body
    assert confirmed.title == created.title
    assert confirmed.status == created.status
    assert confirmed.updated_at == created.updated_at
    assert confirmed.subjects == ("技术", "哲学")
    assert stale_items(load_items(items_directory(tmp_path))) == ()

    edited = update_item(
        tmp_path,
        created.id,
        title=created.title,
        body=f"{created.body}\n\n继续补充。",
        now=datetime(2026, 8, 1, 11, 0, tzinfo=SHANGHAI),
    )

    assert edited.subjects == ("技术", "哲学")
    assert [item.id for item in stale_items(load_items(items_directory(tmp_path)))] == [
        created.id,
    ]


def test_suggestions_reject_unknown_ids_and_relation_types(tmp_path: Path) -> None:
    first = create_item(tmp_path, body="第一条。")
    second = create_item(tmp_path, body="第二条。")
    items = (first, second)
    valid = {
        "suggestions": [
            {
                "item_id": first.id,
                "subjects": ["哲学"],
                "concepts": ["选择"],
                "relations": [
                    {
                        "target_id": second.id,
                        "type": "contrasts",
                        "note": "不同判断",
                    },
                ],
            },
        ],
    }

    assert validate_suggestions(valid, items)[0].relations[0].relation == "contrasts"
    valid["suggestions"][0]["relations"][0]["target_id"] = "missing"
    with pytest.raises(ValueError, match="关联目标"):
        validate_suggestions(valid, items)


def test_graph_contains_concepts_lineage_and_confirmed_relations(tmp_path: Path) -> None:
    source = create_item(tmp_path, body="原始想法。", title="原始想法")
    article = create_item(
        tmp_path,
        body="由原始想法长成的文章。",
        title="文章",
        kind="article",
        parent_id=source.id,
    )
    update_knowledge_metadata(
        tmp_path,
        source.id,
        subjects=["技术", "哲学"],
        concepts=["记忆", "认知"],
        relations=[KnowledgeRelation(article.id, "supports", "文章补充了论证")],
    )
    update_knowledge_metadata(
        tmp_path,
        article.id,
        subjects=["技术"],
        concepts=["记忆"],
    )
    items = eligible_items(load_items(items_directory(tmp_path)))
    graph = build_knowledge_graph(items)

    assert len([node for node in graph.nodes if node["type"] == "item"]) == 2
    assert {node["label"] for node in graph.nodes if node["type"] == "concept"} == {
        "记忆",
        "认知",
    }
    assert {edge["type"] for edge in graph.edges} >= {
        "mentions",
        "cooccurs",
        "derived_from",
        "supports",
    }


def test_index_is_persisted_but_not_added_to_content_items(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="经济决策也受到心理影响。")
    update_knowledge_metadata(
        tmp_path,
        item.id,
        subjects=["经济学", "心理学"],
        concepts=["决策偏差"],
    )
    items = eligible_items(load_items(items_directory(tmp_path)))

    saved = rebuild_knowledge_index(
        tmp_path,
        items,
        model_summaries={"经济学": "当前记录关注决策中的心理因素。"},
    )
    loaded = load_knowledge_index(tmp_path, items)

    assert saved.persisted is True
    assert (tmp_path / "knowledge" / "indexes" / "subject-index.yaml").exists()
    assert load_items(items_directory(tmp_path)).get(item.id) is not None
    economics = next(subject for subject in loaded.subjects if subject.name == "经济学")
    assert economics.summary == "当前记录关注决策中的心理因素。"
