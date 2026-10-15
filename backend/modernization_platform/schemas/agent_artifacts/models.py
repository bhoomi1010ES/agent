"""Version 1.0.0 contracts for the nine TDD-defined agent artifacts."""

import uuid
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.base import (
    ContractModel,
    Identifier,
    LongText,
    Sha256Digest,
    ShortText,
)
from modernization_platform.schemas.common import ArtifactType, ReviewAssessment
from modernization_platform.schemas.references import (
    ArtifactReference,
    CodeReference,
    EvidenceReference,
    validate_repository_path,
)

CURRENT_ARTIFACT_SCHEMA_VERSION: Final = "1.0.0"


class AgentArtifact(ContractModel):
    """Fields shared by every validated agent-to-agent artifact."""

    artifact_type: ArtifactType
    schema_version: Literal["1.0.0"] = CURRENT_ARTIFACT_SCHEMA_VERSION
    assessment: ReviewAssessment
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=500)


class FileInventoryEntry(ContractModel):
    """Metadata for a discovered file; repository contents are intentionally excluded."""

    relative_path: str
    language: Identifier | None = None
    size_bytes: int = Field(ge=0, le=1_000_000_000)
    content_hash: Sha256Digest | None = None

    @field_validator("relative_path")
    @classmethod
    @log_errors
    def validate_path(cls, value: str) -> str:
        return validate_repository_path(value)


class TechnologyObservation(ContractModel):
    """Observed language or framework and the evidence supporting that observation."""

    name: Identifier
    version: Identifier | None = None
    evidence: list[CodeReference] = Field(default_factory=list, max_length=50)


class RepoInventory(AgentArtifact):
    """Repository structure and technology observations produced by Intake."""

    artifact_type: Literal[ArtifactType.REPO_INVENTORY] = ArtifactType.REPO_INVENTORY
    repository_id: Identifier
    revision: Identifier
    files: list[FileInventoryEntry] = Field(min_length=1, max_length=20_000)
    languages: list[TechnologyObservation] = Field(default_factory=list, max_length=100)
    frameworks: list[TechnologyObservation] = Field(default_factory=list, max_length=100)
    build_systems: list[Identifier] = Field(default_factory=list, max_length=50)
    entry_points: list[CodeReference] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    @log_errors
    def validate_unique_paths(self) -> "RepoInventory":
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("repository file paths must be unique")
        return self


class LegacyComponent(ContractModel):
    """A known legacy component and the code that supports its description."""

    component_id: Identifier
    name: ShortText
    kind: Identifier
    description: LongText
    code_references: list[CodeReference] = Field(default_factory=list, max_length=500)


class LegacyCapability(ContractModel):
    """A legacy behavior or integration capability that must be accounted for."""

    capability_id: Identifier
    description: LongText
    component_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    evidence: list[CodeReference] = Field(default_factory=list, max_length=500)


