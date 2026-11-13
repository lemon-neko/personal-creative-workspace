from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.career.infrastructure.sqlite.repositories.documents import DocumentRepository
from app.career.infrastructure.sqlite.repositories.jobs import JobRepository
from app.career.infrastructure.sqlite.repositories.learning import LearningRepository
from app.career.infrastructure.sqlite.repositories.profile import ProfileRepository
from app.career.infrastructure.sqlite.repositories.projects import ProjectRepository
from app.career.infrastructure.sqlite.repositories.resumes import ResumeRepository
from app.database import connect_database


@dataclass(frozen=True)
class CareerRepositories:
    profile: ProfileRepository
    documents: DocumentRepository
    projects: ProjectRepository
    resumes: ResumeRepository
    jobs: JobRepository
    learning: LearningRepository


class SQLiteUnitOfWork:
    def __init__(
        self, database_path: Path, documents_root: Path, resume_assets_root: Path
    ):
        self.database_path = database_path
        self.documents_root = documents_root
        self.resume_assets_root = resume_assets_root

    @contextmanager
    def __call__(self, *, write: bool = False) -> Iterator[CareerRepositories]:
        with closing(connect_database(self.database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield CareerRepositories(
                profile=ProfileRepository(connection),
                documents=DocumentRepository(connection, self.documents_root),
                projects=ProjectRepository(connection),
                resumes=ResumeRepository(connection, self.resume_assets_root),
                jobs=JobRepository(connection),
                learning=LearningRepository(connection),
            )
