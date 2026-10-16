"""Integration tests for lease renewal, non-owner rejection, automated renewal loop, and safe lease release."""

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.domain.tasks.states import TaskLifecycleState
from modernization_platform.repositories.tasks import TaskRepository
from modernization_platform.workers.lease_manager import LeaseManager
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database
from tests.integration.workflows.test_reconciliation import _create_test_job, _create_test_principal


@pytest.mark.asyncio
async def test_lease_renewal_ownership_protection(db_session: AsyncSession) -> None:
    """Only the verified owning worker can renew a valid lease; non-owners and completed tasks are rejected."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        await repo.create_task(job_id=job.id, task_type="workflow_step")
        claimed = await repo.claim_next_task(worker_id="legitimate-owner", lease_seconds=10.0)
        assert claimed is not None
        assert claimed.lease_expires_at is not None
        initial_expiry = claimed.lease_expires_at
        task_id = claimed.id

    # 1. Non-owner attempts renewal -> rejected
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        impostor_renewed = await repo.renew_lease(
            task_id=task_id,
            worker_id="impostor-worker",
            extend_seconds=30.0,
        )
        assert impostor_renewed is False

    # Verify lease expiry is unchanged
    async with session_factory() as session:
        repo = TaskRepository(session)
        t = await repo.get_by_id(task_id)
        assert t is not None
        assert t.lease_expires_at == initial_expiry

    # 2. Legitimate owner renews -> succeeds, expiry extended
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        owner_renewed = await repo.renew_lease(
            task_id=task_id,
            worker_id="legitimate-owner",
            extend_seconds=60.0,
        )
        assert owner_renewed is True

    async with session_factory() as session:
        repo = TaskRepository(session)
        t = await repo.get_by_id(task_id)
        assert t is not None
        assert t.lease_expires_at is not None
        assert t.lease_expires_at > initial_expiry

    # 3. Complete the task, then attempt renewal -> rejected
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        await repo.complete_task(
            task_id=task_id,
            worker_id="legitimate-owner",
            result_payload={"done": True},
        )

    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        after_completed_renew = await repo.renew_lease(
            task_id=task_id,
            worker_id="legitimate-owner",
            extend_seconds=60.0,
        )
        assert after_completed_renew is False


@pytest.mark.asyncio
async def test_lease_manager_automated_background_renewal(db_session: AsyncSession) -> None:
    """LeaseManager automatically periodically extends the lease expiration in PostgreSQL."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    lm = LeaseManager(
        worker_id="auto-renew-worker",
        session_factory=session_factory,
        lease_duration_seconds=10.0,
        renewal_interval_seconds=0.2,  # fast renewal for testing
    )

    task_id: uuid.UUID
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t = await repo.create_task(job_id=job.id, task_type="workflow_step")
        task_id = t.id
        claimed = await lm.acquire_lease(session, lease_seconds=5.0)
        assert claimed is not None
        assert claimed.lease_expires_at is not None
        initial_expiry = claimed.lease_expires_at

    # Start automated background renewal loop
    lm.start()
    try:
        # Sleep long enough for multiple background renewal cycles
        await asyncio.sleep(0.6)

        # Inspect DB to verify lease_expires_at advanced
        async with session_factory() as session:
            repo = TaskRepository(session)
            refreshed = await repo.get_by_id(task_id)
            assert refreshed is not None
            assert refreshed.lease_expires_at is not None
            assert refreshed.lease_expires_at > initial_expiry
    finally:
        await lm.stop()


@pytest.mark.asyncio
async def test_safe_lease_release(db_session: AsyncSession) -> None:
    """A worker safely releasing a lease returns the task to pending so another worker can claim it immediately."""
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
        claimed = await repo.claim_next_task(worker_id="worker-releasing", lease_seconds=60.0)
        assert claimed is not None
        assert claimed.status == TaskLifecycleState.RUNNING.value

    # Non-owner cannot release
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        wrong_rel = await repo.release_lease(task_id=task_id, worker_id="wrong-worker")
        assert wrong_rel is False

    # Owner safely releases lease
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        released = await repo.release_lease(task_id=task_id, worker_id="worker-releasing")
        assert released is True

    # Check database state: status reverted to PENDING, worker_id=None, lease_expires_at=None
    async with session_factory() as session:
        repo = TaskRepository(session)
        t_after = await repo.get_by_id(task_id)
        assert t_after is not None
        assert t_after.status == TaskLifecycleState.PENDING.value
        assert t_after.worker_id is None
        assert t_after.lease_expires_at is None

    # Peer worker can claim it immediately
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        peer_claimed = await repo.claim_next_task(worker_id="peer-worker", lease_seconds=30.0)
        assert peer_claimed is not None
        assert peer_claimed.id == task_id
        assert peer_claimed.worker_id == "peer-worker"