class LegacyModel(AgentArtifact):
    """Analyzed representation of known legacy components and behavior."""

    artifact_type: Literal[ArtifactType.LEGACY_MODEL] = ArtifactType.LEGACY_MODEL
    components: list[LegacyComponent] = Field(min_length=1, max_length=5_000)
    capabilities: list[LegacyCapability] = Field(default_factory=list, max_length=5_000)
    integrations: list[ShortText] = Field(default_factory=list, max_length=500)
    data_stores: list[ShortText] = Field(default_factory=list, max_length=100)
    business_rules: list[ShortText] = Field(default_factory=list, max_length=5_000)

    @model_validator(mode="after")
    @log_errors
    def validate_component_references(self) -> "LegacyModel":
        component_ids = [component.component_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component_id values must be unique")
        known = set(component_ids)
        for capability in self.capabilities:
            if not set(capability.component_ids).issubset(known):
                raise ValueError("capabilities may reference only declared components")
        return self


class TargetStack(ContractModel):
    """Requested target technology stack without implying approval."""

    language: Identifier
    runtime: Identifier | None = None
    framework: Identifier | None = None
    database: Identifier | None = None


class TargetComponent(ContractModel):
    """A proposed target component and the legacy capabilities it covers."""

    component_id: Identifier
    name: ShortText
    responsibility: LongText
    maps_legacy_capabilities: list[Identifier] = Field(default_factory=list, max_length=500)


class ArchitectureDecision(ContractModel):
    """A technical decision in a blueprint; approval remains a separate gate record."""

    decision_id: Identifier
    summary: ShortText
    rationale: LongText
    alternatives: list[ShortText] = Field(default_factory=list, max_length=50)


class TargetBlueprint(AgentArtifact):
    """Proposed target architecture and constraints produced by Architect."""

    artifact_type: Literal[ArtifactType.TARGET_BLUEPRINT] = ArtifactType.TARGET_BLUEPRINT
    target_stack: TargetStack
    components: list[TargetComponent] = Field(min_length=1, max_length=5_000)
    decisions: list[ArchitectureDecision] = Field(default_factory=list, max_length=500)
    constraints: list[ShortText] = Field(default_factory=list, max_length=500)


class FeasibilityRating(StrEnum):
    """TDD feasibility categories for a target-stack capability."""

    NATIVE = "native"
    LIBRARY = "library"
    CUSTOM = "custom"
    UNSUPPORTED = "unsupported"


class GapOption(ContractModel):
    """A human-selectable gap response with explicit cost and verification impact."""

    option_id: Identifier
    description: ShortText
    effort: ShortText
    verification_impact: LongText


class FeasibilityItem(ContractModel):
    """Assessment of one required legacy capability in the target stack."""

    capability: ShortText
    legacy_evidence: list[CodeReference] = Field(default_factory=list, max_length=500)
    rating: FeasibilityRating
    candidate: ShortText | None = None
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    options: list[GapOption] = Field(default_factory=list, max_length=20)
    verification_impact: LongText

    @model_validator(mode="after")
    @log_errors
    def validate_gap_details(self) -> "FeasibilityItem":
        if self.rating is FeasibilityRating.LIBRARY and self.candidate is None:
            raise ValueError("library feasibility requires a named candidate")
        if (
            self.rating in {FeasibilityRating.CUSTOM, FeasibilityRating.UNSUPPORTED}
            and not self.options
        ):
            raise ValueError("custom or unsupported capabilities require explicit options")
        return self


class FeasibilityStatus(StrEnum):
    """Aggregate feasibility assessment, distinct from gate approval."""

    FEASIBLE = "feasible"
    GAPS_IDENTIFIED = "gaps_identified"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"


class FeasibilityReport(AgentArtifact):
    """Capability gaps, tooling gaps, and options for the G1 decision."""

    artifact_type: Literal[ArtifactType.FEASIBILITY_REPORT] = ArtifactType.FEASIBILITY_REPORT
    status: FeasibilityStatus
    items: list[FeasibilityItem] = Field(min_length=1, max_length=5_000)
    pipeline_tool_gaps: list[ShortText] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    @log_errors
    def validate_aggregate_status(self) -> "FeasibilityReport":
        has_unsupported = any(item.rating is FeasibilityRating.UNSUPPORTED for item in self.items)
        needs_gate = bool(self.pipeline_tool_gaps) or any(
            item.rating in {FeasibilityRating.CUSTOM, FeasibilityRating.UNSUPPORTED}
            or item.confidence < 0.8
            for item in self.items
        )
        if has_unsupported and self.status is FeasibilityStatus.FEASIBLE:
            raise ValueError("a report with unsupported capabilities cannot be feasible")
        if needs_gate and not self.assessment.needs_human:
            raise ValueError("gaps and low-confidence items must request human review")
        return self


class RiskLevel(StrEnum):
    """Bounded execution risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConversionUnit(ContractModel):
    """One independently ordered unit in the conversion DAG."""

    unit_id: Identifier
    name: ShortText
    scope: list[str] = Field(min_length=1, max_length=1_000)
    depends_on: list[Identifier] = Field(default_factory=list, max_length=500)
    risk: RiskLevel
    mapping_decisions: list[ShortText] = Field(default_factory=list, max_length=200)

    @field_validator("scope")
    @classmethod
    @log_errors
    def validate_scope_paths(cls, values: list[str]) -> list[str]:
        return [validate_repository_path(value) for value in values]


class ConversionPlan(AgentArtifact):
    """Dependency-ordered conversion units produced by Planner."""

    artifact_type: Literal[ArtifactType.CONVERSION_PLAN] = ArtifactType.CONVERSION_PLAN
    units: list[ConversionUnit] = Field(min_length=1, max_length=5_000)
    estimated_effort: ShortText | None = None
    planning_constraints: list[ShortText] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    @log_errors
    def validate_dag(self) -> "ConversionPlan":
        unit_ids = [unit.unit_id for unit in self.units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("conversion unit ids must be unique")
        known = set(unit_ids)
        graph = {unit.unit_id: set(unit.depends_on) for unit in self.units}
        for unit_id, dependencies in graph.items():
            if unit_id in dependencies:
                raise ValueError("a conversion unit cannot depend on itself")
            if not dependencies.issubset(known):
                raise ValueError("conversion dependencies must reference declared units")

        visiting: set[str] = set()
        visited: set[str] = set()

        @log_errors
        def visit(unit_id: str) -> None:
            if unit_id in visiting:
                raise ValueError("conversion unit dependencies must form an acyclic graph")
            if unit_id in visited:
                return
            visiting.add(unit_id)
            for dependency in graph[unit_id]:
                visit(dependency)
            visiting.remove(unit_id)
            visited.add(unit_id)

        for unit_id in unit_ids:
            visit(unit_id)
        return self


class CharacterizationLayer(StrEnum):
    """TDD-defined characterization test layers."""

    UNIT = "unit"
    API_CONTRACT = "api_contract"
    DATA_EFFECTS = "data_effects"
    BATCH_FILE = "batch_file"
    UI_FLOW = "ui_flow"


class CharacterizationCaseReference(ContractModel):
    """Identity and stored definition for a characterization test case."""

    case_id: uuid.UUID
    name: ShortText
    layer: CharacterizationLayer
    definition: EvidenceReference
    source_references: list[CodeReference] = Field(default_factory=list, max_length=500)


class NormalizationRule(ContractModel):
    """Explicit normalization rule that may affect equivalence comparisons."""

    rule_id: Identifier
    description: LongText
    justification: LongText


class CharacterizationSuite(AgentArtifact):
    """Versioned test inventory captured from legacy behavior."""

    artifact_type: Literal[ArtifactType.CHARACTERIZATION_SUITE] = (
        ArtifactType.CHARACTERIZATION_SUITE
    )
    suite_id: uuid.UUID
    suite_version: int = Field(ge=1)
    cases: list[CharacterizationCaseReference] = Field(min_length=1, max_length=20_000)
    normalization_rules: list[NormalizationRule] = Field(default_factory=list, max_length=500)
    suite_content_hash: Sha256Digest
    frozen: bool = False
    approval_reference: uuid.UUID | None = None

    @model_validator(mode="after")
    @log_errors
    def validate_freeze_state(self) -> "CharacterizationSuite":
        if self.frozen and self.approval_reference is None:
            raise ValueError("a frozen suite requires its G2 approval reference")
        if not self.frozen and self.approval_reference is not None:
            raise ValueError("approval_reference is only valid for a frozen suite")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("characterization case ids must be unique")
        return self


class SchemaMapping(ContractModel):
    """A source-to-target data structure mapping."""

    mapping_id: Identifier
    source: ShortText
    target: ShortText
    transformation: LongText
    evidence: list[CodeReference] = Field(default_factory=list, max_length=500)


class DataRisk(ContractModel):
    """Explicit data migration risk and proposed mitigation."""

    risk_id: Identifier
    level: RiskLevel
    description: LongText
    mitigation: LongText | None = None


class SchemaPlan(AgentArtifact):
    """Source/target schema mappings, transformations, and data risks."""

    artifact_type: Literal[ArtifactType.SCHEMA_PLAN] = ArtifactType.SCHEMA_PLAN
    mappings: list[SchemaMapping] = Field(min_length=1, max_length=10_000)
    transformation_decisions: list[ArchitectureDecision] = Field(
        default_factory=list, max_length=500
    )
    risks: list[DataRisk] = Field(default_factory=list, max_length=1_000)


class ComparisonOutcomeStatus(StrEnum):
    """Observed comparison result before any human waiver."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class DifferenceClassification(StrEnum):
    """TDD-required classification for every failing comparison."""

    REGRESSION = "regression"
    INTENDED_DIFFERENCE = "intended_difference"
    NONDETERMINISTIC = "nondeterministic"
    TEST_DEFECT = "test_defect"


class ComparisonOutcome(ContractModel):
    """One characterization comparison and its evidence."""

    case_id: uuid.UUID
    status: ComparisonOutcomeStatus
    classification: DifferenceClassification | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=100)
    details: LongText | None = None

    @model_validator(mode="after")
    @log_errors
    def validate_classification(self) -> "ComparisonOutcome":
        if self.status is ComparisonOutcomeStatus.FAILED and self.classification is None:
            raise ValueError("every failed comparison requires a classification")
        if self.status is not ComparisonOutcomeStatus.FAILED and self.classification is not None:
            raise ValueError("classification applies only to failed comparisons")
        return self


