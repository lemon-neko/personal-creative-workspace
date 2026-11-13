from app.career.application.ports import UnitOfWork
from app.career.domain.learning import (
    LearningReference,
    LearningStage,
    LearningTask,
    Quest,
    QuestEvidence,
    Skill,
    validate_quest_start,
)
from app.career.domain.policies import new_id, now


class LearningService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def seed_career_radar(self) -> None:
        with self.uow(write=True) as stores:
            stores.learning.seed_career_radar()

    def start_quest(self, quest_id: str) -> Quest:
        with self.uow(write=True) as stores:
            quest = stores.learning.quest(quest_id)
            if quest is None:
                raise KeyError(quest_id)
            prerequisite = (
                stores.learning.quest(quest.prerequisite_id)
                if quest.prerequisite_id
                else None
            )
            validate_quest_start(quest, prerequisite)
            stores.learning.mark_quest_started(quest_id)
            return stores.learning.quest(quest_id)  # type: ignore[return-value]

    def add_quest_evidence(
        self,
        quest_id: str,
        *,
        commit_sha: str,
        test_result: str,
        reflection: str = "",
        evidence_url: str = "",
    ) -> QuestEvidence:
        with self.uow(write=True) as stores:
            quest = stores.learning.quest(quest_id)
            if quest is None:
                raise KeyError(quest_id)
            if quest.status != "active":
                raise ValueError("请先开始关卡再提交证据")
            if not commit_sha.strip() or not test_result.strip():
                raise ValueError("Commit SHA 和测试结果不能为空")
            evidence = QuestEvidence(
                new_id("evidence"),
                quest_id,
                commit_sha.strip()[:120],
                test_result.strip()[:20_000],
                reflection.strip()[:20_000],
                evidence_url.strip()[:1000],
                now(),
            )
            stores.learning.insert_quest_evidence(evidence)
            return evidence

    def clear_quest(self, quest_id: str) -> Quest:
        with self.uow(write=True) as stores:
            quest = stores.learning.quest(quest_id)
            if quest is None:
                raise KeyError(quest_id)
            if quest.status != "active" or not stores.learning.quest_evidence(quest_id):
                raise ValueError("关卡进行中且已有验收证据时才能确认通关")
            stores.learning.mark_quest_cleared(quest)
            return stores.learning.quest(quest_id)  # type: ignore[return-value]

    def find_or_add_skill(self, *, name: str, category: str = "") -> Skill:
        with self.uow(write=True) as stores:
            return stores.learning.find_or_add_skill(name=name, category=category)

    def add_skill(
        self,
        *,
        name: str,
        category: str = "",
        current_level: int = 0,
        target_level: int = 3,
        notes: str = "",
    ) -> Skill:
        with self.uow(write=True) as stores:
            return stores.learning.add_skill(
                name=name,
                category=category,
                current_level=current_level,
                target_level=target_level,
                notes=notes,
            )

    def update_learning_stage(
        self,
        stage_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningStage:
        with self.uow(write=True) as stores:
            return stores.learning.update_learning_stage(
                stage_id,
                status=status,
                commit_sha=commit_sha,
                test_result=test_result,
                reflection=reflection,
            )

    def update_learning_stage_status(
        self, stage_id: str, *, status: str
    ) -> LearningStage:
        with self.uow(write=True) as stores:
            return stores.learning.update_learning_stage_status(stage_id, status=status)

    def update_learning_reference(
        self,
        reference_id: str,
        *,
        status: str,
        commit_sha: str = "",
        test_result: str = "",
        reflection: str = "",
    ) -> LearningReference:
        with self.uow(write=True) as stores:
            return stores.learning.update_learning_reference(
                reference_id,
                status=status,
                commit_sha=commit_sha,
                test_result=test_result,
                reflection=reflection,
            )

    def update_learning_task_status(self, task_id: str, status: str) -> None:
        with self.uow(write=True) as stores:
            return stores.learning.update_learning_task_status(task_id, status)

    def add_learning_task(
        self,
        *,
        skill_id: str,
        title: str,
        status: str = "backlog",
        priority: int = 3,
        linked_content_id: str = "",
        linked_project_id: str = "",
        notes: str = "",
    ) -> LearningTask:
        with self.uow(write=True) as stores:
            return stores.learning.add_learning_task(
                skill_id=skill_id,
                title=title,
                status=status,
                priority=priority,
                linked_content_id=linked_content_id,
                linked_project_id=linked_project_id,
                notes=notes,
            )
