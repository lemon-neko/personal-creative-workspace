from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.knowledge_store import load_knowledge_store
from app.main import create_app
from app.model_gateway import (
    ModelGateway,
    ModelProvider,
    ModelTaskKind,
    ModelTaskStore,
    ModelUsageRepository,
    estimate_tokens,
    is_loopback_endpoint,
)
from app.workspace import create_item


def _knowledge_payload() -> str:
    return json.dumps(
        {
            "sources": [{"id": "idea-1", "title": "记忆", "body": "一条观察"}],
            "allowed_relation_targets": ["idea-1", "idea-2"],
            "allowed_map_ids": ["map-memory"],
        },
        ensure_ascii=False,
    )


def _knowledge_result(item_id: str = "idea-1", map_id: str = "map-memory") -> str:
    return json.dumps(
        {
            "suggestions": [
                {
                    "item_id": item_id,
                    "cards": [
                        {
                            "title": "记忆是一种选择",
                            "card_type": "claim",
                            "body": "记住什么，也意味着忽略什么。",
                            "subjects": ["认知科学", "哲学"],
                            "concepts": ["记忆"],
                            "map_ids": [map_id],
                            "relations": [
                                {
                                    "target_id": "idea-2",
                                    "type": "related",
                                    "note": "共享记忆主题",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )


def test_loopback_policy_and_default_rules(monkeypatch, tmp_path: Path) -> None:
    assert is_loopback_endpoint("http://127.0.0.1:11434/v1")
    assert is_loopback_endpoint("http://localhost:1234/v1")
    assert not is_loopback_endpoint("https://api.example.com/v1")

    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_MODEL", "paid-model")
    monkeypatch.delenv("MODEL_ALLOW_EXTERNAL", raising=False)
    gateway = ModelGateway(tmp_path)
    assert gateway.provider == ModelProvider.RULES
    assert not gateway.enabled


def test_local_provider_rejects_non_loopback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "not-local")
    with pytest.raises(ValueError, match="回环"):
        ModelGateway(tmp_path)


def test_model_prices_are_private_and_validated(tmp_path: Path) -> None:
    gateway = ModelGateway(tmp_path)
    gateway.save_prices(2.5, 10.0)
    reloaded = ModelGateway(tmp_path)
    assert (reloaded.input_price, reloaded.output_price) == (2.5, 10.0)
    with pytest.raises(ValueError, match="非负"):
        gateway.save_prices(-1, 1)


def test_manual_task_enforces_full_prompt_limit_and_expires_privately(
    tmp_path: Path,
) -> None:
    store = ModelTaskStore(tmp_path)
    task = store.create(
        task_type=ModelTaskKind.PUBLISH.value,
        purpose="公众号候选",
        source_labels=("来源",),
        payload=json.dumps({"title": "标题", "body": "正文"}, ensure_ascii=False),
        return_url="/publish/idea-1",
    )
    assert task.estimated_input_tokens == estimate_tokens(task.prompt)
    assert task.max_output_tokens == 6_000
    assert (store.root / f"{task.id}.json").stat().st_mode & 0o777 == 0o600

    with pytest.raises(ValueError, match="上限"):
        store.create(
            task_type=ModelTaskKind.PUBLISH.value,
            purpose="超限",
            source_labels=("来源",),
            payload="很多字" * 30_000,
            return_url="/models",
        )


def test_manual_knowledge_result_rejects_fabricated_ids_and_duplicate_import(
    tmp_path: Path,
) -> None:
    usage = ModelUsageRepository(tmp_path)
    store = ModelTaskStore(tmp_path, usage)
    task = store.create(
        task_type=ModelTaskKind.KNOWLEDGE.value,
        purpose="知识拆卡",
        source_labels=("记忆",),
        payload=_knowledge_payload(),
        return_url="/knowledge",
    )

    with pytest.raises(ValueError, match="来源 ID"):
        store.import_result(task.id, _knowledge_result(item_id="invented"))
    with pytest.raises(ValueError, match="地图 ID"):
        store.import_result(task.id, _knowledge_result(map_id="invented-map"))

    imported, value = store.import_result(task.id, _knowledge_result())
    assert imported.status == "imported"
    assert value["suggestions"][0]["item_id"] == "idea-1"
    assert usage.recent()[0].provider == "manual"
    assert usage.recent()[0].estimated_cost == 0
    with pytest.raises(ValueError, match="已经导入"):
        store.import_result(task.id, _knowledge_result())


def test_manual_result_rejects_invalid_shape_and_output_limit(tmp_path: Path) -> None:
    store = ModelTaskStore(tmp_path)
    task = store.create(
        task_type=ModelTaskKind.JOB_SKILLS.value,
        purpose="JD 技能",
        source_labels=("虚构职位",),
        payload="需要 Python 和 FastAPI",
        return_url="/career/jobs/job-1",
    )
    with pytest.raises(ValueError, match="合法 JSON"):
        store.import_result(task.id, "not-json")
    with pytest.raises(ValueError, match="重要度"):
        store.import_result(
            task.id,
            json.dumps({"skills": [{"name": "Python", "importance": 9}]}),
        )


def test_manual_knowledge_route_requires_explicit_confirmation(
    tmp_path: Path,
) -> None:
    app = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=False,
    )
    source = create_item(app.state.content_root, body="记忆具有时间属性。")
    client = TestClient(app)
    prepared = client.post("/knowledge/analyze/manual", follow_redirects=False)
    task_path = prepared.headers["location"]
    task_id = task_path.rsplit("/", 1)[-1]

    imported = client.post(
        f"/model-tasks/{task_id}/import",
        data={
            "result": json.dumps(
                {
                    "suggestions": [
                        {
                            "item_id": source.id,
                            "cards": [
                                {
                                    "title": "记忆的时间属性",
                                    "card_type": "claim",
                                    "body": "记忆中的事实可能只在某段时间成立。",
                                    "subjects": ["技术", "认知科学"],
                                    "concepts": ["时序记忆"],
                                    "map_ids": [],
                                    "relations": [],
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        },
        follow_redirects=False,
    )
    assert imported.status_code == 303
    assert load_knowledge_store(app.state.content_root).cards == ()

    confirmed = client.post(
        f"/model-tasks/{task_id}/confirm",
        data={
            "selected": "0-0",
            "title_0-0": "记忆的时间属性",
            "type_0-0": "claim",
            "body_0-0": "记忆中的事实可能只在某段时间成立。",
            "subjects_0-0": "技术，认知科学",
            "concepts_0-0": "时序记忆",
            "maps_0-0": "",
        },
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    card = load_knowledge_store(app.state.content_root).cards[0]
    assert card.source_ids == (source.id,)
    assert "时间" in card.body
