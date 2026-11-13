import sqlite3
from contextlib import closing
from pathlib import Path

from app.career.infrastructure.sqlite.schema import (
    CAMPAIGN_SCHEMA,
    CAREER_RADAR_SCHEMA,
    LEARNING_PATH_SCHEMA,
    RESUME_PHOTO_SCHEMA,
    RESUME_STUDIO_SCHEMA,
    SCHEMA,
)
from app.database import WORKSPACE_REGISTRY, apply_migrations


SCHEMA_VERSION = 8


def migrate_career(database_path: Path, data_root: Path) -> None:
    legacy_version = 0
    if database_path.exists():
        with closing(sqlite3.connect(database_path)) as connection:
            legacy_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
    apply_migrations(
        database_path,
        registry=WORKSPACE_REGISTRY,
        subsystem="career",
        snapshot_root=data_root / "working" / "db-migrations",
        legacy_version=legacy_version,
        migrations={
            1: f"{SCHEMA}\nPRAGMA user_version = 1;",
            2: f"{CAMPAIGN_SCHEMA}\nPRAGMA user_version = 2;",
            3: f"{CAREER_RADAR_SCHEMA}\nPRAGMA user_version = 3;",
            4: RESUME_STUDIO_SCHEMA,
            5: RESUME_PHOTO_SCHEMA,
            6: LEARNING_PATH_SCHEMA,
            7: """ALTER TABLE jobs ADD COLUMN tier TEXT NOT NULL DEFAULT 'B';
                ALTER TABLE jobs ADD COLUMN applied_on TEXT NOT NULL DEFAULT '';
                ALTER TABLE jobs ADD COLUMN next_action TEXT NOT NULL DEFAULT '';
                ALTER TABLE jobs ADD COLUMN next_action_on TEXT NOT NULL DEFAULT '';
                PRAGMA user_version = 7;""",
            8: """CREATE TABLE job_resume_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    resume_id TEXT REFERENCES resumes(id) ON DELETE SET NULL,
                    revision INTEGER NOT NULL, title TEXT NOT NULL,
                    target_role TEXT NOT NULL, structured_data TEXT NOT NULL,
                    template_key TEXT NOT NULL,
                    photo_asset_id TEXT REFERENCES resume_assets(id) ON DELETE SET NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX ix_job_resume_submissions_job ON job_resume_submissions(job_id,id);
                PRAGMA user_version = 8;""",
        },
    )
