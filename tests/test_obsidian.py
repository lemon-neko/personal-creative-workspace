from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi.testclient import TestClient

from app.content import (
    MANAGED_LINKS_END,
    MANAGED_LINKS_START,
    load_items,
    parse_item,
    render_markdown,
    semantic_revision,
)
from app.knowledge import stale_items
from app.main import create_app
from app.knowledge_store import create_knowledge_card, create_knowledge_map
from app.obsidian import (
    ObsidianBridge,
    inbox_directory,
    knowledge_inbox_directory,
    templates_directory,
)
from app.publishing import PublishingSource, WeChatRenderer, resolve_publishing_source
from app.workspace import (
    ContentConflictError,
    create_item,
    update_item,
    update_knowledge_metadata,
)


def _insert_property(path: Path, text: str) -> None:
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace("---\n\n", f"{text}\n---\n\n", 1), encoding="utf-8")


def test_obsidian_properties_and_managed_links_survive_workspace_edit(
    tmp_path: Path,
) -> None:
    item = create_item(tmp_path, body="原始正文。", title="属性测试")
    _insert_property(
        item.source,
        "aliases:\n- 属性别名\ncustom:\n  nested: true",
    )
    with item.source.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n{MANAGED_LINKS_START}\n\n## 工作台关联\n\n{MANAGED_LINKS_END}\n",
        )

    loaded = parse_item(item.source)
    assert loaded.body == "原始正文。"
    assert loaded.extra_metadata["aliases"] == ["属性别名"]
    assert loaded.extra_metadata["custom"] == {"nested": True}
    assert loaded.managed_links.startswith(MANAGED_LINKS_START)

    updated = update_item(tmp_path, item.id, body="更新后的正文。", title="属性测试")
    metadata = yaml.safe_load(
        updated.source.read_text(encoding="utf-8").split("---", 2)[1]
    )
    assert metadata["aliases"] == ["属性别名"]
    assert metadata["custom"] == {"nested": True}
    assert MANAGED_LINKS_START in updated.source.read_text(encoding="utf-8")


def test_workspace_rejects_stale_obsidian_edit_revision(tmp_path: Path) -> None:
    item = create_item(tmp_path, body="第一版。")
    opened_revision = semantic_revision(item)
    source = item.source.read_text(encoding="utf-8")
    item.source.write_text(
        source.replace("第一版。", "Obsidian 新版本。"), encoding="utf-8"
    )

    try:
        update_item(
            tmp_path,
            item.id,
            body="网页表单版本。",
            expected_revision=opened_revision,
        )
    except ContentConflictError as error:
        assert error.current.body == "Obsidian 新版本。"
    else:
        raise AssertionError("stale edit should be rejected")
    assert parse_item(item.source).body == "Obsidian 新版本。"


