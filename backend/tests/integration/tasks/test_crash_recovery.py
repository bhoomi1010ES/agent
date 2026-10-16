"""Integration tests for worker crash recovery, expired lease reclaiming, stale-worker protection, and duplicate finalization prevention."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.db.models.task import Task
from modernization_platform.domain.tasks.errors import DuplicateFinalizationError, LeaseLostError
from modernization_platform.domain.tasks.states import TaskLifecycleState
from modernization_platform.repositories.tasks import TaskRepository
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database
from tests.integration.workflows.test_reconciliation import _create_test_job, _create_test_principal


@pytest.mark.asyncio
async def test_crashed_worker_lease_expiry_and_reclaim(db_session: AsyncSession) -> None:
    """When a worker crashes and its lease expires, a second worker safely reclaims the task."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    task_id: uuid.UUID
    # 1. Worker A claims the task
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t = await repo.create_task(job_id=job.id, task_type="workflow_step")
        task_id = t.id
        claimed_a = await repo.claim_next_task(worker_id="worker-A", lease_seconds=10.0)
        assert claimed_a is not None
        assert claimed_a.worker_id == "worker-A"
        assert claimed_a.attempt_count == 1

    # 2. Worker A "crashes": simulate time passing and lease expiring in the past
    past_expiry = datetime.now(UTC) - timedelta(seconds=15)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(Task).where(Task.id == task_id).values(lease_expires_at=past_expiry)
        )

    # 3. Worker B scans for claimable work and reclaims the expired task
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        claimed_b = await repo.claim_next_task(worker_id="worker-B", lease_seconds=30.0)
        assert claimed_b is not None
        assert claimed_b.id == task_id
        assert claimed_b.worker_id == "worker-B"
        # Attempt count incremented to 2
        assert claimed_b.attempt_count == 2
        assert claimed_b.lease_expires_at is not None
        assert claimed_b.lease_expires_at > datetime.now(UTC)

    # 4. Worker B completes the task successfully
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        await repo.complete_task(
            task_id=task_id,
            worker_id="worker-B",
            result_payload={"reclaimed_by": "worker-B", "status": "ok"},
        )

    # Verify task state in database
    async with session_factory() as session:
        repo = TaskRepository(session)
        final_task = await repo.get_by_id(task_id)
        assert final_task is not None
        assert final_task.status == TaskLifecycleState.COMPLETED.value
        assert final_task.result == {"reclaimed_by": "worker-B", "status": "ok"}


@pytest.mark.asyncio
async def test_stale_worker_completion_rejected(db_session: AsyncSession) -> None:
    """A stale worker whose lease expired and was reclaimed cannot finalize the task."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    task_id: uuid.UUID
    # Worker A claims task
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t = await repo.create_task(job_id=job.id, task_type="workflow_step")
        task_id = t.id
        claimed = await repo.claim_next_task(worker_id="worker-A", lease_seconds=5.0)
        assert claimed is not None

    # Simulate Worker A stalling: lease expires in DB
    past_expiry = datetime.now(UTC) - timedelta(seconds=10)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(Task).where(Task.id == task_id).values(lease_expires_at=past_expiry)
        )

    # Worker B reclaims the task
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        claimed_b = await repo.claim_next_task(worker_id="worker-B", lease_seconds=30.0)
        assert claimed_b is not None
        assert claimed_b.worker_id == "worker-B"

    # Stale Worker A wakes up and attempts to commit completion
    # Database level check (worker_id == 'worker-A' AND lease_expires_at >= now) must reject!
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        with pytest.raises(LeaseLostError) as exc_info:
            await repo.complete_task(
                task_id=task_id,
                worker_id="worker-A",
                result_payload={"stale_result": True},
            )
        assert "lost lease on task" in str(exc_info.value)

    # Worker B completes the task cleanly
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        await repo.complete_task(
            task_id=task_id,
            worker_id="worker-B",
            result_payload={"valid_result": True},
        )

    # Verify database holds Worker B's result, not Stale Worker A's result
    async with session_factory() as session:
        repo = TaskRepository(session)
        final_task = await repo.get_by_id(task_id)
        assert final_task is not None
        assert final_task.result == {"valid_result": True}


@pytest.mark.asyncio
async def test_duplicate_finalization_prevention(db_session: AsyncSession) -> None:
    """Concurrent attempts to complete a task result in exactly one successful finalization."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    task_id: uuid.UUID
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t = await repo.create_task(job_id=job.id, task_type="workflow_step")
        task_id = t.id
        claimed = await repo.claim_next_task(worker_id="worker-dual", lease_seconds=60.0)
        assert claimed is not None

    success_count = 0
    duplicate_count = 0
    lock = asyncio.Lock()

    async def attempt_completion(tag: str) -> None:
        nonlocal success_count, duplicate_count
        try:
            async with session_factory() as session, session.begin():
                repo = TaskRepository(session)
                await repo.complete_task(
                    task_id=task_id,
                    worker_id="worker-dual",
                    result_payload={"tag": tag},
                )
            async with lock:
                success_count += 1
        except (DuplicateFinalizationError, LeaseLostError):
            async with lock:
                duplicate_count += 1

    # Concurrently fire 2 completion attempts for the same task
    await asyncio.gather(attempt_completion("caller-1"), attempt_completion("caller-2"))

    # Exactly one succeeded and the other was rejected as duplicate
    assert success_count == 1
    assert duplicate_count == 1
