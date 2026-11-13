from dataclasses import replace

import pytest

from app.agent_runtime.domain.policies import (
    require_decision_answer,
    require_executable,
    require_step_transition,
    should_cancel,
    task_material,
)


def test_role_material_and_transition_rules(planned):
    _, run = planned
    assert task_material(" 示例   任务 ", "  示例目标  ", "creation", 1) == ("示例 任务", "示例目标", "creator")
    with pytest.raises(ValueError, match="优先级"):
        task_material("任务", "目标", "research", 0)
    require_executable(run)
    assert should_cancel(run)
    with pytest.raises(ValueError, match="不能执行"):
        require_executable(replace(run, status="completed"))
    with pytest.raises(ValueError, match="正在执行"):
        should_cancel(replace(run, status="running"))
    with pytest.raises(ValueError, match="步骤状态"):
        require_step_transition("pending", "completed")
    with pytest.raises(ValueError, match="请选择"):
        require_decision_answer("planned", "", ["甲", "乙"], "丙")
