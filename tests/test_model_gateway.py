from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.knowledge_store import create_knowledge_map, load_knowledge_store
from app.main import create_app
from app.model_gateway import (
    ModelGateway,
    ModelProvider,
    ModelTaskKind,
    ModelTaskStore,
    ModelUsageRecord,
    ModelUsageRepository,
    estimate_tokens,
    is_loopback_endpoint,
    validate_manual_result,
)
from app.llm import LLMConfig
from app.workspace import SHANGHAI
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
    assert estimate_tokens("") == 0
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


def test_usage_ledger_totals_and_price_roundtrip(tmp_path: Path) -> None:
    usage = ModelUsageRepository(tmp_path)
    assert usage.totals() == {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": 0,
    }
    usage.record(
        ModelUsageRecord(
            id="usage-1",
            task_type="publish",
            provider="external",
            model="fake",
            estimated_input_tokens=20,
            input_tokens=12,
            output_tokens=8,
            latency_ms=5,
            status="success",
            estimated_cost=0.25,
            created_at=datetime.now(SHANGHAI).isoformat(),
        )
    )
    assert usage.totals()["calls"] == 1
    assert usage.totals()["input_tokens"] == 12
    assert usage.totals()["cost"] == pytest.approx(0.25)
    assert usage.recent(limit=0)[0].id == "usage-1"


@pytest.mark.parametrize(
    ("task_type", "payload"),
    [
        ("weekly-review", {"markdown": "本周记录"}),
        (
            "assistant",
            {
                "assistant_summary": "先完成最小闭环",
                "user_intent_summary": "判断下一步",
            },
        ),
        ("publish", {"title": "标题", "markdown": "正文", "image_suggestions": []}),
        (
            "profile",
            {
                "target_roles": "Agent 开发",
                "contact": "",
                "education": "",
                "experience": "",
                "certifications": "",
                "skills": "Python",
                "facts": "四年经验",
            },
        ),
        ("job-skills", {"skills": [{"name": "Python", "importance": 4}]}),
        (
            "resume-parse",
            {
                "resume": {
                    "personal_info": {"name": "测试作者"},
                    "summary": "Agent 应用开发",
                    "work_experience": [],
                    "education": [],
                    "projects": [],
                    "skills": ["Python"],
                    "sections": [],
                }
            },
        ),
        (
            "resume-tailor",
            {
                "suggestions": [
                    {
                        "path": "summary",
                        "before": "当前摘要",
                        "after": "候选摘要",
                        "reason": "突出岗位重点",
                        "evidence_ids": ["career-profile"],
                    }
                ]
            },
        ),
    ],
)
def test_manual_result_validates_all_task_shapes(task_type: str, payload: dict) -> None:
    raw = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    validated = validate_manual_result(task_type, raw)
    if task_type == "resume-parse":
        assert validated["resume"]["personal_info"]["name"] == "测试作者"
        assert validated["resume"]["skills"] == ["Python"]
        assert validated["resume"]["sections"]
    else:
        assert validated == payload


