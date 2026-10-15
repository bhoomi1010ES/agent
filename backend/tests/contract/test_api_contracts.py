"""Transport contract tests for jobs, errors, artifacts, and gate decisions."""

import uuid

import pytest
from pydantic import ValidationError

from modernization_platform.schemas.artifacts import ArtifactValidationRequest
from modernization_platform.schemas.common import ArtifactType
from modernization_platform.schemas.errors import ErrorResponse, ValidationIssue
from modernization_platform.schemas.gates import GateDecisionRequest
from modernization_platform.schemas.jobs import JobCreateRequest
from tests.contract.factories import repo_inventory_payload


def test_job_request_rejects_owner_and_unknown_fields() -> None:
    """Authenticated owner identity cannot be forged in the create-job body."""
    payload = {
        "source_repository": "https://example.com/legacy.git",
        "source_revision": "abc123",
        "target_stack": {
            "language": "python",
            "runtime": "3.13",
            "framework": "FastAPI",
            "database": "PostgreSQL",
        },
        "budget": {"max_cost_cents": 10_000},
        "owner": "forged-user",
    }
    with pytest.raises(ValidationError):
        JobCreateRequest.model_validate(payload)


def test_gate_decision_does_not_accept_actor_or_silent_rejection() -> None:
    """Actor identity is server-owned and rejection feedback is mandatory."""
    with pytest.raises(ValidationError):
        GateDecisionRequest.model_validate({"decision": "rejected", "waivers": []})
    with pytest.raises(ValidationError):
        GateDecisionRequest.model_validate(
            {"decision": "approved", "waivers": [], "actor": "forged-approver"}
        )


def test_artifact_validation_request_is_typed() -> None:
    """Transport input declares workflow expectations separately from payload validation."""
    request = ArtifactValidationRequest(
        expected_artifact_type=ArtifactType.REPO_INVENTORY,
        expected_schema_version="1.0.0",
        payload=repo_inventory_payload(),
    )
    assert request.expected_artifact_type.value == "RepoInventory"


def test_error_contract_excludes_rejected_values() -> None:
    """Standard errors carry safe issue metadata without a raw-input field."""
    response = ErrorResponse(
        code="VALIDATION_ERROR",
        message="Request input validation failed",
        request_id=str(uuid.uuid4()),
        details=[ValidationIssue(field="body.token", issue="Invalid value", type="value_error")],
    )
    assert '"input":' not in response.model_dump_json()
