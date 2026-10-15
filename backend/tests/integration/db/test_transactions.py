"""PostgreSQL integration tests verifying transaction atomicity, boundaries, and failure rollback."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modernization_platform.core.exceptions import PersistenceError
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.module import Module
from modernization_platform.db.session import transactional_session


@pytest.mark.asyncio
async def test_atomic_multi_record_transaction_success(db_engine: AsyncEngine) -> None:
    """Verify that multiple related records commit atomically in a single transaction."""
    job_id = uuid.uuid4()
    module_id = uuid.uuid4()

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with transactional_session(db_engine) as session:
        job = Job(
            id=job_id,
            owner="transaction-test",
            source_ref="https://example.invalid/legacy/atomic-success.git",
        )
        session.add(job)
        await session.flush()

        module = Module(
            id=module_id,
            job_id=job.id,
            name="Atomic Module",
            legacy_paths=["legacy/atomic.cob"],
        )
        session.add(module)

    # In a new session, verify both records are persisted
    async with session_factory() as session:
        persisted_job = await session.get(Job, job_id)
        persisted_module = await session.get(Module, module_id)
        assert persisted_job is not None
        assert persisted_module is not None
        assert persisted_module.job_id == persisted_job.id


@pytest.mark.asyncio
async def test_atomic_multi_record_transaction_rollback_leaves_no_partial_state(
    db_engine: AsyncEngine,
) -> None:
    """Verify that if an operation fails midway, all prior writes in the transaction are rolled back."""
    job_id = uuid.uuid4()
    module_id = uuid.uuid4()

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    with pytest.raises(
        PersistenceError,
        match="Simulated business logic failure during modernization",
    ):
        async with transactional_session(db_engine) as session:
            job = Job(
                id=job_id,
                owner="transaction-test",
                source_ref="https://example.invalid/legacy/atomic-rollback.git",
            )
            session.add(job)
            await session.flush()

            module = Module(
                id=module_id,
                job_id=job.id,
                name="Uncommitted Module",
                legacy_paths=["legacy/uncommitted.cob"],
            )
            session.add(module)
            await session.flush()

            # Simulate unexpected failure before commit
            raise ValueError("Simulated business logic failure during modernization")

    # In a new session, verify neither record exists (0 partial state)
    async with session_factory() as session:
        job_check = await session.execute(select(Job).where(Job.id == job_id))
        assert job_check.scalar_one_or_none() is None

        module_check = await session.execute(select(Module).where(Module.id == module_id))
        assert module_check.scalar_one_or_none() is None
