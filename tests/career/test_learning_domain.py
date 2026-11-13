from dataclasses import replace

import pytest

from app.career.domain.learning import Quest, validate_quest_start, validate_skill


def test_learning_requires_prerequisite_and_valid_skill_levels():
    quest = Quest(
        id="quest",
        campaign_id="fixture",
        code="two",
        title="Second",
        description="",
        stage_order=2,
        prerequisite_id="first",
        pass_criteria="pytest",
        xp=50,
        status="available",
        started_at=None,
        completed_at=None,
    )
    with pytest.raises(ValueError, match="前置关卡"):
        validate_quest_start(quest, replace(quest, id="first", status="active"))
    validate_quest_start(quest, replace(quest, id="first", status="cleared"))
    validate_skill("Example", 0, 5)
    with pytest.raises(ValueError, match="等级无效"):
        validate_skill("Example", 0, 6)
