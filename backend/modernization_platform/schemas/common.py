"""Common enums and uncertainty semantics shared by artifact contracts."""

from enum import StrEnum

from pydantic import Field, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import ContractModel, ShortText


class ArtifactType(StrEnum):
    """The nine artifact handoff types defined by the platform TDD."""

    REPO_INVENTORY = "RepoInventory"
    LEGACY_MODEL = "LegacyModel"
    TARGET_BLUEPRINT = "TargetBlueprint"
    FEASIBILITY_REPORT = "FeasibilityReport"
    CONVERSION_PLAN = "ConversionPlan"
    CHARACTERIZATION_SUITE = "CharacterizationSuite"
    SCHEMA_PLAN = "SchemaPlan"
    EQUIVALENCE_REPORT = "EquivalenceReport"
    JOB_REPORT = "JobReport"


class AnalysisStatus(StrEnum):
    """Completeness of an analysis; this is never an approval decision."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"


class ReviewAssessment(ContractModel):
    """Explicit uncertainty and human-review signal embedded in every agent artifact.

    ``confidence`` is a producer-reported value in the closed interval [0, 1]. It is
    not a calibrated probability and never grants approval or bypasses a gate.
    """

    analysis_status: AnalysisStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    needs_human: bool
    human_review_reason: ShortText | None = None
    unresolved_questions: list[ShortText] = Field(default_factory=list, max_length=50)
    assumptions: list[ShortText] = Field(default_factory=list, max_length=100)
    blockers: list[ShortText] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    @log_errors
    def validate_review_state(self) -> "ReviewAssessment":
        """Require an actionable reason for human review and incomplete analysis."""
        if self.needs_human and self.human_review_reason is None:
            raise ValueError("human_review_reason is required when needs_human is true")
        if not self.needs_human and self.human_review_reason is not None:
            raise ValueError("human_review_reason requires needs_human to be true")
        if self.analysis_status is AnalysisStatus.INCOMPLETE and not self.needs_human:
            raise ValueError("incomplete analysis must request human review")
        return self
