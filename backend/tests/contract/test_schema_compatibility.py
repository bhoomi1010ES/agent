"""Schema-version registry and compatibility matrix tests."""

import pytest

from modernization_platform.schemas.agent_artifacts import RepoInventory
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.compatibility import CompatibilityStatus, assess_compatibility
from modernization_platform.schemas.registry import (
    ArtifactContractRegistry,
    ArtifactRegistryError,
    artifact_registry,
)
from modernization_platform.schemas.validation import ArtifactValidationError, parse_artifact
from tests.contract.factories import repo_inventory_payload


def test_compatibility_matrix_is_explicit() -> None:
    """Current, older, newer, and invalid versions receive distinct outcomes."""
    assert (
        assess_compatibility(ArtifactType.REPO_INVENTORY, "1.0.0").status
        is CompatibilityStatus.SAME_VERSION
    )
    assert (
        assess_compatibility(ArtifactType.REPO_INVENTORY, "0.9.0").status
        is CompatibilityStatus.UNSUPPORTED_OLDER
    )
    assert (
        assess_compatibility(ArtifactType.REPO_INVENTORY, "2.0.0").status
        is CompatibilityStatus.NEWER_UNKNOWN
    )
    assert (
        assess_compatibility(ArtifactType.REPO_INVENTORY, "latest").status
        is CompatibilityStatus.INVALID_VERSION
    )


def test_unknown_version_is_never_interpreted_as_latest() -> None:
    """The registry rejects unknown versions even when the payload shape resembles v1."""
    payload = repo_inventory_payload()
    payload["schema_version"] = "2.0.0"
    with pytest.raises(ArtifactValidationError) as raised:
        parse_artifact(
            payload,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="2.0.0",
        )
    assert raised.value.code == "UNSUPPORTED_ARTIFACT_CONTRACT"
    assert artifact_registry.supported_versions(ArtifactType.REPO_INVENTORY) == ("1.0.0",)


def test_registry_rejects_duplicate_registration() -> None:
    """Conflicting interpretations cannot replace existing registrations."""
    registry = ArtifactContractRegistry()
    registry.register(ArtifactType.REPO_INVENTORY, "1.0.0", RepoInventory)
    with pytest.raises(ArtifactRegistryError):
        registry.register(ArtifactType.REPO_INVENTORY, "1.0.0", RepoInventory)


def test_all_eleven_artifact_types_are_registered_for_v1() -> None:
    """All 11 canonical artifact types defined in TDD have version 1.0.0 registered."""
    for artifact_type in ArtifactType:
        assert artifact_registry.supported_versions(artifact_type) == ("1.0.0",)
