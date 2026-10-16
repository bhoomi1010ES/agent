"""Storage retention policy engine enforcing active job protection and referential integrity."""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from modernization_platform.config.settings import get_settings
from modernization_platform.core.decorators import log_errors
from modernization_platform.storage.exceptions import (
    ActiveJobArtifactProtectionException,
    ArtifactReferentialIntegrityException,
)

logger = logging.getLogger(__name__)

DEFAULT_PROTECTED_JOB_STATUSES = frozenset({"queued", "running", "awaiting_approval", "paused"})


class StorageRetentionPolicy:
    """Policy engine governing artifact retention, active job protection, and dependency preservation."""

    def __init__(
        self,
        retention_days: int | None = None,
        protected_job_statuses: Sequence[str] | None = None,
    ) -> None:
        try:
            settings = get_settings()
            self.retention_days = (
                retention_days if retention_days is not None else settings.storage_retention_days
            )
            raw_statuses = (
                protected_job_statuses
                if protected_job_statuses is not None
                else settings.storage_retention_protected_job_statuses
            )
            self.protected_job_statuses = frozenset(s.lower() for s in raw_statuses)
        except Exception:
            self.retention_days = 90
            self.protected_job_statuses = DEFAULT_PROTECTED_JOB_STATUSES

    @log_errors
    def is_job_active(self, job_status: str) -> bool:
        """Return True if job status represents an active, non-terminal modernization job."""
        try:
            return job_status.lower() in self.protected_job_statuses
        except Exception as exc:
            logger.exception("is_job_active check failed | %s: %s", type(exc).__name__, exc)
            return True

    @log_errors
    def is_expired(self, created_at: datetime, now: datetime | None = None) -> bool:
        """Evaluate if an artifact has exceeded its configured retention lifespan."""
        try:
            reference_time = now or datetime.now(UTC)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            expiry_threshold = created_at + timedelta(days=self.retention_days)
            return reference_time >= expiry_threshold
        except Exception as exc:
            logger.exception("is_expired check failed | %s: %s", type(exc).__name__, exc)
            return False

    @log_errors
    def can_delete(
        self,
        *,
        artifact_id: uuid.UUID,
        job_status: str,
        downstream_dependent_ids: Sequence[uuid.UUID] | None = None,
    ) -> tuple[bool, str | None]:
        """Check whether an artifact can safely be deleted under retention and lineage rules."""
        try:
            if self.is_job_active(job_status):
                return (
                    False,
                    f"Artifact '{artifact_id}' belongs to active job with status '{job_status}'.",
                )

            if downstream_dependent_ids:
                dep_strs = [str(did) for did in downstream_dependent_ids]
                return (
                    False,
                    f"Artifact '{artifact_id}' is referenced in lineage by downstream artifacts: {dep_strs}.",
                )

            return True, None
        except Exception as exc:
            logger.exception("can_delete check failed | %s: %s", type(exc).__name__, exc)
            return False, f"Evaluation error: {exc}"

    @log_errors
    def enforce_can_delete(
        self,
        *,
        artifact_id: uuid.UUID,
        job_id: uuid.UUID,
        job_status: str,
        downstream_dependent_ids: Sequence[uuid.UUID] | None = None,
    ) -> None:
        """Enforce deletion rules, raising typed exceptions on policy violations."""
        try:
            if self.is_job_active(job_status):
                raise ActiveJobArtifactProtectionException(
                    f"Cannot delete artifact '{artifact_id}' belonging to active job '{job_id}' in state '{job_status}'.",
                    job_id=job_id,
                    artifact_id=artifact_id,
                )

            if downstream_dependent_ids:
                raise ArtifactReferentialIntegrityException(
                    f"Cannot delete artifact '{artifact_id}' because it is referenced in lineage by {len(downstream_dependent_ids)} downstream artifact(s).",
                    artifact_id=artifact_id,
                    dependent_ids=[str(did) for did in downstream_dependent_ids],
                )
        except (ActiveJobArtifactProtectionException, ArtifactReferentialIntegrityException):
            raise
        except Exception as exc:
            logger.exception("enforce_can_delete failed | %s: %s", type(exc).__name__, exc)
            raise


__all__ = [
    "DEFAULT_PROTECTED_JOB_STATUSES",
    "StorageRetentionPolicy",
]
