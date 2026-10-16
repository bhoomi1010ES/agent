"""Concurrency and race protection tests for durable budget reservations."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.model_gateway.errors import (
    ModelBudgetExceededError,
)
from modernization_platform.repositories.budgets import BudgetRepository
from modernization_platform.services.model_gateway.budget_service import BudgetService


@pytest.mark.asyncio
async def test_budget_reservation_race_protection(db_engine: AsyncEngine) -> None:
    """Verify concurrent workers cannot race to exceed the configured hard budget limit.

    Scenario:
    Budget = $1.00 (1,000,000 microcents)
    Worker A estimates $0.70 (700,000 microcents)
    Worker B estimates $0.70 (700,000 microcents)

    Result:
    Exactly one worker succeeds. The other must raise ModelBudgetExceededError.
    Total committed reservation must not exceed $1.00.
    """
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    job_id = uuid.uuid4()

    # 1. Initialize parent Job and $1.00 budget account
    async with session_factory() as session, session.begin():
        job = Job(
            id=job_id,
            status=JobLifecycleState.RUNNING.value,
            source_ref="git://github.com/example/repo",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 100},
            owner="architect@company.com",
        )
        session.add(job)
        await session.flush()

        budget_repo = BudgetRepository(session)
        await budget_repo.create_or_get_account(
            job_id=job_id,
            scope_type="job",
            scope_id="job",
            limit_microcents=1_000_000,  # $1.00
            warning_threshold_percent=80,
            hard_stop_percent=100,
        )

    # 2. Worker reservation coroutines
    async def worker_reserve(worker_name: str, estimated_microcents: int) -> dict[str, Any]:
        try:
            async with session_factory() as worker_session, worker_session.begin():
                service = BudgetService(worker_session)
                res = await service.reserve_budget(
                    job_id=job_id,
                    agent_role=worker_name,
                    estimated_microcents=estimated_microcents,
                )
                return {"worker": worker_name, "success": True, "reservation_id": res.id}
        except ModelBudgetExceededError as exc:
            return {"worker": worker_name, "success": False, "error": exc}

    # 3. Launch simultaneous reservations
    task_a = worker_reserve("WorkerA", 700_000)
    task_b = worker_reserve("WorkerB", 700_000)

    results = await asyncio.gather(task_a, task_b)

    # 4. Assert mutual exclusion
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got: {results}"
    assert isinstance(failures[0]["error"], ModelBudgetExceededError)

    # 5. Verify final state in database
    async with session_factory() as session:
        budget_repo = BudgetRepository(session)
        account = await budget_repo.get_account_by_job_for_update(job_id)
        assert account is not None
        assert account.reserved_microcents == 700_000
        assert account.spent_microcents == 0
        assert account.reserved_microcents <= account.limit_microcents


@pytest.mark.asyncio
async def test_budget_reservation_and_release_concurrency(db_engine: AsyncEngine) -> None:
    """Verify that releasing a reservation restores available budget for subsequent reservations."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    job_id = uuid.uuid4()

    async with session_factory() as session, session.begin():
        job = Job(
            id=job_id,
            status=JobLifecycleState.RUNNING.value,
            source_ref="git://github.com/example/repo",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 100},
            owner="architect@company.com",
        )
        session.add(job)
        await session.flush()

        budget_repo = BudgetRepository(session)
        await budget_repo.create_or_get_account(
            job_id=job_id,
            scope_type="job",
            scope_id="job",
            limit_microcents=1_000_000,
            warning_threshold_percent=80,
            hard_stop_percent=100,
        )

    # Reserve 900,000 microcents
    res_id: uuid.UUID
    async with session_factory() as session, session.begin():
        service = BudgetService(session)
        res = await service.reserve_budget(
            job_id=job_id,
            agent_role="Worker1",
            estimated_microcents=900_000,
        )
        res_id = res.id

    # Another worker attempting 200,000 must fail
    with pytest.raises(ModelBudgetExceededError):
        async with session_factory() as session, session.begin():
            service = BudgetService(session)
            await service.reserve_budget(
                job_id=job_id,
                agent_role="Worker2",
                estimated_microcents=200_000,
            )

    # Worker1 releases reservation
    async with session_factory() as session, session.begin():
        service = BudgetService(session)
        await service.release_reservation(res_id, reason="cancelled")

    # Worker2 now succeeds
    async with session_factory() as session, session.begin():
        service = BudgetService(session)
        res2 = await service.reserve_budget(
            job_id=job_id,
            agent_role="Worker2",
            estimated_microcents=200_000,
        )
        assert res2 is not None
        assert res2.reserved_microcents == 200_000
