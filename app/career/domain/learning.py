from dataclasses import dataclass


LEARNING_STATUSES = {"backlog", "active", "done", "paused"}
QUEST_STATUSES = {"locked", "available", "active", "cleared"}
CAMPAIGN_STATUSES = {"planned", "active", "completed", "archived"}
REFERENCE_STATUSES = {"backlog", "reading", "building", "verified", "paused"}
LEARNING_PATH_STATUSES = {"active", "completed", "archived"}
LEARNING_STAGE_STATUSES = REFERENCE_STATUSES


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    current_level: int
    target_level: int
    notes: str


@dataclass(frozen=True)
class LearningTask:
    id: str
    skill_id: str
    title: str
    status: str
    priority: int
    linked_content_id: str
    linked_project_id: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CapabilityDomain:
    id: str
    title: str
    priority: str
    summary: str
    sort_order: int


@dataclass(frozen=True)
class JobCapability:
    job_id: str
    capability_id: str
    requirement_summary: str
    importance: int


@dataclass(frozen=True)
class LearningReference:
    id: str
    name: str
    repo_url: str
    snapshot_date: str
    week: int
    study_focus: str
    target_modules: str
    deliverable: str
    acceptance_command: str
    status: str
    commit_sha: str
    test_result: str
    reflection: str
    is_optional: int
    created_at: str
    updated_at: str
    archived_at: str


@dataclass(frozen=True)
class LearningPath:
    id: str
    title: str
    summary: str
    status: str
    source_title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LearningStage:
    id: str
    path_id: str
    stage_order: int
    title: str
    objective: str
    focus: str
    deliverable: str
    acceptance_command: str
    status: str
    commit_sha: str
    test_result: str
    reflection: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LearningStageReference:
    id: str
    stage_id: str
    name: str
    repo_url: str
    role: str
    target_modules: str
    sort_order: int


@dataclass(frozen=True)
class LearningCampaign:
    id: str
    name: str
    description: str
    repository_path: str
    status: str
    total_xp: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Quest:
    id: str
    campaign_id: str
    code: str
    title: str
    description: str
    stage_order: int
    prerequisite_id: str | None
    pass_criteria: str
    xp: int
    status: str
    started_at: str | None
    completed_at: str | None
    learning_task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestEvidence:
    id: str
    quest_id: str
    commit_sha: str
    test_result: str
    reflection: str
    evidence_url: str
    created_at: str


def validate_quest_start(quest: Quest, prerequisite: Quest | None) -> None:
    if quest.status != "available":
        raise ValueError("只有已解锁关卡可以开始")
    if quest.prerequisite_id and (
        prerequisite is None or prerequisite.status != "cleared"
    ):
        raise ValueError("请先通关前置关卡")


def validate_skill(name: str, current_level: int, target_level: int) -> None:
    if (
        not name.strip()
        or current_level not in range(6)
        or target_level not in range(6)
    ):
        raise ValueError("技能名称或等级无效")
