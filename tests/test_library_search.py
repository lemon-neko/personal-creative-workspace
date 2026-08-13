from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge_store import create_knowledge_card, load_knowledge_store
from app.library import create_material, load_materials, update_material_status
from app.search import SearchRepository
from app.workspace import create_item


class EmptyRepository:
    def projects(self):
        return ()

    def jobs(self):
        return ()

    def resumes(self):
        return ()

    def skills(self):
        return ()

    def learning_tasks(self):
        return ()


def test_material_urls_are_stored_without_fetching_and_status_is_local(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    material = create_material(
        content,
        title="待读论文",
        source_type="url",
        source_url="https://example.invalid/paper",
        body="关注时序记忆。",
    )
    changed = update_material_status(content, material.id, "reading")
    assert changed.source_url == "https://example.invalid/paper"
    assert changed.status == "reading"
    assert load_materials(content)[0].body == "关注时序记忆。"
    with pytest.raises(ValueError, match="HTTP"):
        create_material(
            content,
            title="危险链接",
            source_type="url",
            source_url="javascript:alert(1)",
        )


def test_fts_search_covers_sources_cards_and_materials(tmp_path: Path) -> None:
    content = tmp_path / "content"
    source = create_item(content, body="Graphiti 使用时序事实记录记忆。")
    create_knowledge_card(
        content,
        title="时序事实",
        body="事实带有有效时间，旧观点不会被覆盖。",
        card_type="concept",
        subjects=("技术",),
        concepts=("时序事实",),
        source_ids=(source.id,),
    )
    create_material(
        content,
        title="记忆系统阅读材料",
        body="Graphiti 项目笔记",
    )
    search = SearchRepository(tmp_path)
    search.rebuild(
        items=(source,),
        knowledge=load_knowledge_store(content),
        materials=load_materials(content),
        career=EmptyRepository(),
        video=EmptyRepository(),
    )
    results = search.search("时序")
    assert {result.result_type for result in results} >= {"thought", "knowledge-card"}
    assert all(result.url.startswith("/") for result in results)
    assert search.search("   ") == ()

