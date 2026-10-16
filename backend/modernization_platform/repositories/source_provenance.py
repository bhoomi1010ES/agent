"""Repository layer for SourceProvenanceRecord persistence and queries."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.source_provenance import SourceProvenanceRecord
from modernization_platform.integrations.git.models import SourceProvenance

logger = logging.getLogger(__name__)


class SourceProvenanceRepository:
    """Encapsulates persistence, lookup, and updates for job source provenance."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @log_errors
    async def get_by_job_id(
        self,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> SourceProvenanceRecord | None:
        """Fetch provenance record for a job, optionally enforcing tenant boundary."""
        stmt = select(SourceProvenanceRecord).where(SourceProvenanceRecord.job_id == job_id)
        if tenant_id is not None:
            stmt = stmt.where(SourceProvenanceRecord.tenant_id == tenant_id)

        result = await self._session.execute(stmt)
        return result.scalars().first()

    @log_errors
    async def save_provenance(
        self,
        provenance: SourceProvenance,
        tenant_id: uuid.UUID | None = None,
    ) -> SourceProvenanceRecord:
        """Insert or update source provenance for a job."""
        existing = await self.get_by_job_id(provenance.job_id, tenant_id=tenant_id)
        if existing is not None:
            existing.repository_url = provenance.repository_url
            existing.provider = provenance.provider
            existing.requested_ref = provenance.requested_ref
            existing.resolved_commit_sha = provenance.resolved_commit_sha
            existing.branch = provenance.branch
            existing.tree_hash = provenance.tree_hash
            existing.commit_author = provenance.commit_author
            existing.commit_author_email = provenance.commit_author_email
            existing.commit_timestamp = provenance.commit_timestamp
            existing.commit_message = provenance.commit_message
            existing.file_count = provenance.repository_metadata.file_count
            existing.size_bytes = provenance.repository_metadata.size_bytes
            existing.repository_metadata = provenance.repository_metadata.model_dump(mode="json")
            existing.provenance_hash = provenance.provenance_hash
            existing.ingestion_status = provenance.ingestion_status
            existing.ingested_at = provenance.ingestion_timestamp
            await self._session.flush()
            return existing

        record = SourceProvenanceRecord(
            id=provenance.ingestion_id,
            job_id=provenance.job_id,
            tenant_id=tenant_id,
            repository_url=provenance.repository_url,
            provider=provenance.provider,
            requested_ref=provenance.requested_ref,
            resolved_commit_sha=provenance.resolved_commit_sha,
            branch=provenance.branch,
            tree_hash=provenance.tree_hash,
            commit_author=provenance.commit_author,
            commit_author_email=provenance.commit_author_email,
            commit_timestamp=provenance.commit_timestamp,
            commit_message=provenance.commit_message,
            file_count=provenance.repository_metadata.file_count,
            size_bytes=provenance.repository_metadata.size_bytes,
            repository_metadata=provenance.repository_metadata.model_dump(mode="json"),
            provenance_hash=provenance.provenance_hash,
            ingestion_status=provenance.ingestion_status,
            ingested_at=provenance.ingestion_timestamp,
        )
        self._session.add(record)
        await self._session.flush()
        return record


__all__ = ["SourceProvenanceRepository"]
