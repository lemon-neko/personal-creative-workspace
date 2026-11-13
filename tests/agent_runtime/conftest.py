import pytest

from app.agent_core import DEFAULT_PROJECT_ID, AgentCoreRepository
from app.focus import FocusRepository


@pytest.fixture
def focus(tmp_path):
    return FocusRepository(tmp_path)


@pytest.fixture
def runtime(tmp_path, focus):
    return AgentCoreRepository(tmp_path)


@pytest.fixture
def planned(runtime):
    task = runtime.create_task(
        project_id=DEFAULT_PROJECT_ID, title="虚构任务", objective="核对测试资料", task_type="research",
    )
    return task, runtime.run_service.plan_task(task.id)
