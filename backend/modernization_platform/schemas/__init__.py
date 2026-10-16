"""Public Pydantic contracts for API transport and typed artifact handoffs."""

from modernization_platform.schemas.agent_artifacts import (
    ChangeSet,
    CharacterizationSuite,
    ConversionPlan,
    EquivalenceReport,
    FeasibilityReport,
    JobReport,
    LegacyModel,
    RepoInventory,
    ReviewReport,
    SchemaPlan,
    TargetBlueprint,
)
from modernization_platform.schemas.artifacts import (
    ArtifactDeleteResponse,
    ArtifactDetailResponse,
    ArtifactIntegrityVerificationResponse,
    ArtifactLineageResponse,
    ArtifactListResponse,
    ArtifactResponse,
    ArtifactValidationRequest,
)
from modernization_platform.schemas.audit import (
    AuditEventListResponse,
    AuditEventResponse,
)
from modernization_platform.schemas.common import ArtifactType, ReviewAssessment
from modernization_platform.schemas.gates import (
    GateDecisionRequest,
    GateDecisionResponse,
    GateDetailResponse,
    GateListResponse,
    WaiverRequest,
)
from modernization_platform.schemas.jobs import (
    JobBudget,
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
    JobListResponse,
    JobStatusResponse,
    JobSummaryResponse,
    PaginationMetadata,
    PaginationRequest,
)
from modernization_platform.schemas.metadata import ArtifactMetadata
from modernization_platform.schemas.references import (
    ArtifactReference,
    CodeReference,
    EvidenceReference,
)
from modernization_platform.schemas.source import (
    ModuleBranchRequest,
    ModuleBranchResponse,
    RepositoryMetadataResponse,
    SourceIngestRequest,
    SourceProvenanceResponse,
)
from modernization_platform.schemas.validation import parse_artifact

__all__ = [
    "ArtifactDeleteResponse",
    "ArtifactDetailResponse",
    "ArtifactIntegrityVerificationResponse",
    "ArtifactLineageResponse",
    "ArtifactListResponse",
    "ArtifactMetadata",
    "ArtifactReference",
    "ArtifactResponse",
    "ArtifactType",
    "ArtifactValidationRequest",
    "AuditEventListResponse",
    "AuditEventResponse",
    "ChangeSet",
    "CharacterizationSuite",
    "CodeReference",
    "ConversionPlan",
    "EquivalenceReport",
    "EvidenceReference",
    "FeasibilityReport",
    "GateDecisionRequest",
    "GateDecisionResponse",
    "GateDetailResponse",
    "GateListResponse",
    "JobBudget",
    "JobCreateRequest",
    "JobCreateResponse",
    "JobDetailResponse",
    "JobListResponse",
    "JobReport",
    "JobStatusResponse",
    "JobSummaryResponse",
    "LegacyModel",
    "ModuleBranchRequest",
    "ModuleBranchResponse",
    "PaginationMetadata",
    "PaginationRequest",
    "RepoInventory",
    "RepositoryMetadataResponse",
    "ReviewAssessment",
    "ReviewReport",
    "SchemaPlan",
    "SourceIngestRequest",
    "SourceProvenanceResponse",
    "TargetBlueprint",
    "WaiverRequest",
    "parse_artifact",
]
