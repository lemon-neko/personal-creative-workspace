from dataclasses import dataclass


DOCUMENT_KINDS = {"resume", "certificate", "project", "job", "other"}
PROJECT_STATUSES = {"draft", "active", "archived"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class CareerProfile:
    target_roles: str = ""
    contact: str = ""
    education: str = ""
    experience: str = ""
    certifications: str = ""
    skills: str = ""
    facts: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class PrivateDocument:
    id: str
    kind: str
    original_name: str
    stored_name: str
    media_type: str
    size: int
    sha256: str
    extracted_text: str
    created_at: str


@dataclass(frozen=True)
class CareerProject:
    id: str
    name: str
    role: str
    timeframe: str
    summary: str
    technologies: str
    challenge: str
    actions: str
    outcome: str
    evidence: str
    status: str
    created_at: str
    updated_at: str


def normalize_profile_fields(fields: dict[str, str]) -> dict[str, str]:
    allowed = (
        "target_roles",
        "contact",
        "education",
        "experience",
        "certifications",
        "skills",
        "facts",
    )
    return {key: str(fields.get(key, "")).strip()[:20_000] for key in allowed}
