from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceProject:
    id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceTask:
    id: str
    project_id: str
    title: str
    objective: str
    task_type: str
    assigned_role: str
    status: str
    priority: int
    next_action: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AgentRun:
    id: str
    task_id: str
    role_key: str
    status: str
    current_step: int
    error_code: str
    created_at: str
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class AgentStep:
    id: str
    run_id: str
    position: int
    step_key: str
    title: str
    status: str
    output_artifact_id: str
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    run_id: str
    step_id: str
    tool_key: str
    status: str
    input_summary: str
    result_summary: str
    created_at: str


@dataclass(frozen=True)
class Artifact:
    id: str
    task_id: str
    run_id: str
    artifact_type: str
    title: str
    status: str
    storage_key: str
    content_hash: str
    summary: str
    created_at: str
    accepted_at: str
