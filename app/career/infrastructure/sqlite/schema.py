SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS profile (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    target_roles TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '', experience TEXT NOT NULL DEFAULT '',
    certifications TEXT NOT NULL DEFAULT '', skills TEXT NOT NULL DEFAULT '',
    facts TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE, media_type TEXT NOT NULL, size INTEGER NOT NULL,
    sha256 TEXT NOT NULL, extracted_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT '',
    timeframe TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
    technologies TEXT NOT NULL DEFAULT '', challenge TEXT NOT NULL DEFAULT '',
    actions TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, target_role TEXT NOT NULL DEFAULT '',
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    project_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
    jd_text TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category TEXT NOT NULL DEFAULT '', current_level INTEGER NOT NULL DEFAULT 0,
    target_level INTEGER NOT NULL DEFAULT 3, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS job_skill_gaps (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    importance INTEGER NOT NULL DEFAULT 3, evidence TEXT NOT NULL DEFAULT '',
    gap_note TEXT NOT NULL DEFAULT '', PRIMARY KEY(job_id, skill_id)
);
CREATE TABLE IF NOT EXISTS learning_tasks (
    id TEXT PRIMARY KEY, skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    title TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 3,
    linked_content_id TEXT NOT NULL DEFAULT '', linked_project_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


CAMPAIGN_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_campaigns (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    repository_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
    total_xp INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quests (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES learning_campaigns(id) ON DELETE CASCADE,
    code TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    stage_order INTEGER NOT NULL, prerequisite_id TEXT REFERENCES quests(id),
    pass_criteria TEXT NOT NULL, xp INTEGER NOT NULL, status TEXT NOT NULL,
    started_at TEXT, completed_at TEXT,
    UNIQUE(campaign_id, code), UNIQUE(campaign_id, stage_order)
);
CREATE TABLE IF NOT EXISTS quest_learning_tasks (
    quest_id TEXT NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    learning_task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY(quest_id, learning_task_id)
);
CREATE TABLE IF NOT EXISTS quest_evidence (
    id TEXT PRIMARY KEY, quest_id TEXT NOT NULL REFERENCES quests(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL, test_result TEXT NOT NULL,
    reflection TEXT NOT NULL DEFAULT '', evidence_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


CAREER_RADAR_SCHEMA = """
ALTER TABLE jobs ADD COLUMN captured_at TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN capability_summary TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS career_radar_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    baseline_version TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capability_domains (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, priority TEXT NOT NULL,
    summary TEXT NOT NULL, sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS job_capabilities (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    requirement_summary TEXT NOT NULL, importance INTEGER NOT NULL,
    PRIMARY KEY(job_id, capability_id)
);
CREATE TABLE IF NOT EXISTS capability_skills (
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY(capability_id, skill_id)
);
CREATE TABLE IF NOT EXISTS learning_references (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, repo_url TEXT NOT NULL,
    snapshot_date TEXT NOT NULL, week INTEGER NOT NULL,
    study_focus TEXT NOT NULL, target_modules TEXT NOT NULL,
    deliverable TEXT NOT NULL, acceptance_command TEXT NOT NULL,
    status TEXT NOT NULL, commit_sha TEXT NOT NULL DEFAULT '',
    test_result TEXT NOT NULL DEFAULT '', reflection TEXT NOT NULL DEFAULT '',
    is_optional INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_reference_capabilities (
    reference_id TEXT NOT NULL REFERENCES learning_references(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    PRIMARY KEY(reference_id, capability_id)
);
CREATE TABLE IF NOT EXISTS learning_reference_tasks (
    reference_id TEXT NOT NULL REFERENCES learning_references(id) ON DELETE CASCADE,
    learning_task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
    PRIMARY KEY(reference_id, learning_task_id)
);
"""


LEARNING_PATH_SCHEMA = """
ALTER TABLE learning_references ADD COLUMN archived_at TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS learning_paths (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','completed','archived')),
    source_title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_stages (
    id TEXT PRIMARY KEY,
    path_id TEXT NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    stage_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    focus TEXT NOT NULL,
    deliverable TEXT NOT NULL,
    acceptance_command TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('backlog','reading','building','verified','paused')),
    commit_sha TEXT NOT NULL DEFAULT '',
    test_result TEXT NOT NULL DEFAULT '',
    reflection TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(path_id, stage_order)
);
CREATE TABLE IF NOT EXISTS learning_stage_references (
    id TEXT PRIMARY KEY,
    stage_id TEXT NOT NULL REFERENCES learning_stages(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    role TEXT NOT NULL,
    target_modules TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    UNIQUE(stage_id, repo_url)
);
CREATE TABLE IF NOT EXISTS learning_stage_capabilities (
    stage_id TEXT NOT NULL REFERENCES learning_stages(id) ON DELETE CASCADE,
    capability_id TEXT NOT NULL REFERENCES capability_domains(id) ON DELETE CASCADE,
    PRIMARY KEY(stage_id, capability_id)
);
CREATE INDEX IF NOT EXISTS ix_learning_stages_path_order
    ON learning_stages(path_id, stage_order);
PRAGMA user_version = 6;
"""


RESUME_STUDIO_SCHEMA = """
ALTER TABLE resumes ADD COLUMN resume_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE resumes ADD COLUMN parent_id TEXT REFERENCES resumes(id) ON DELETE SET NULL;
ALTER TABLE resumes ADD COLUMN job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE resumes ADD COLUMN structured_data TEXT NOT NULL DEFAULT '';
ALTER TABLE resumes ADD COLUMN source_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE resumes ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE resumes ADD COLUMN template_key TEXT NOT NULL DEFAULT 'ats_single';
ALTER TABLE resumes ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_resumes_primary
    ON resumes(is_primary) WHERE is_primary = 1;
PRAGMA user_version = 4;
"""


RESUME_PHOTO_SCHEMA = """
CREATE TABLE IF NOT EXISTS resume_assets (
    id TEXT PRIMARY KEY,
    source_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    stored_name TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_document_id, sha256)
);
ALTER TABLE resumes ADD COLUMN photo_asset_id TEXT
    REFERENCES resume_assets(id) ON DELETE SET NULL;
PRAGMA user_version = 5;
"""