class VerificationStatus(StrEnum):
    """Verification outcome without conflating waivers or gate approval."""

    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class EquivalenceReport(AgentArtifact):
    """Characterization outcomes, discrepancies, evidence, and explicit waivers."""

    artifact_type: Literal[ArtifactType.EQUIVALENCE_REPORT] = ArtifactType.EQUIVALENCE_REPORT
    suite: ArtifactReference
    verification_status: VerificationStatus
    outcomes: list[ComparisonOutcome] = Field(min_length=1, max_length=20_000)
    uncovered_areas: list[CodeReference] = Field(default_factory=list, max_length=5_000)
    waiver_references: list[uuid.UUID] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    @log_errors
    def validate_verification_status(self) -> "EquivalenceReport":
        if self.verification_status is VerificationStatus.PASSED and any(
            outcome.status is not ComparisonOutcomeStatus.PASSED for outcome in self.outcomes
        ):
            raise ValueError("passed verification requires every recorded outcome to pass")
        if (
            any(outcome.status is ComparisonOutcomeStatus.NOT_RUN for outcome in self.outcomes)
            and self.verification_status is not VerificationStatus.INCOMPLETE
        ):
            raise ValueError("not-run outcomes require incomplete verification status")
        return self


class GateResolution(StrEnum):
    """Observed state of a required gate at report generation time."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


class GateReference(ContractModel):
    """Reference to an independently stored human gate decision."""

    gate_id: uuid.UUID
    gate_type: Identifier
    state: GateResolution
    decision_id: uuid.UUID | None = None

    @model_validator(mode="after")
    @log_errors
    def validate_decision_reference(self) -> "GateReference":
        if self.state is GateResolution.APPROVED and self.decision_id is None:
            raise ValueError("approved gates require a decision reference")
        return self


class JobOutcome(StrEnum):
    """Final report outcome; success is constrained by verification and gates."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class JobReport(AgentArtifact):
    """Final job summary with artifact, verification, and approval references."""

    artifact_type: Literal[ArtifactType.JOB_REPORT] = ArtifactType.JOB_REPORT
    outcome: JobOutcome
    summary: LongText
    artifacts: list[ArtifactReference] = Field(min_length=1, max_length=5_000)
    verification_status: VerificationStatus
    required_gates: list[GateReference] = Field(min_length=1, max_length=20)
    unresolved_items: list[ShortText] = Field(default_factory=list, max_length=1_000)
    delivery_reference: Identifier | None = None

    @model_validator(mode="after")
    @log_errors
    def prevent_false_success(self) -> "JobReport":
        if self.outcome is JobOutcome.SUCCEEDED:
            if self.verification_status is not VerificationStatus.PASSED:
                raise ValueError("successful jobs require passed verification")
            if self.unresolved_items:
                raise ValueError("successful jobs cannot contain unresolved items")
            if any(gate.state is not GateResolution.APPROVED for gate in self.required_gates):
                raise ValueError("successful jobs require every required gate to be approved")
        return self


ArtifactContract = (
    RepoInventory
    | LegacyModel
    | TargetBlueprint
    | FeasibilityReport
    | ConversionPlan
    | CharacterizationSuite
    | SchemaPlan
    | EquivalenceReport
    | JobReport
)
