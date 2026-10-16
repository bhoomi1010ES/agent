"""Integration tests verifying atomic task claiming and FOR UPDATE SKIP LOCKED semantics in PostgreSQL."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.domain.tasks.states import TaskLifecycleState
from modernization_platform.repositories.tasks import TaskRepository
from tests.integration.db.conftest import _PORT_AVAILABLE, _skip_or_fail_database
from tests.integration.workflows.test_reconciliation import _create_test_job, _create_test_principal


@pytest.mark.asyncio
async def test_atomic_single_task_claiming(db_session: AsyncSession) -> None:
    """A worker atomically claims an available pending task and acquires its lease."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")

    repo = TaskRepository(db_session)
    task = await repo.create_task(
        job_id=job.id,
        task_type="workflow_step",
        payload={"step": "intake"},
    )
    assert task.status == TaskLifecycleState.PENDING.value
    assert task.worker_id is None
    assert task.attempt_count == 0

    now_before = datetime.now(UTC)
    claimed = await repo.claim_next_task(worker_id="worker-node-1", lease_seconds=45.0)

    assert claimed is not None
    assert claimed.id == task.id
    assert claimed.status == TaskLifecycleState.RUNNING.value
    assert claimed.worker_id == "worker-node-1"
    assert claimed.attempt_count == 1
    assert claimed.lease_expires_at is not None
    assert claimed.lease_expires_at > now_before

    # Verify no more tasks are claimable
    second_claim = await repo.claim_next_task(worker_id="worker-node-2")
    assert second_claim is None


@pytest.mark.asyncio
async def test_concurrent_task_claiming_no_duplicates(db_session: AsyncSession) -> None:
    """Multiple workers claiming concurrently from a pool of tasks never claim the same task."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    num_tasks = 8
    task_ids: list[uuid.UUID] = []

    async with session_factory() as setup_session, setup_session.begin():
        repo = TaskRepository(setup_session)
        for i in range(num_tasks):
            t = await repo.create_task(
                job_id=job.id,
                task_type="workflow_step",
                payload={"index": i},
            )
            task_ids.append(t.id)

    # 4 distinct workers compete concurrently to claim all 8 tasks
    worker_ids = [f"competing-worker-{i}" for i in range(4)]
    claimed_results: list[uuid.UUID] = []
    claimed_lock = asyncio.Lock()

    async def worker_loop(wid: str) -> None:
        while True:
            async with session_factory() as session, session.begin():
                w_repo = TaskRepository(session)
                claimed = await w_repo.claim_next_task(worker_id=wid, lease_seconds=30.0)
                if claimed is None:
                    break
                async with claimed_lock:
                    claimed_results.append(claimed.id)

    await asyncio.gather(*(worker_loop(wid) for wid in worker_ids))

    # All 8 tasks must have been claimed exactly once with no duplicates
    assert len(claimed_results) == num_tasks
    assert set(claimed_results) == set(task_ids)
    assert len(set(claimed_results)) == num_tasks


@pytest.mark.asyncio
async def test_skip_locked_behavior_bypasses_in_flight_transaction(
    db_session: AsyncSession,
) -> None:
    """A worker skips tasks locked by another active uncommitted transaction without blocking."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    t1_id: uuid.UUID
    t2_id: uuid.UUID
    async with session_factory() as setup_session, setup_session.begin():
        repo = TaskRepository(setup_session)
        t1 = await repo.create_task(job_id=job.id, task_type="workflow_step", payload={"order": 1})
        t2 = await repo.create_task(job_id=job.id, task_type="workflow_step", payload={"order": 2})
        t1_id = t1.id
        t2_id = t2.id

    # Session 1 begins a transaction and claims T1, holding the row lock open
    session1 = session_factory()
    await session1.begin()
    try:
        repo1 = TaskRepository(session1)
        claimed_w1 = await repo1.claim_next_task(worker_id="tx-worker-1", lease_seconds=60.0)
        assert claimed_w1 is not None
        assert claimed_w1.id == t1_id

        # Concurrently, Session 2 attempts to claim.
        # SKIP LOCKED must immediately return T2 without blocking on T1!
        async with session_factory() as session2, session2.begin():
            repo2 = TaskRepository(session2)
            claimed_w2 = await repo2.claim_next_task(worker_id="tx-worker-2", lease_seconds=60.0)
            assert claimed_w2 is not None
            # Worker 2 claimed T2 because T1 was locked by Session 1
            assert claimed_w2.id == t2_id

        # Commit Session 1
        await session1.commit()
    finally:
        await session1.close()

    # Verify final states in DB
    async with session_factory() as verify_session:
        v_repo = TaskRepository(verify_session)
        v_t1 = await v_repo.get_by_id(t1_id)
        v_t2 = await v_repo.get_by_id(t2_id)
        assert v_t1 is not None and v_t1.worker_id == "tx-worker-1"
        assert v_t2 is not None and v_t2.worker_id == "tx-worker-2"
