"""Public Pydantic contracts for API transport and typed artifact handoffs."""

from modernization_platform.schemas.agent_artifacts import (
    CharacterizationSuite,
    ConversionPlan,
    EquivalenceReport,
    FeasibilityReport,
    JobReport,
    LegacyModel,
    RepoInventory,
    SchemaPlan,
    TargetBlueprint,
)
from modernization_platform.schemas.common import ArtifactType, ReviewAssessment
from modernization_platform.schemas.metadata import ArtifactMetadata
from modernization_platform.schemas.references import (
    ArtifactReference,
    CodeReference,
    EvidenceReference,
)
from modernization_platform.schemas.validation import parse_artifact

__all__ = [
    "ArtifactMetadata",
    "ArtifactReference",
    "ArtifactType",
    "CharacterizationSuite",
    "CodeReference",
    "ConversionPlan",
    "EquivalenceReport",
    "EvidenceReference",
    "FeasibilityReport",
    "JobReport",
    "LegacyModel",
    "RepoInventory",
    "ReviewAssessment",
    "SchemaPlan",
    "TargetBlueprint",
    "parse_artifact",
]
