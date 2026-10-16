"""Integration tests for worker runtime, bounded retry scheduling, cancellation, graceful shutdown, and LangGraph coordination."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.db.models.job import Job
from modernization_platform.db.models.task import Task
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.tasks.states import (
    TaskFailureClassification,
    TaskLifecycleState,
)
from modernization_platform.repositories.tasks import TaskRepository
from modernization_platform.workers.workflow_worker import WorkflowWorker
from modernization_platform.workflows.checkpointer import (
    ensure_windows_event_loop_policy,
    normalize_postgres_connection_string,
    setup_postgres_checkpointer,
)
from modernization_platform.workflows.engine import WorkflowEngine
from tests.integration.db.conftest import _PORT_AVAILABLE, TEST_DB_URL, _skip_or_fail_database
from tests.integration.workflows.test_reconciliation import _create_test_job, _create_test_principal


@pytest.mark.asyncio
async def test_bounded_retry_policy_in_database(db_session: AsyncSession) -> None:
    """Transient failures schedule retry until max attempts; permanent failures terminate immediately."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    # 1. Transient failure with remaining attempts -> RETRY_WAIT
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t1 = await repo.create_task(job_id=job.id, task_type="step", max_attempts=3)
        claimed = await repo.claim_next_task(worker_id="w-1", lease_seconds=30.0)
        assert claimed is not None
        assert claimed.attempt_count == 1

        await repo.fail_task(
            task_id=t1.id,
            worker_id="w-1",
            error_message="Network glitch",
            classification=TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR,
            retry_backoff_seconds=2.0,
        )

    async with session_factory() as session:
        repo = TaskRepository(session)
        t1_after = await repo.get_by_id(t1.id)
        assert t1_after is not None
        assert t1_after.status == TaskLifecycleState.RETRY_WAIT.value
        assert t1_after.retry_at is not None
        assert t1_after.worker_id is None  # worker released during wait

    # 2. Permanent failure -> immediately FAILED regardless of remaining attempts
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t2 = await repo.create_task(job_id=job.id, task_type="step", max_attempts=5)
        claimed2 = await repo.claim_next_task(worker_id="w-2", lease_seconds=30.0)
        assert claimed2 is not None

        await repo.fail_task(
            task_id=t2.id,
            worker_id="w-2",
            error_message="Invalid payload schema",
            classification=TaskFailureClassification.PERMANENT_FAILURE,
        )

    async with session_factory() as session:
        repo = TaskRepository(session)
        t2_after = await repo.get_by_id(t2.id)
        assert t2_after is not None
        assert t2_after.status == TaskLifecycleState.FAILED.value
        assert t2_after.completed_at is not None

    # 3. Max attempts reached on transient failure -> terminal FAILED
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        t3 = await repo.create_task(job_id=job.id, task_type="step", max_attempts=2)
        # Attempt 1
        c1 = await repo.claim_next_task(worker_id="w-3", lease_seconds=30.0)
        assert c1 is not None
        await repo.fail_task(
            task_id=t3.id,
            worker_id="w-3",
            error_message="Timeout 1",
            classification=TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR,
            retry_backoff_seconds=0.01,
        )

    # Set retry_at in past so attempt 2 is immediately claimable
    past = datetime.now(UTC) - timedelta(seconds=1)
    async with session_factory() as session, session.begin():
        await session.execute(update(Task).where(Task.id == t3.id).values(retry_at=past))

    # Attempt 2 (reaches max_attempts=2)
    async with session_factory() as session, session.begin():
        repo = TaskRepository(session)
        c2 = await repo.claim_next_task(worker_id="w-3", lease_seconds=30.0)
        assert c2 is not None
        assert c2.attempt_count == 2
        await repo.fail_task(
            task_id=t3.id,
            worker_id="w-3",
            error_message="Timeout 2",
            classification=TaskFailureClassification.RETRYABLE_INFRASTRUCTURE_ERROR,
        )

    async with session_factory() as session:
        repo = TaskRepository(session)
        t3_after = await repo.get_by_id(t3.id)
        assert t3_after is not None
        assert t3_after.status == TaskLifecycleState.FAILED.value
        assert t3_after.completed_at is not None


