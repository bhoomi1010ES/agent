"""Security tests for untrusted artifact boundaries."""

import copy

import pytest

from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.validation import (
    MAX_ARTIFACT_PAYLOAD_BYTES,
    ArtifactValidationError,
    parse_artifact,
)
from tests.contract.factories import repo_inventory_payload


@pytest.mark.parametrize(
    "path",
    ["../secret.txt", "/etc/passwd", "C:/Windows/system.ini", "src\\secret.py"],
)
def test_repository_paths_reject_traversal_and_absolute_paths(path: str) -> None:
    """Repository-derived paths cannot escape the repository namespace."""
    payload = repo_inventory_payload()
    payload["files"][0]["relative_path"] = path
    with pytest.raises(ArtifactValidationError):
        parse_artifact(
            payload,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
        )


def test_unknown_type_and_type_mismatch_are_rejected() -> None:
    """Untrusted output cannot select an arbitrary parser or lie about its type."""
    with pytest.raises(ArtifactValidationError) as unknown:
        parse_artifact(
            repo_inventory_payload(),
            expected_type="PythonObject",
            expected_schema_version="1.0.0",
        )
    assert unknown.value.code == "UNKNOWN_ARTIFACT_TYPE"

    payload = repo_inventory_payload()
    payload["artifact_type"] = "LegacyModel"
    with pytest.raises(ArtifactValidationError) as mismatch:
        parse_artifact(
            payload,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
        )
    assert mismatch.value.code == "ARTIFACT_TYPE_MISMATCH"


def test_oversized_and_deep_payloads_are_rejected_before_schema_acceptance() -> None:
    """Bounded parsing rejects resource-exhaustion payloads deterministically."""
    oversized = b"{" + b'"x":"' + (b"a" * MAX_ARTIFACT_PAYLOAD_BYTES) + b'"}'
    with pytest.raises(ArtifactValidationError) as raised:
        parse_artifact(
            oversized,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
        )
    assert raised.value.code == "PAYLOAD_TOO_LARGE"

    deep: dict[str, object] = repo_inventory_payload()
    current: dict[str, object] = deep
    for _ in range(25):
        nested: dict[str, object] = {}
        current["nested"] = nested
        current = nested
    with pytest.raises(ArtifactValidationError) as depth_error:
        parse_artifact(
            deep,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
        )
    assert depth_error.value.code == "PAYLOAD_TOO_DEEP"


def test_safe_validation_errors_do_not_echo_sensitive_values() -> None:
    """Schema diagnostics identify fields without copying secret-like input values."""
    payload = copy.deepcopy(repo_inventory_payload())
    secret = "sk-this-must-never-appear"
    payload["repository_id"] = secret
    payload["files"] = []
    with pytest.raises(ArtifactValidationError) as raised:
        parse_artifact(
            payload,
            expected_type=ArtifactType.REPO_INVENTORY,
            expected_schema_version="1.0.0",
        )
    serialized_issues = " ".join(issue.model_dump_json() for issue in raised.value.issues)
    assert secret not in str(raised.value)
    assert secret not in serialized_issues
