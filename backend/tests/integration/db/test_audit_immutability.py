"""PostgreSQL integration tests verifying audit event persistence, query, and append-only semantics."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.jobs import JobRepository


@pytest.mark.asyncio
async def test_audit_event_append_and_query(db_session: AsyncSession) -> None:
    """Verify AuditEventRepository appends events with correlation tracking and query capabilities."""
    job_repo = JobRepository(db_session)
    audit_repo = AuditEventRepository(db_session)

    job = await job_repo.create_job(name="Audited Modernization Job")
    await db_session.commit()

    event = await audit_repo.append_event(
        event_type="JOB_STARTED",
        actor_identity="user:dev_lead_42",
        job_id=job.id,
        correlation_id="corr-req-789",
        metadata_payload={"initiated_by": "api_trigger", "source_branch": "legacy/v2.4"},
    )
    await db_session.commit()

    assert event.id is not None
    assert event.timestamp is not None
    assert event.event_type == "JOB_STARTED"
    assert event.actor_identity == "user:dev_lead_42"
    assert event.correlation_id == "corr-req-789"

    # Query events for the job
    events = await audit_repo.list_events_by_job(job.id)
    assert len(events) == 1
    assert events[0].id == event.id
    assert events[0].metadata_payload == {
        "initiated_by": "api_trigger",
        "source_branch": "legacy/v2.4",
    }


@pytest.mark.asyncio
async def test_audit_event_repository_has_no_update_or_delete_methods() -> None:
    """Verify AuditEventRepository enforces append-only semantics by not providing update or delete APIs."""
    repo_methods = dir(AuditEventRepository)
    assert "append_event" in repo_methods
    assert "get_by_id" in repo_methods
    assert "list_events_by_job" in repo_methods

    # Mutating operations must not exist on AuditEventRepository
    assert "update_event" not in repo_methods
    assert "delete_event" not in repo_methods
    assert "remove_event" not in repo_methods
    assert "purge_events" not in repo_methods
