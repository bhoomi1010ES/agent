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


def test_changeset_enforces_directory_and_branch_constraints() -> None:
    """ChangeSet requires paths inside allowed directories and strict branch names."""
    # 1. Path outside allowed directories
    cs = ARTIFACT_PAYLOADS[ArtifactType.CHANGE_SET]()
    cs["files"].append(
        {
            "path": "outside/secret.py",
            "action": "create",
            "content": "leak = True\n",
            "old_path": None,
            "content_hash": None,
        }
    )
    with pytest.raises(ArtifactValidationError) as raised:
        parse_artifact(cs, expected_type=ArtifactType.CHANGE_SET, expected_schema_version="1.0.0")
    assert any("outside" in issue.issue for issue in raised.value.issues)

    # 2. Path traversal rejection
    cs_traversal = ARTIFACT_PAYLOADS[ArtifactType.CHANGE_SET]()
    cs_traversal["files"][0]["path"] = "src/auth/../../etc/passwd"
    with pytest.raises(ArtifactValidationError):
        parse_artifact(
            cs_traversal, expected_type=ArtifactType.CHANGE_SET, expected_schema_version="1.0.0"
        )

    # 3. Invalid branch pattern
    cs_branch = ARTIFACT_PAYLOADS[ArtifactType.CHANGE_SET]()
    cs_branch["branch"] = "main"
    with pytest.raises(ArtifactValidationError) as raised_branch:
        parse_artifact(
            cs_branch, expected_type=ArtifactType.CHANGE_SET, expected_schema_version="1.0.0"
        )
    assert any("branch" in issue.issue for issue in raised_branch.value.issues)

    # 4. Action content consistency (delete with content)
    cs_delete = ARTIFACT_PAYLOADS[ArtifactType.CHANGE_SET]()
    cs_delete["files"][0]["action"] = "delete"
    cs_delete["files"][0]["content"] = "should not have content"
    with pytest.raises(ArtifactValidationError):
        parse_artifact(
            cs_delete, expected_type=ArtifactType.CHANGE_SET, expected_schema_version="1.0.0"
        )

    # 5. Action content consistency (create without content)
    cs_create = ARTIFACT_PAYLOADS[ArtifactType.CHANGE_SET]()
    cs_create["files"][0]["action"] = "create"
    cs_create["files"][0]["content"] = None
    with pytest.raises(ArtifactValidationError):
        parse_artifact(
            cs_create, expected_type=ArtifactType.CHANGE_SET, expected_schema_version="1.0.0"
        )

    # 6. Duplicate file paths
    cs_dup = ARTIFACT_PAYLOADS[ArtifactType.CHANGE_SET]()
    cs_dup["files"].append(dict(cs_dup["files"][0]))
    with pytest.raises(ArtifactValidationError) as raised_dup:
        parse_artifact(
            cs_dup, expected_type=ArtifactType.CHANGE_SET, expected_schema_version="1.0.0"
        )
    assert any("unique" in issue.issue for issue in raised_dup.value.issues)


def test_review_report_enforces_severity_and_reference_invariants() -> None:
    """ReviewReport prevents false passes and dangling task references."""
    # 1. High severity finding blocking passed status
    rr_high = ARTIFACT_PAYLOADS[ArtifactType.REVIEW_REPORT]()
    rr_high["status"] = "passed"
    rr_high["findings"][0]["severity"] = "high"
    with pytest.raises(ArtifactValidationError) as raised_high:
        parse_artifact(
            rr_high, expected_type=ArtifactType.REVIEW_REPORT, expected_schema_version="1.0.0"
        )
    assert any("cannot pass" in issue.issue for issue in raised_high.value.issues)

    # 2. Fix task referencing unknown finding
    rr_unknown_find = ARTIFACT_PAYLOADS[ArtifactType.REVIEW_REPORT]()
    rr_unknown_find["fix_tasks"][0]["finding_ids"] = ["non-existent-finding-id"]
    with pytest.raises(ArtifactValidationError) as raised_ref:
        parse_artifact(
            rr_unknown_find,
            expected_type=ArtifactType.REVIEW_REPORT,
            expected_schema_version="1.0.0",
        )
    assert any("reference declared" in issue.issue for issue in raised_ref.value.issues)

    # 3. Duplicate finding IDs
    rr_dup_find = ARTIFACT_PAYLOADS[ArtifactType.REVIEW_REPORT]()
    rr_dup_find["findings"].append(dict(rr_dup_find["findings"][0]))
    with pytest.raises(ArtifactValidationError) as raised_dup_find:
        parse_artifact(
            rr_dup_find, expected_type=ArtifactType.REVIEW_REPORT, expected_schema_version="1.0.0"
        )
    assert any("unique" in issue.issue for issue in raised_dup_find.value.issues)

    # 4. Changes requested with no tasks and no human review flagged
    rr_no_action = ARTIFACT_PAYLOADS[ArtifactType.REVIEW_REPORT]()
    rr_no_action["status"] = "changes_requested"
    rr_no_action["fix_tasks"] = []
    rr_no_action["assessment"]["needs_human"] = False
    rr_no_action["assessment"]["human_review_reason"] = None
    with pytest.raises(ArtifactValidationError) as raised_no_act:
        parse_artifact(
            rr_no_action, expected_type=ArtifactType.REVIEW_REPORT, expected_schema_version="1.0.0"
        )
    assert any("non-passing review requires" in issue.issue for issue in raised_no_act.value.issues)