def test_scan_reconciles_external_edit_and_marks_knowledge_stale(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    item = create_item(content, body="记忆像文件。")
    confirmed = update_knowledge_metadata(
        content,
        item.id,
        subjects="技术",
        concepts="记忆",
    )
    bridge = ObsidianBridge(tmp_path, content)
    bridge.scan()
    raw = confirmed.source.read_text(encoding="utf-8")
    confirmed.source.write_text(
        raw.replace("记忆像文件。", "记忆也像河流。"), encoding="utf-8"
    )

    state = bridge.scan()
    refreshed = load_items(content)
    changed = refreshed.get(item.id)

    assert state.external_changes == 1
    assert changed is not None
    assert changed.body == "记忆也像河流。"
    assert "记忆也像河流" in changed.summary
    assert [value.id for value in stale_items(refreshed)] == [item.id]


def test_projection_builds_native_links_without_leaking_into_body(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    source = create_item(content, body="第一个想法。", title="来源想法")
    subject = create_knowledge_map(
        content,
        title="哲学",
        kind="subject",
        summary="理解世界的方式",
    )
    topic = create_knowledge_map(
        content,
        title="选择",
        kind="topic",
        summary="选择如何形成",
        parent_ids=(subject.id,),
    )
    card = create_knowledge_card(
        content,
        title="选择来自既有参数",
        body="判断会受到过去经验影响。",
        card_type="claim",
        subjects=("哲学",),
        source_ids=(source.id,),
        map_ids=(topic.id,),
    )
    bridge = ObsidianBridge(tmp_path, content)

    assert bridge.rebuild_links() >= 1
    raw = card.source.read_text(encoding="utf-8")
    loaded = parse_item(source.source)
    publishing = resolve_publishing_source(content, source.id)

    assert MANAGED_LINKS_START in raw
    assert source.source.relative_to(content).as_posix() in raw
    assert loaded.body == "第一个想法。"
    assert publishing is not None
    assert "工作台关联" not in publishing.markdown
    home = content / "知识首页.md"
    assert home.is_file()
    assert quote(subject.source.relative_to(content).as_posix(), safe="/") in home.read_text(
        encoding="utf-8"
    )
    assert card.source.relative_to(content).as_posix() not in home.read_text(
        encoding="utf-8"
    )


def test_inbox_import_is_explicit_and_rewrites_absolute_vault_links(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    bridge = ObsidianBridge(tmp_path, content)
    inbox = inbox_directory(content)
    draft = inbox / "突然想到.md"
    draft.write_text(
        "# 蛋糕的切法\n\n横着切，竖着切，也可以漂移着切。", encoding="utf-8"
    )
    existing = create_item(
        content,
        body="参见 [收件箱](sources/inbox/突然想到.md)。",
        title="已有链接",
    )
    candidate = bridge.inbox()[0]

    imported = bridge.import_inbox(
        candidate.id,
        expected_revision=candidate.revision,
        tags="生活观察",
    )

    assert not draft.exists()
    assert imported.title == "蛋糕的切法"
    assert imported.tags == ("生活观察",)
    assert "sources/thoughts/" in parse_item(existing.source).body
    assert "sources/inbox/" not in parse_item(existing.source).body


def test_markdown_renderer_maps_private_assets_and_vault_notes(tmp_path: Path) -> None:
    content = tmp_path / "content"
    target = create_item(content, body="目标。", title="目标")
    markdown = (
        "![图](assets/local.png)\n\n"
        f"[目标]({target.source.relative_to(content).as_posix()})"
    )
    html = render_markdown(markdown, source=target.source, content_root=content)
    assert 'src="/assets/local.png"' in html
    assert f'href="/ideas/{target.id}"' in html


def test_wechat_renderer_removes_private_vault_links() -> None:
    rendered = WeChatRenderer().render(
        PublishingSource(
            source_id="private-link",
            kind="article",
            title="标题",
            summary="摘要",
            markdown="参考 [私人卡片](knowledge/cards/card-1.md) 的结论。",
        ),
    )
    assert "knowledge/cards" not in rendered.html
    assert "私人卡片" in rendered.html
    assert any("私人 Obsidian Vault" in value for value in rendered.warnings)


def test_obsidian_routes_and_conflict_page(tmp_path: Path) -> None:
    app = create_app(content_root=tmp_path, enable_scheduler=False)
    client = TestClient(app)
    item = create_item(tmp_path, body="浏览器打开的版本。")

    page = client.get("/settings/obsidian")
    detail = client.get(f"/ideas/{item.id}")
    assert page.status_code == 200
    assert "Obsidian 知识后台" in page.text
    assert "obsidian://open?path=" in detail.text

    opened_revision = semantic_revision(item)
    item.source.write_text(
        item.source.read_text(encoding="utf-8").replace(
            "浏览器打开的版本。", "外部版本。"
        ),
        encoding="utf-8",
    )
    conflict = client.post(
        f"/ideas/{item.id}",
        data={
            "body": "表单版本。",
            "title": "",
            "tags": "",
            "category": "",
            "source_revision": opened_revision,
        },
    )
    assert conflict.status_code == 409
    assert "工作台没有覆盖" in conflict.text
    assert parse_item(item.source).body == "外部版本。"


def test_knowledge_templates_are_explicitly_imported(tmp_path: Path) -> None:
    content = tmp_path / "content"
    source = create_item(content, body="Agent 会压缩上下文。", title="记忆观察")
    subject = create_knowledge_map(
        content,
        title="技术",
        kind="subject",
        summary="软件和人工智能的实现机制",
    )
    topic = create_knowledge_map(
        content,
        title="Agent 记忆",
        kind="topic",
        summary="上下文如何形成长期记忆",
        parent_ids=(subject.id,),
    )
    bridge = ObsidianBridge(tmp_path, content)

    assert bridge.initialize_templates() == 3
    assert {path.name for path in templates_directory(content).glob("*.md")} == {
        "知识卡模板.md",
        "主题地图模板.md",
        "学科地图模板.md",
    }
    draft = knowledge_inbox_directory(content) / "记忆压缩.md"
    draft.write_text(
        """---
workspace_type: knowledge-card
title: 记忆是一种选择性压缩
card_type: claim
subjects:
- 技术
concepts:
- 记忆
- 压缩
---

系统保留可复用信息，而不是保存全部上下文。
""",
        encoding="utf-8",
    )
    candidate = bridge.knowledge_inbox()[0]

    card = bridge.import_knowledge_inbox(
        candidate.id,
        expected_revision=candidate.revision,
        title=candidate.title,
        source_ids=(source.id,),
        map_ids=(topic.id,),
        subjects=candidate.subjects,
        concepts=candidate.concepts,
    )

    assert card.source.name.startswith("记忆是一种选择性压缩--")
    assert card.source_ids == (source.id,)
    assert card.map_ids == (topic.id,)
    assert not draft.exists()


def test_legacy_reconciliation_renames_safely_and_rolls_back(tmp_path: Path) -> None:
    content = tmp_path / "content"
    source = create_item(content, body="原始正文保持不变。", title="人的选择")
    source = update_knowledge_metadata(
        content,
        source.id,
        subjects="哲学",
        concepts="选择",
    )
    subject = create_knowledge_map(
        content,
        title="哲学",
        kind="subject",
        summary="理解选择与因果",
    )
    topic = create_knowledge_map(
        content,
        title="选择与因果",
        kind="topic",
        summary="人的选择如何形成",
        parent_ids=(subject.id,),
    )
    create_knowledge_card(
        content,
        title="选择受到历史经验影响",
        body="过去的经验会改变下一次判断。",
        card_type="claim",
        subjects=("哲学",),
        concepts=("选择",),
        source_ids=(source.id,),
        map_ids=(topic.id,),
    )
    original_path = source.source
    bridge = ObsidianBridge(tmp_path, content)
    preview = bridge.migration_preview()

    assert preview.can_apply
    assert preview.reconciliations[0].state == "covered"
    assert any(value.item_id == source.id for value in preview.renames)

    bridge.apply_migration("整理知识库")
    migrated = load_items(content).get(source.id)
    assert migrated is not None
    assert migrated.body == "原始正文保持不变。"
    assert migrated.subjects == ()
    assert migrated.concepts == ()
    assert migrated.source.name.startswith("人的选择--")
    assert not original_path.exists()

    bridge.rollback_latest_migration("恢复整理前版本")
    restored = load_items(content).get(source.id)
    assert restored is not None
    assert restored.source == original_path
    assert restored.subjects == ("哲学",)
    assert restored.concepts == ("选择",)
