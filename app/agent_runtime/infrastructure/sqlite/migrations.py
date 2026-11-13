"""Existing agent_core migrations in the shared workspace registry."""
MIGRATIONS = {
                1: """CREATE TABLE IF NOT EXISTS workspace_projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','paused','archived')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '' REFERENCES workspace_projects(id) ON DELETE RESTRICT,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    task_type TEXT NOT NULL CHECK(task_type IN ('learning','research','creation','build')),
                    assigned_role TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft','planned','running','reviewing','completed','failed','cancelled')),
                    priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5),
                    next_action TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_dependencies (
                    task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE CASCADE,
                    depends_on_task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE RESTRICT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, depends_on_task_id),
                    CHECK(task_id <> depends_on_task_id)
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE CASCADE,
                    role_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('planned','running','reviewing','completed','failed','cancelled')),
                    current_step INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES workspace_tasks(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('review','accepted','rejected')),
                    storage_key TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    accepted_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS agent_steps (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    step_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','cancelled')),
                    output_artifact_id TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(run_id, position)
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL REFERENCES agent_steps(id) ON DELETE CASCADE,
                    tool_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_summary TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workspace_tasks_project ON workspace_tasks(project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_task ON agent_runs(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_steps(run_id, position);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id, created_at);""",
                2: """CREATE TABLE focus_action_tasks (
                    action_id TEXT PRIMARY KEY REFERENCES focus_actions(id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL UNIQUE REFERENCES workspace_tasks(id) ON DELETE CASCADE
                );""",
                3: """CREATE TABLE daily_event_tasks (
                    event_id TEXT PRIMARY KEY REFERENCES daily_events(id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL UNIQUE REFERENCES workspace_tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE agent_run_decisions (
                    run_id TEXT PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
                    question TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    answer TEXT NOT NULL DEFAULT ''
                );""",
            }