@pytest.mark.asyncio
async def test_job_cancellation_stops_task_processing(db_session: AsyncSession) -> None:
    """When a job is cancelled, executing tasks detect cancellation and abort without completing."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    ensure_windows_event_loop_policy()
    norm_url = normalize_postgres_connection_string(TEST_DB_URL)
    await setup_postgres_checkpointer(norm_url)

    async with AsyncPostgresSaver.from_conn_string(norm_url) as saver:
        engine = WorkflowEngine(checkpointer=saver)
        worker = WorkflowWorker(
            engine=engine,
            session_factory=session_factory,
            name="cancellation-worker",
        )

        task_id: uuid.UUID
        async with session_factory() as session, session.begin():
            repo = TaskRepository(session)
            t = await repo.create_task(job_id=job.id, task_type="workflow_step")
            task_id = t.id
            claimed = await worker.lease_manager.acquire_lease(session)
            assert claimed is not None

        # Mark parent job CANCELLED in database
        async with session_factory() as session, session.begin():
            await session.execute(
                update(Job).where(Job.id == job.id).values(status=JobLifecycleState.CANCELLED.value)
            )

        # Worker attempts to execute task -> detects cancellation
        result = await worker.execute_task(task_id)
        assert result is None

        # Verify task is cancelled in database
        async with session_factory() as session:
            repo = TaskRepository(session)
            task_after = await repo.get_by_id(task_id)
            assert task_after is not None
            assert task_after.status == TaskLifecycleState.CANCELLED.value
            assert task_after.completed_at is not None


@pytest.mark.asyncio
async def test_worker_graceful_shutdown_releases_leases(db_session: AsyncSession) -> None:
    """Graceful shutdown safely releases active task leases back to pending so peers can execute them."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    ensure_windows_event_loop_policy()
    norm_url = normalize_postgres_connection_string(TEST_DB_URL)
    await setup_postgres_checkpointer(norm_url)

    async with AsyncPostgresSaver.from_conn_string(norm_url) as saver:
        engine = WorkflowEngine(checkpointer=saver)
        worker = WorkflowWorker(
            engine=engine,
            session_factory=session_factory,
            name="shutting-down-worker",
            worker_id="worker-shutdown-1",
        )

        task_id: uuid.UUID
        async with session_factory() as session, session.begin():
            repo = TaskRepository(session)
            t = await repo.create_task(job_id=job.id, task_type="workflow_step")
            task_id = t.id
            claimed = await worker.lease_manager.acquire_lease(session)
            assert claimed is not None
            assert claimed.status == TaskLifecycleState.RUNNING.value

        # Trigger graceful shutdown
        await worker.shutdown(timeout_seconds=2.0)
        assert worker.should_stop is True

        # In DB, the abandoned task lease was released back to PENDING!
        async with session_factory() as session:
            repo = TaskRepository(session)
            task_after = await repo.get_by_id(task_id)
            assert task_after is not None
            assert task_after.status == TaskLifecycleState.PENDING.value
            assert task_after.worker_id is None
            assert task_after.lease_expires_at is None

        # Peer worker can now claim and execute it immediately
        async with session_factory() as session, session.begin():
            repo = TaskRepository(session)
            peer_claimed = await repo.claim_next_task(worker_id="peer-worker-2")
            assert peer_claimed is not None
            assert peer_claimed.id == task_id


@pytest.mark.asyncio
async def test_langgraph_checkpoint_coordination_with_task_leases(db_session: AsyncSession) -> None:
    """Task execution resumes from LangGraph checkpoints without duplicating completed workflow steps."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    principal = await _create_test_principal(db_session)
    job = await _create_test_job(db_session, principal, status="queued")
    await db_session.commit()

    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    ensure_windows_event_loop_policy()
    norm_url = normalize_postgres_connection_string(TEST_DB_URL)
    await setup_postgres_checkpointer(norm_url)

    async with AsyncPostgresSaver.from_conn_string(norm_url) as saver:
        engine = WorkflowEngine(checkpointer=saver)
        worker1 = WorkflowWorker(
            engine=engine,
            session_factory=session_factory,
            name="worker-phase-1",
            worker_id="w-phase-1",
        )

        # 1. Create and execute Task 1 (initialization & intake up to G1 checkpoint)
        task1 = await worker1.submit_task(
            job_id=job.id,
            task_type="workflow_step",
            payload={"action": "start"},
        )
        assert task1.status == TaskLifecycleState.PENDING.value

        claimed_id = await worker1.claim_and_execute_next_task()
        assert claimed_id == task1.id

        # Verify Task 1 completed and LangGraph checkpointed at G1
        async with session_factory() as session:
            repo = TaskRepository(session)
            t1_db = await repo.get_by_id(task1.id)
            assert t1_db is not None
            assert t1_db.status == TaskLifecycleState.COMPLETED.value
            assert t1_db.result is not None
            assert t1_db.result["current_gate"] == "G1_FEASIBILITY"
            assert "intake" in t1_db.result["completed_steps"]

        await worker1.shutdown()

        # 2. Worker 2 boots up in fresh lifecycle to resume workflow via Task 2
        worker2 = WorkflowWorker(
            engine=engine,
            session_factory=session_factory,
            name="worker-phase-2",
            worker_id="w-phase-2",
        )

        task2 = await worker2.submit_task(
            job_id=job.id,
            task_type="workflow_step",
            payload={
                "action": "resume",
                "resume_payload": {"decision": "approved", "actor": "phase2_operator"},
            },
        )

        claimed_id2 = await worker2.claim_and_execute_next_task()
        assert claimed_id2 == task2.id

        # Verify Task 2 completed and LangGraph advanced to G2 without re-running intake
        async with session_factory() as session:
            repo = TaskRepository(session)
            t2_db = await repo.get_by_id(task2.id)
            assert t2_db is not None
            assert t2_db.status == TaskLifecycleState.COMPLETED.value
            assert t2_db.result is not None
            assert t2_db.result["current_gate"] == "G2_CHARACTERIZATION"
            assert "analysis" in t2_db.result["completed_steps"]
            assert t2_db.result["completed_steps"].count("intake") == 1
            assert t2_db.result["completed_steps"].count("analysis") == 1

        await worker2.shutdown()
