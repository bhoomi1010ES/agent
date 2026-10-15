"""Contract tests for all nine versioned artifact types."""

from collections.abc import Callable
from typing import Any

import pytest

from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.validation import ArtifactValidationError, parse_artifact
from tests.contract.factories import ARTIFACT_PAYLOADS


@pytest.mark.parametrize(("artifact_type", "factory"), ARTIFACT_PAYLOADS.items())
def test_each_artifact_accepts_representative_valid_payload(
    artifact_type: ArtifactType,
    factory: Callable[[], dict[str, Any]],
) -> None:
    """Every TDD artifact has an exact v1 contract and canonical representation."""
    result = parse_artifact(factory(), expected_type=artifact_type, expected_schema_version="1.0.0")
    assert result.artifact.artifact_type is artifact_type
    assert result.artifact.schema_version == "1.0.0"
    assert len(result.content_hash) == 64


@pytest.mark.parametrize(("artifact_type", "factory"), ARTIFACT_PAYLOADS.items())
def test_each_artifact_rejects_unexpected_fields(
    artifact_type: ArtifactType,
    factory: Callable[[], dict[str, Any]],
) -> None:
    """Trusted agent artifact boundaries never discard unknown fields."""
    payload = factory()
    payload["unexpected"] = "not allowed"
    with pytest.raises(ArtifactValidationError) as raised:
        parse_artifact(payload, expected_type=artifact_type, expected_schema_version="1.0.0")
    assert raised.value.code == "ARTIFACT_SCHEMA_INVALID"


def test_artifact_specific_invariants_reject_invalid_meaning() -> None:
    """Cross-field invariants prevent cyclic plans and false success reports."""
    plan = ARTIFACT_PAYLOADS[ArtifactType.CONVERSION_PLAN]()
    plan["units"][0]["depends_on"] = ["api"]
    with pytest.raises(ArtifactValidationError):
        parse_artifact(
            plan,
            expected_type=ArtifactType.CONVERSION_PLAN,
            expected_schema_version="1.0.0",
        )

    report = ARTIFACT_PAYLOADS[ArtifactType.JOB_REPORT]()
    report["required_gates"][0]["state"] = "pending"
    report["required_gates"][0]["decision_id"] = None
    with pytest.raises(ArtifactValidationError):
        parse_artifact(
            report,
            expected_type=ArtifactType.JOB_REPORT,
            expected_schema_version="1.0.0",
        )
