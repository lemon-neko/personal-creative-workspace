"""Public compatibility exports for the Career domain."""

from app.career.domain.job import (
    JOB_INLINE_FIELDS,
    JOB_STATUSES,
    JOB_STATUS_LABELS,
    JobOpportunity,
    JobResumeSubmission,
    JobSkillGap,
    JobStageEvent,
)
from app.career.domain.learning import (
    CAMPAIGN_STATUSES,
    LEARNING_PATH_STATUSES,
    LEARNING_STAGE_STATUSES,
    LEARNING_STATUSES,
    QUEST_STATUSES,
    REFERENCE_STATUSES,
    CapabilityDomain,
    JobCapability,
    LearningCampaign,
    LearningPath,
    LearningReference,
    LearningStage,
    LearningStageReference,
    LearningTask,
    Quest,
    QuestEvidence,
    Skill,
)
from app.career.domain.policies import (
    LLMDisclosure,
    SHANGHAI,
)
from app.career.domain.profile import (
    ALLOWED_EXTENSIONS,
    DOCUMENT_KINDS,
    MAX_DOCUMENT_BYTES,
    MAX_DOCX_EXPANDED_BYTES,
    PROJECT_STATUSES,
    CareerProfile,
    CareerProject,
    PrivateDocument,
)
from app.career.domain.resume import (
    RESUME_STATUSES,
    ResumeAsset,
    ResumeVersion,
    StructuredResume,
)
from app.career.infrastructure.documents import (
    validate_document,
)
from app.career.infrastructure.sqlite.migrations import (
    SCHEMA_VERSION,
    apply_migrations,
)
from app.career.infrastructure.sqlite.schema import (
    SCHEMA,
    CAMPAIGN_SCHEMA,
    CAREER_RADAR_SCHEMA,
    LEARNING_PATH_SCHEMA,
    RESUME_STUDIO_SCHEMA,
    RESUME_PHOTO_SCHEMA,
)
from app.career.repository import CareerRepository
from app.database import WORKSPACE_REGISTRY
from app.resume_assets import ResumeImage, validate_resume_image
from app.resume_studio import (
    RESUME_TEMPLATE_KEYS,
    deserialize_structured_resume,
    serialize_structured_resume,
    source_fingerprint,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "WORKSPACE_REGISTRY",
    "RESUME_TEMPLATE_KEYS",
    "ResumeImage",
    "deserialize_structured_resume",
    "serialize_structured_resume",
    "source_fingerprint",
    "validate_resume_image",
    "CAMPAIGN_SCHEMA",
    "CAMPAIGN_STATUSES",
    "CAREER_RADAR_SCHEMA",
    "CapabilityDomain",
    "CareerProfile",
    "CareerProject",
    "CareerRepository",
    "DOCUMENT_KINDS",
    "JOB_INLINE_FIELDS",
    "JOB_STATUSES",
    "JOB_STATUS_LABELS",
    "JobCapability",
    "JobOpportunity",
    "JobResumeSubmission",
    "JobSkillGap",
    "JobStageEvent",
    "LEARNING_PATH_SCHEMA",
    "LEARNING_PATH_STATUSES",
    "LEARNING_STAGE_STATUSES",
    "LEARNING_STATUSES",
    "LLMDisclosure",
    "LearningCampaign",
    "LearningPath",
    "LearningReference",
    "LearningStage",
    "LearningStageReference",
    "LearningTask",
    "MAX_DOCUMENT_BYTES",
    "MAX_DOCX_EXPANDED_BYTES",
    "PROJECT_STATUSES",
    "PrivateDocument",
    "QUEST_STATUSES",
    "Quest",
    "QuestEvidence",
    "REFERENCE_STATUSES",
    "RESUME_PHOTO_SCHEMA",
    "RESUME_STATUSES",
    "RESUME_STUDIO_SCHEMA",
    "ResumeAsset",
    "ResumeVersion",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SHANGHAI",
    "Skill",
    "StructuredResume",
    "apply_migrations",
    "validate_document",
]
