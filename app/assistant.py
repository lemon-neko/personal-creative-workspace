"""Private, source-backed decision assistant state and context projection."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.career import CareerRepository
from app.content import load_items
from app.database import WORKSPACE_REGISTRY, apply_migrations, connect_database
from app.knowledge_quality import inspect_knowledge_quality
from app.knowledge_store import load_knowledge_store
from app.workspace import SHANGHAI, items_directory


ASSISTANT_ACTION_TYPES = {"create-thought", "create-learning-task"}
ASSISTANT_CONVERSATION_STATUSES = {"active", "archived"}
MAX_ASSISTANT_QUESTION = 2_000
MAX_ASSISTANT_CONTEXT = 80_000


def _now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def _short(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[已隐藏邮箱]",
        text,
    )
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[已隐藏手机号]", text)
    text = re.sub(r"(?i)\b(?:sk|api)[-_][A-Z0-9_-]{12,}\b", "[已隐藏密钥]", text)
    text = re.sub(r"/(?:Users|home)/[^\s\"']+", "[已隐藏本地路径]", text)
    return text[:limit]


@dataclass(frozen=True)
class AssistantSource:
    id: str
    kind: str
    title: str
    url: str


@dataclass(frozen=True)
class AssistantContextSnapshot:
    material: str
    sources: tuple[AssistantSource, ...]
    allowed_skill_ids: tuple[str, ...]


@dataclass(frozen=True)
class AssistantEvidence:
    source_id: str
    reason: str
    title: str = ""
    url: str = ""


@dataclass(frozen=True)
class AssistantSuggestion:
    id: str
    action_type: str
    title: str
    body: str
    skill_id: str
    priority: int


@dataclass(frozen=True)
class AssistantRecommendation:
    user_intent_summary: str
    assistant_summary: str
    priority_title: str
    reason: str
    steps: tuple[str, ...]
    success_criteria: str
    evidence: tuple[AssistantEvidence, ...]
    assumptions: tuple[str, ...]
    clarifying_question: str
    suggestions: tuple[AssistantSuggestion, ...]


@dataclass(frozen=True)
class AssistantConversation:
    id: str
    title: str
    status: str
    summary: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AssistantTurnSummary:
    id: str
    conversation_id: str
    user_intent_summary: str
    assistant_summary: str
    priority_title: str
    reason: str
    steps: tuple[str, ...]
    success_criteria: str
    evidence: tuple[AssistantEvidence, ...]
    assumptions: tuple[str, ...]
    clarifying_question: str
    suggestions: tuple[AssistantSuggestion, ...]
    created_at: str


@dataclass(frozen=True)
class AssistantDecision:
    id: str
    turn_id: str
    action_id: str
    action_type: str
    status: str
    target_id: str
    created_at: str


def _string_list(value: object, *, limit: int, item_limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("助手返回的列表字段格式无效")
    rows = tuple(_short(item, item_limit) for item in value if _short(item, item_limit))
    if len(rows) > limit:
        raise ValueError("助手返回的列表条目过多")
    return rows


def validate_assistant_result(
    payload: object,
    *,
    allowed_source_ids: set[str],
    allowed_skill_ids: set[str],
) -> AssistantRecommendation:
    """Validate a model candidate before storing even its summary."""

    if not isinstance(payload, dict):
        raise ValueError("助手返回内容必须是 JSON 对象")
    intent = _short(payload.get("user_intent_summary"), 300)
    summary = _short(payload.get("assistant_summary"), 1_200)
    priority_title = _short(payload.get("priority_title"), 200)
    reason = _short(payload.get("reason"), 1_500)
    success = _short(payload.get("success_criteria"), 800)
    clarification = _short(payload.get("clarifying_question"), 500)
    steps = _string_list(payload.get("steps", []), limit=3, item_limit=500)
    assumptions = _string_list(
        payload.get("assumptions", []), limit=6, item_limit=400
    )
    if not intent or not summary:
        raise ValueError("助手返回缺少意图摘要或回答摘要")
    if clarification:
        if priority_title or reason or steps or success:
            raise ValueError("需要澄清时不能同时给出未经确认的优先结论")
    elif not priority_title or not reason or len(steps) != 3 or not success:
        raise ValueError("助手回答必须包含一个优先事项、理由、三个步骤和完成标准")

    raw_evidence = payload.get("evidence", [])
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 12:
        raise ValueError("助手来源引用格式无效")
    evidence: list[AssistantEvidence] = []
    for row in raw_evidence:
        if not isinstance(row, dict):
            raise ValueError("助手来源引用格式无效")
        source_id = _short(row.get("source_id"), 200)
        reason_text = _short(row.get("reason"), 500)
        if source_id not in allowed_source_ids or not reason_text:
            raise ValueError("助手引用了本轮上下文之外的来源")
        evidence.append(AssistantEvidence(source_id, reason_text))
    if not clarification and not evidence:
        raise ValueError("助手结论必须引用至少一个本轮来源")

    raw_suggestions = payload.get("suggested_actions", [])
    if not isinstance(raw_suggestions, list) or len(raw_suggestions) > 4:
        raise ValueError("助手候选操作格式无效")
    suggestions: list[AssistantSuggestion] = []
    for index, row in enumerate(raw_suggestions):
        if not isinstance(row, dict):
            raise ValueError("助手候选操作格式无效")
        action_type = _short(row.get("type"), 60)
        title = _short(row.get("title"), 200)
        body = str(row.get("body", "")).strip()[:10_000]
        skill_id = _short(row.get("skill_id"), 160)
        try:
            priority = int(row.get("priority", 3))
        except (TypeError, ValueError) as error:
            raise ValueError("学习任务优先级无效") from error
        if action_type not in ASSISTANT_ACTION_TYPES or not title or not body:
            raise ValueError("助手返回了不允许的候选操作")
        if priority not in range(1, 6):
            raise ValueError("学习任务优先级无效")
        if action_type == "create-learning-task":
            if skill_id not in allowed_skill_ids:
                raise ValueError("助手引用了不存在的技能")
        elif skill_id:
            raise ValueError("新想法候选不能绑定技能")
        suggestions.append(
            AssistantSuggestion(
                id=f"action-{index + 1}",
                action_type=action_type,
                title=title,
                body=body,
                skill_id=skill_id,
                priority=priority,
            )
        )
    if clarification and suggestions:
        raise ValueError("需要澄清时不能同时提出写入操作")
    return AssistantRecommendation(
        user_intent_summary=intent,
        assistant_summary=summary,
        priority_title=priority_title,
        reason=reason,
        steps=steps,
        success_criteria=success,
        evidence=tuple(evidence),
        assumptions=assumptions,
        clarifying_question=clarification,
        suggestions=tuple(suggestions),
    )


class AssistantContextBuilder:
    """Build a bounded, reviewable snapshot without private documents or secrets."""

    def __init__(self, content_root: Path, career: CareerRepository, search, video) -> None:
        self.content_root = content_root
        self.career = career
        self.search = search
        self.video = video

    def build(self, question: str, *, conversation_summary: str = "") -> AssistantContextSnapshot:
        clean_question = str(question).strip()[:MAX_ASSISTANT_QUESTION]
        if not clean_question:
            raise ValueError("请先写下想问助手的问题")
        collection = load_items(items_directory(self.content_root))
        store = load_knowledge_store(self.content_root)
        issues = inspect_knowledge_quality(collection.items, store)
        skills = self.career.skills()
        skill_lookup = {skill.id: skill for skill in skills}
        jobs = tuple(
            job
            for job in self.career.jobs()
            if job.status not in {"rejected", "withdrawn", "archived"}
        )[:5]
        job_ids = {job.id for job in jobs}
        gaps = tuple(
            gap for gap in self.career.gaps() if gap.job_id in job_ids
        )[:8]
        tasks = tuple(
            task
            for task in self.career.learning_tasks()
            if task.status in {"backlog", "active"}
        )[:8]
        campaigns = tuple(
            campaign
            for campaign in self.career.campaigns()
            if campaign.status in {"planned", "active"}
        )[:3]
        quests = tuple(
            quest
            for campaign in campaigns
            for quest in self.career.quests(campaign.id)
            if quest.status in {"available", "active"}
        )[:5]
        thoughts = tuple(
            item
            for item in collection.items
            if item.kind == "thought" and item.status != "archived"
        )[:5]
        reviews = tuple(
            item for item in collection.items if item.kind == "weekly-review"
        )[:1]
        articles = tuple(
            item
            for item in collection.items
            if item.kind == "article" and item.status == "draft"
        )[:5]
        video_projects = tuple(
            project
            for project in self.video.projects()
            if project.status != "archived"
        )[:5]
        recent_cards = tuple(
            card for card in store.cards if card.status == "active"
        )[:5]
        search_results = self.search.search(clean_question, limit=8)

        sources: dict[str, AssistantSource] = {}

        def source(source_id: str, kind: str, title: str, url: str) -> None:
            if source_id and source_id not in sources:
                sources[source_id] = AssistantSource(
                    source_id, kind, _short(title, 200), url
                )

        profile = self.career.profile()
        if profile.target_roles:
            source("career-profile", "career-profile", "候选人目标方向", "/career/profile")
        for job in jobs:
            source(job.id, "career-job", f"{job.company} · {job.title}", f"/career/jobs/{job.id}")
        for task in tasks:
            source(task.id, "learning-task", task.title, "/learning")
        for campaign in campaigns:
            source(campaign.id, "campaign", campaign.name, f"/learning/campaigns/{campaign.id}")
        for quest in quests:
            source(quest.id, "quest", quest.title, f"/learning/campaigns/{quest.campaign_id}")
        for item in (*thoughts, *reviews, *articles):
            source(item.id, item.kind, item.title, f"/ideas/{item.id}")
        for project in video_projects:
            source(project.id, "video-project", project.title, f"/video?project={project.id}")
        for card in recent_cards:
            source(card.id, "knowledge-card", card.title, f"/knowledge/cards/{card.id}")
        for result in search_results:
            source(result.id, result.result_type, result.title, result.url)

        issue_counts: dict[str, int] = {}
        for issue in issues:
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1

        state: dict[str, Any] = {
            "career": {
                "target_roles": _short(profile.target_roles, 500),
                "active_jobs": [
                    {
                        "id": job.id,
                        "company": _short(job.company, 120),
                        "title": _short(job.title, 120),
                        "status": job.status,
                        "updated_at": job.updated_at,
                    }
                    for job in jobs
                ],
                "skill_gaps": [
                    {
                        "job_id": gap.job_id,
                        "skill_id": gap.skill_id,
                        "skill": _short(
                            getattr(skill_lookup.get(gap.skill_id), "name", ""), 120
                        ),
                        "importance": gap.importance,
                        "gap": _short(gap.gap_note, 240),
                    }
                    for gap in gaps
                ],
            },
            "learning": {
                "tasks": [
                    {
                        "id": task.id,
                        "title": _short(task.title, 200),
                        "status": task.status,
                        "priority": task.priority,
                        "skill_id": task.skill_id,
                        "skill": _short(
                            getattr(skill_lookup.get(task.skill_id), "name", ""), 120
                        ),
                    }
                    for task in tasks
                ],
                "campaigns": [
                    {
                        "id": campaign.id,
                        "name": _short(campaign.name, 160),
                        "status": campaign.status,
                    }
                    for campaign in campaigns
                ],
                "available_quests": [
                    {
                        "id": quest.id,
                        "campaign_id": quest.campaign_id,
                        "title": _short(quest.title, 160),
                        "status": quest.status,
                        "pass_criteria": _short(quest.pass_criteria, 300),
                    }
                    for quest in quests
                ],
            },
            "knowledge": {
                "active_cards": sum(card.status == "active" for card in store.cards),
                "quality_issue_counts": issue_counts,
                "recent_cards": [
                    {
                        "id": card.id,
                        "title": _short(card.title, 180),
                        "concepts": list(card.concepts[:6]),
                    }
                    for card in recent_cards
                ],
            },
            "recent_thoughts": [
                {
                    "id": item.id,
                    "title": _short(item.title, 180),
                    "summary": _short(item.summary, 360),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in thoughts
            ],
            "latest_review": [
                {
                    "id": item.id,
                    "title": _short(item.title, 180),
                    "summary": _short(item.summary, 600),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in reviews
            ],
            "creative_queue": {
                "article_drafts": [
                    {"id": item.id, "title": _short(item.title, 180)}
                    for item in articles
                ],
                "video_projects": [
                    {
                        "id": project.id,
                        "title": _short(project.title, 180),
                        "status": project.status,
                        "platform": project.platform,
                    }
                    for project in video_projects
                ],
            },
            "query_matches": [
                {
                    "id": result.id,
                    "type": result.result_type,
                    "title": _short(result.title, 180),
                    "snippet": _short(result.snippet, 400),
                }
                for result in search_results
            ],
        }
        envelope = {
            "task": "personal-decision-support",
            "question": clean_question,
            "conversation_summary": _short(conversation_summary, 2_000),
            "current_state": state,
            "allowed_sources": [asdict(value) for value in sources.values()],
            "allowed_skills": [
                {"id": skill.id, "name": _short(skill.name, 120)} for skill in skills
            ],
        }
        material = json.dumps(envelope, ensure_ascii=False, indent=2)
        if len(material) > MAX_ASSISTANT_CONTEXT:
            raise ValueError("助手上下文超过本地安全上限，请缩小问题范围")
        return AssistantContextSnapshot(
            material=material,
            sources=tuple(sources.values()),
            allowed_skill_ids=tuple(skill.id for skill in skills),
        )

    def validate_outbound(self, material: str) -> tuple[set[str], set[str]]:
        """Reject forged IDs while allowing the author to redact text freely."""

        try:
            payload = json.loads(material)
        except json.JSONDecodeError as error:
            raise ValueError("外发内容必须保持为可校验的 JSON") from error
        if not isinstance(payload, dict) or payload.get("task") != "personal-decision-support":
            raise ValueError("外发内容缺少助手任务边界")
        if not _short(payload.get("question"), MAX_ASSISTANT_QUESTION):
            raise ValueError("外发内容缺少问题")
        current = self.build(str(payload["question"]), conversation_summary="")
        known_sources = {value.id for value in current.sources}
        known_skills = set(current.allowed_skill_ids)
        raw_sources = payload.get("allowed_sources", [])
        raw_skills = payload.get("allowed_skills", [])
        if not isinstance(raw_sources, list) or not isinstance(raw_skills, list):
            raise ValueError("外发内容的允许集合格式无效")
        selected_sources = {
            str(row.get("id", "")) for row in raw_sources if isinstance(row, dict)
        }
        selected_skills = {
            str(row.get("id", "")) for row in raw_skills if isinstance(row, dict)
        }
        if not selected_sources <= known_sources or not selected_skills <= known_skills:
            raise ValueError("外发内容包含未知的来源或技能 ID")
        return selected_sources, selected_skills


class AssistantRepository:
    """Persist only summaries, citations and explicit decisions."""

    def __init__(self, data_root: Path) -> None:
        self.database_path = data_root / "workspace.db"
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="assistant",
            snapshot_root=data_root / "working" / "db-migrations",
            migrations={
                1: """CREATE TABLE IF NOT EXISTS assistant_conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','archived')),
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_turn_summaries (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
                    user_intent_summary TEXT NOT NULL,
                    assistant_summary TEXT NOT NULL,
                    priority_title TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    success_criteria TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    clarifying_question TEXT NOT NULL,
                    suggestions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_decisions (
                    id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL REFERENCES assistant_turn_summaries(id) ON DELETE CASCADE,
                    action_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','discarded','failed')),
                    target_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(turn_id, action_id)
                );""",
            },
        )

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def conversations(self, *, include_archived: bool = False) -> tuple[AssistantConversation, ...]:
        where = "" if include_archived else "WHERE status='active'"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM assistant_conversations {where} ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(AssistantConversation(**dict(row)) for row in rows)

    def conversation(self, conversation_id: str) -> AssistantConversation | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_conversations WHERE id=?", (conversation_id,)
            ).fetchone()
        return AssistantConversation(**dict(row)) if row else None

    @staticmethod
    def _turn(row: sqlite3.Row) -> AssistantTurnSummary:
        return AssistantTurnSummary(
            id=row["id"],
            conversation_id=row["conversation_id"],
            user_intent_summary=row["user_intent_summary"],
            assistant_summary=row["assistant_summary"],
            priority_title=row["priority_title"],
            reason=row["reason"],
            steps=tuple(json.loads(row["steps_json"])),
            success_criteria=row["success_criteria"],
            evidence=tuple(
                AssistantEvidence(**value)
                for value in json.loads(row["evidence_json"])
            ),
            assumptions=tuple(json.loads(row["assumptions_json"])),
            clarifying_question=row["clarifying_question"],
            suggestions=tuple(
                AssistantSuggestion(**value)
                for value in json.loads(row["suggestions_json"])
            ),
            created_at=row["created_at"],
        )

    def turns(self, conversation_id: str) -> tuple[AssistantTurnSummary, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_turn_summaries WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        return tuple(self._turn(row) for row in rows)

    def turn(self, turn_id: str) -> AssistantTurnSummary | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_turn_summaries WHERE id=?", (turn_id,)
            ).fetchone()
        return self._turn(row) if row else None

    def save_turn(
        self,
        recommendation: AssistantRecommendation,
        *,
        conversation_id: str = "",
    ) -> tuple[AssistantConversation, AssistantTurnSummary]:
        stamp = _now()
        conversation = self.conversation(conversation_id) if conversation_id else None
        if conversation is not None and conversation.status != "active":
            raise ValueError("归档会话不能继续追加内容")
        if conversation is None:
            conversation_id = f"assistant-conversation-{uuid4().hex}"
            conversation = AssistantConversation(
                conversation_id,
                recommendation.user_intent_summary[:80],
                "active",
                recommendation.assistant_summary[:2_000],
                stamp,
                stamp,
            )
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO assistant_conversations VALUES(?,?,?,?,?,?)",
                    tuple(asdict(conversation).values()),
                )
        turn = AssistantTurnSummary(
            id=f"assistant-turn-{uuid4().hex}",
            conversation_id=conversation_id,
            user_intent_summary=recommendation.user_intent_summary,
            assistant_summary=recommendation.assistant_summary,
            priority_title=recommendation.priority_title,
            reason=recommendation.reason,
            steps=recommendation.steps,
            success_criteria=recommendation.success_criteria,
            evidence=recommendation.evidence,
            assumptions=recommendation.assumptions,
            clarifying_question=recommendation.clarifying_question,
            suggestions=recommendation.suggestions,
            created_at=stamp,
        )
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO assistant_turn_summaries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    turn.id,
                    turn.conversation_id,
                    turn.user_intent_summary,
                    turn.assistant_summary,
                    turn.priority_title,
                    turn.reason,
                    json.dumps(turn.steps, ensure_ascii=False),
                    turn.success_criteria,
                    json.dumps([asdict(value) for value in turn.evidence], ensure_ascii=False),
                    json.dumps(turn.assumptions, ensure_ascii=False),
                    turn.clarifying_question,
                    json.dumps([asdict(value) for value in turn.suggestions], ensure_ascii=False),
                    turn.created_at,
                ),
            )
            connection.execute(
                "UPDATE assistant_conversations SET summary=?,updated_at=? WHERE id=?",
                (turn.assistant_summary[:2_000], stamp, conversation_id),
            )
        return self.conversation(conversation_id), turn  # type: ignore[return-value]

    def set_status(self, conversation_id: str, status: str) -> None:
        if status not in ASSISTANT_CONVERSATION_STATUSES:
            raise ValueError("助手会话状态无效")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE assistant_conversations SET status=?,updated_at=? WHERE id=?",
                (status, _now(), conversation_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(conversation_id)

    def delete(self, conversation_id: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM assistant_conversations WHERE id=?", (conversation_id,)
            )
        if cursor.rowcount != 1:
            raise KeyError(conversation_id)

    def decision(self, turn_id: str, action_id: str) -> AssistantDecision | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_decisions WHERE turn_id=? AND action_id=?",
                (turn_id, action_id),
            ).fetchone()
        return AssistantDecision(**dict(row)) if row else None

    def reserve_decision(
        self, turn_id: str, suggestion: AssistantSuggestion, *, discarded: bool = False
    ) -> AssistantDecision:
        existing = self.decision(turn_id, suggestion.id)
        if existing is not None:
            return existing
        decision = AssistantDecision(
            id=f"assistant-decision-{uuid4().hex}",
            turn_id=turn_id,
            action_id=suggestion.id,
            action_type=suggestion.action_type,
            status="discarded" if discarded else "pending",
            target_id="",
            created_at=_now(),
        )
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO assistant_decisions VALUES(?,?,?,?,?,?,?)",
                    tuple(asdict(decision).values()),
                )
        except sqlite3.IntegrityError:
            return self.decision(turn_id, suggestion.id)  # type: ignore[return-value]
        return decision

    def finish_decision(
        self, turn_id: str, action_id: str, *, status: str, target_id: str = ""
    ) -> AssistantDecision:
        if status not in {"confirmed", "failed"}:
            raise ValueError("助手决策结果无效")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE assistant_decisions SET status=?,target_id=? WHERE turn_id=? AND action_id=? AND status='pending'",
                (status, target_id[:200], turn_id, action_id),
            )
        if cursor.rowcount != 1:
            existing = self.decision(turn_id, action_id)
            if existing is None:
                raise KeyError(action_id)
            return existing
        return self.decision(turn_id, action_id)  # type: ignore[return-value]

    def decisions(self, turn_id: str) -> tuple[AssistantDecision, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_decisions WHERE turn_id=? ORDER BY created_at",
                (turn_id,),
            ).fetchall()
        return tuple(AssistantDecision(**dict(row)) for row in rows)


def outbound_allowed_sets(material: str) -> tuple[set[str], set[str]]:
    """Read selected IDs from an already server-validated assistant envelope."""

    payload = json.loads(material)
    return (
        {
            str(row["id"])
            for row in payload.get("allowed_sources", [])
            if isinstance(row, dict) and row.get("id")
        },
        {
            str(row["id"])
            for row in payload.get("allowed_skills", [])
            if isinstance(row, dict) and row.get("id")
        },
    )


def enrich_assistant_recommendation(
    recommendation: AssistantRecommendation,
    sources: tuple[AssistantSource, ...],
) -> AssistantRecommendation:
    """Attach server-reviewed labels and local URLs to persisted citations."""

    catalog = {value.id: value for value in sources}
    if any(value.source_id not in catalog for value in recommendation.evidence):
        raise ValueError("助手引用的来源在保存前已经发生变化，请重新预览")
    return replace(
        recommendation,
        evidence=tuple(
            replace(
                value,
                title=catalog[value.source_id].title,
                url=catalog[value.source_id].url,
            )
            for value in recommendation.evidence
        ),
    )
