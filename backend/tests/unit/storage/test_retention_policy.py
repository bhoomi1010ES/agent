"""Unit tests for storage retention policy engine and dependency protection."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from modernization_platform.storage.exceptions import (
    ActiveJobArtifactProtectionException,
    ArtifactReferentialIntegrityException,
)
from modernization_platform.storage.retention import (
    StorageRetentionPolicy,
)


def test_retention_policy_defaults() -> None:
    """Retention policy defaults to configured protected statuses and 90 days."""
    policy = StorageRetentionPolicy(retention_days=60)
    assert policy.retention_days == 60
    assert "queued" in policy.protected_job_statuses
    assert "running" in policy.protected_job_statuses
    assert "awaiting_approval" in policy.protected_job_statuses
    assert "paused" in policy.protected_job_statuses


@pytest.mark.parametrize("status", ["queued", "running", "awaiting_approval", "paused"])
def test_active_jobs_are_protected(status: str) -> None:
    """Artifacts belonging to active jobs cannot be deleted."""
    policy = StorageRetentionPolicy()
    assert policy.is_job_active(status) is True

    can_delete, reason = policy.can_delete(
        artifact_id=uuid.uuid4(),
        job_status=status,
    )
    assert can_delete is False
    assert f"belongs to active job with status '{status}'" in (reason or "")

    with pytest.raises(ActiveJobArtifactProtectionException):
        policy.enforce_can_delete(
            artifact_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            job_status=status,
        )


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_jobs_can_be_deleted_if_no_dependents(status: str) -> None:
    """Terminal jobs without dependents allow artifact deletion."""
    policy = StorageRetentionPolicy()
    assert policy.is_job_active(status) is False

    can_delete, reason = policy.can_delete(
        artifact_id=uuid.uuid4(),
        job_status=status,
        downstream_dependent_ids=None,
    )
    assert can_delete is True
    assert reason is None

    # Should not raise
    policy.enforce_can_delete(
        artifact_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        job_status=status,
        downstream_dependent_ids=None,
    )


def test_referential_integrity_prevents_deletion() -> None:
    """Artifacts with downstream dependents in lineage cannot be deleted."""
    policy = StorageRetentionPolicy()
    child_id = uuid.uuid4()
    art_id = uuid.uuid4()

    can_delete, reason = policy.can_delete(
        artifact_id=art_id,
        job_status="completed",
        downstream_dependent_ids=[child_id],
    )
    assert can_delete is False
    assert "referenced in lineage" in (reason or "")

    with pytest.raises(ArtifactReferentialIntegrityException) as exc_info:
        policy.enforce_can_delete(
            artifact_id=art_id,
            job_id=uuid.uuid4(),
            job_status="completed",
            downstream_dependent_ids=[child_id],
        )
    assert exc_info.value.artifact_id == str(art_id)
    assert exc_info.value.dependent_ids == [str(child_id)]


def test_expiration_calculation() -> None:
    """Artifact is expired only when created_at + retention_days <= reference time."""
    policy = StorageRetentionPolicy(retention_days=30)
    now = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

    fresh_created = now - timedelta(days=10)
    assert policy.is_expired(fresh_created, now=now) is False

    boundary_created = now - timedelta(days=30)
    assert policy.is_expired(boundary_created, now=now) is True

    old_created = now - timedelta(days=60)
    assert policy.is_expired(old_created, now=now) is True
