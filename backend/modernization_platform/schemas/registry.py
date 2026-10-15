"""Explicit registry for supported artifact type and schema-version pairs."""

from collections.abc import Mapping

from modernization_platform.core.decorators import log_errors
from modernization_platform.schemas.agent_artifacts import (
    AgentArtifact,
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
from modernization_platform.schemas.common import ArtifactType


class ArtifactRegistryError(ValueError):
    """Raised for unsupported or conflicting artifact registrations."""


class ArtifactContractRegistry:
    """In-memory allowlist with no dynamic imports or external side effects."""

    def __init__(
        self,
        registrations: Mapping[tuple[ArtifactType, str], type[AgentArtifact]] | None = None,
    ) -> None:
        self._registrations: dict[tuple[ArtifactType, str], type[AgentArtifact]] = {}
        if registrations:
            for (artifact_type, schema_version), model in registrations.items():
                self.register(artifact_type, schema_version, model)

    @log_errors
    def register(
        self,
        artifact_type: ArtifactType,
        schema_version: str,
        model: type[AgentArtifact],
    ) -> None:
        """Register one exact interpretation, rejecting duplicate keys."""
        key = (artifact_type, schema_version)
        if key in self._registrations:
            raise ArtifactRegistryError(
                f"duplicate artifact contract registration: {artifact_type.value} {schema_version}"
            )
        self._registrations[key] = model

    @log_errors
    def resolve(self, artifact_type: ArtifactType, schema_version: str) -> type[AgentArtifact]:
        """Resolve one exact supported interpretation; never fall back to latest."""
        model = self._registrations.get((artifact_type, schema_version))
        if model is None:
            raise ArtifactRegistryError(
                f"unsupported artifact contract: {artifact_type.value} {schema_version}"
            )
        return model

    @log_errors
    def supported_versions(self, artifact_type: ArtifactType) -> tuple[str, ...]:
        """Return deterministic supported versions for one artifact type."""
        return tuple(
            sorted(
                version
                for registered_type, version in self._registrations
                if registered_type is artifact_type
            )
        )


@log_errors
def _build_default_registry() -> ArtifactContractRegistry:
    registry = ArtifactContractRegistry()
    for artifact_type, model in (
        (ArtifactType.REPO_INVENTORY, RepoInventory),
        (ArtifactType.LEGACY_MODEL, LegacyModel),
        (ArtifactType.TARGET_BLUEPRINT, TargetBlueprint),
        (ArtifactType.FEASIBILITY_REPORT, FeasibilityReport),
        (ArtifactType.CONVERSION_PLAN, ConversionPlan),
        (ArtifactType.CHARACTERIZATION_SUITE, CharacterizationSuite),
        (ArtifactType.SCHEMA_PLAN, SchemaPlan),
        (ArtifactType.EQUIVALENCE_REPORT, EquivalenceReport),
        (ArtifactType.JOB_REPORT, JobReport),
    ):
        registry.register(artifact_type, "1.0.0", model)
    return registry


artifact_registry = _build_default_registry()

__all__ = [
    "ArtifactContractRegistry",
    "ArtifactRegistryError",
    "artifact_registry",
]
