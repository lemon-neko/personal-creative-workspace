from dataclasses import dataclass

from app.resume_studio import StructuredResume as StructuredResume


RESUME_STATUSES = {"draft", "active", "archived"}


@dataclass(frozen=True)
class ResumeVersion:
    id: str
    title: str
    target_role: str
    document_id: str | None
    project_ids: tuple[str, ...]
    status: str
    notes: str
    created_at: str
    updated_at: str
    resume_kind: str = "legacy"
    parent_id: str | None = None
    job_id: str | None = None
    structured_data: str = ""
    source_fingerprint: str = ""
    revision: int = 0
    template_key: str = "ats_single"
    is_primary: int = 0
    photo_asset_id: str | None = None

    @property
    def is_structured(self) -> bool:
        return self.resume_kind in {"master", "tailored"} and bool(self.structured_data)


@dataclass(frozen=True)
class ResumeAsset:
    id: str
    source_document_id: str | None
    stored_name: str
    media_type: str
    size: int
    sha256: str
    width: int
    height: int
    created_at: str


def referenced_project_ids(structured: StructuredResume) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(row.get("project_id", ""))
            for row in structured.projects
            if str(row.get("project_id", ""))
        )
    )