@pytest.mark.parametrize(
    ("task_type", "payload", "message"),
    [
        ("weekly-review", {"markdown": ""}, "不能为空"),
        ("publish", {"title": "", "markdown": "正文"}, "标题或正文为空"),
        ("publish", {"title": "标题", "markdown": "正文", "image_suggestions": "图"}, "列表"),
        ("profile", {"facts": []}, "必须是文本"),
        ("job-skills", {"skills": [{"name": ""}]}, "名称无效"),
        ("job-skills", {"skills": [{"name": "Python", "importance": "高"}]}, "重要度无效"),
        ("resume-parse", {"resume": []}, "必须是对象"),
        (
            "resume-tailor",
            {"suggestions": [{} for _ in range(41)]},
            "最多 40 条",
        ),
    ],
)
def test_manual_result_rejects_task_specific_invalid_values(
    task_type: str, payload: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_manual_result(task_type, json.dumps(payload, ensure_ascii=False))


def test_manual_knowledge_candidate_validation_boundaries() -> None:
    base = json.loads(_knowledge_result())
    for key, value, message in (
        ("card_type", "unknown", "类型无效"),
        ("subjects", [], "1–3"),
        ("concepts", list(map(str, range(9))), "概念数量"),
        ("map_ids", list(map(str, range(9))), "地图数量"),
        ("relations", [{"type": "unknown", "target_id": "idea-2"}], "关系无效"),
    ):
        candidate = json.loads(json.dumps(base))
        candidate["suggestions"][0]["cards"][0][key] = value
        with pytest.raises(ValueError, match=message):
            validate_manual_result("knowledge", json.dumps(candidate, ensure_ascii=False))


class FakeModelClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434/v1") -> None:
        self.config = LLMConfig(base_url, "local-key", "fake-model")
        self.enabled = True
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 4}
        self.fail = False

    @contextmanager
    def output_limit(self, _limit: int):
        yield

    def _result(self, value):
        if self.fail:
            raise RuntimeError("fake failure")
        return value

    def polish(self, **_kwargs):
        return self._result("polished")

    def summarize(self, _items):
        return self._result("summary")

    def analyze_knowledge(self, *_args):
        return self._result("knowledge")

    def analyze_knowledge_material(self, *_args):
        return self._result("material")

    def knowledge_card_candidate(self, _material):
        return self._result(json.loads(_knowledge_result()))

    def profile_candidate(self, _material):
        return self._result({"facts": "fact"})

    def job_skill_candidate(self, _material):
        return self._result({"skills": []})

    def assistant_candidate(self, _material):
        return self._result({"assistant_summary": "先完成最小闭环"})

    def resume_parse_candidate(self, _material):
        return self._result(
            {
                "resume": {
                    "personal_info": {"name": "测试作者"},
                    "summary": "Agent 应用开发",
                    "work_experience": [],
                    "education": [],
                    "projects": [],
                    "skills": ["Python"],
                    "sections": [],
                }
            }
        )

    def resume_tailor_candidate(self, _material):
        return self._result(
            {
                "suggestions": [
                    {
                        "path": "summary",
                        "before": "当前摘要",
                        "after": "候选摘要",
                        "reason": "突出岗位重点",
                        "evidence_ids": ["career-profile"],
                    }
                ]
            }
        )


def test_gateway_records_local_success_failure_and_facade_calls(tmp_path: Path) -> None:
    client = FakeModelClient()
    gateway = ModelGateway(tmp_path, client=client)  # type: ignore[arg-type]
    source = create_item(tmp_path / "content", body="模型网关测试")
    assert gateway.provider == ModelProvider.LOCAL
    assert gateway.polish(title="标题", body="正文", mode="auto") == "polished"
    assert gateway.summarize((source,)) == "summary"
    assert gateway.analyze_knowledge((source,), (), ()) == "knowledge"
    assert gateway.analyze_knowledge_material('{"items":[]}', ()) == "material"
    assert gateway.knowledge_card_candidate(_knowledge_payload())["suggestions"]
    assert gateway.profile_candidate("profile") == {"facts": "fact"}
    assert gateway.job_skill_candidate("jd") == {"skills": []}
    assert gateway.assistant_candidate("assistant") == {
        "assistant_summary": "先完成最小闭环"
    }
    assert gateway.resume_parse_candidate("resume")["resume"]["summary"]
    assert gateway.resume_tailor_candidate("tailor")["suggestions"]
    assert any(row.task_type == "assistant" for row in gateway.usage.recent())
    assert all(row.estimated_cost == 0 for row in gateway.usage.recent())

    client.fail = True
    with pytest.raises(RuntimeError, match="fake failure"):
        gateway.polish(title="标题", body="正文", mode="auto")
    assert any(row.status == "failed" for row in gateway.usage.recent())


def test_gateway_external_requires_explicit_opt_in(monkeypatch, tmp_path: Path) -> None:
    client = FakeModelClient("https://api.example.test/v1")
    assert ModelGateway(tmp_path, client=client).provider == ModelProvider.RULES  # type: ignore[arg-type]
    monkeypatch.setenv("MODEL_ALLOW_EXTERNAL", "true")
    gateway = ModelGateway(tmp_path, client=client)  # type: ignore[arg-type]
    gateway.save_prices(2.0, 4.0)
    assert gateway.provider == ModelProvider.EXTERNAL
    assert gateway.polish(title="标题", body="正文", mode="auto") == "polished"
    assert gateway.usage.recent()[0].estimated_cost is not None


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
    subject = create_knowledge_map(
        app.state.content_root,
        title="技术",
        kind="subject",
        summary="软件和人工智能系统。",
    )
    topic = create_knowledge_map(
        app.state.content_root,
        title="时序记忆",
        kind="topic",
        summary="记忆在时间中的变化。",
        parent_ids=(subject.id,),
    )
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
                                    "map_ids": [topic.id],
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
            "maps_0-0": topic.id,
        },
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    card = load_knowledge_store(app.state.content_root).cards[0]
    assert card.source_ids == (source.id,)
    assert "时间" in card.body
