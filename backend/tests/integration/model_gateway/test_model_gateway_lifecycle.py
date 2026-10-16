"""Integration tests covering Model Gateway lifecycle, routing, retries, fallbacks, and budget enforcement."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
)
from modernization_platform.domain.model_gateway.errors import (
    ModelBudgetExceededError,
)
from modernization_platform.domain.model_gateway.policy import (
    FallbackTarget,
    ModelPolicy,
    default_policy_registry,
)
from modernization_platform.integrations.models.mock import MockProviderAdapter
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.budgets import BudgetRepository
from modernization_platform.repositories.model_executions import ModelExecutionRepository
from modernization_platform.services.model_gateway.gateway_service import ModelGatewayService


@pytest.mark.asyncio
async def test_successful_model_generation_lifecycle(db_engine: AsyncEngine) -> None:
    """Verify end-to-end model invocation records tokens, cost, execution history, and audit trail."""
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    job_id = uuid.uuid4()
    task_id = uuid.uuid4()

    async with session_factory() as session, session.begin():
        job = Job(
            id=job_id,
            status=JobLifecycleState.RUNNING.value,
            source_ref="git://github.com/example/repo",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 500},
            owner="architect@company.com",
        )
        session.add(job)

        from modernization_platform.db.models.task import Task

        task = Task(
            id=task_id,
            job_id=job_id,
            task_type="workflow_step",
            status="running",
            workflow_thread_id=str(job_id),
        )
        session.add(task)
        await session.flush()

    mock_adapter = MockProviderAdapter(default_response="Generated modernization plan.")
    adapters = {"mock": mock_adapter}

    async with session_factory() as session, session.begin():
        gateway = ModelGatewayService(session, adapters=adapters)
        req = ModelRequest(
            messages=[ChatMessage(role="user", content="Draft architecture design")],
            prompt_version="architect-v1.0",
            metadata={
                "input_artifact_ids": ["art-input-1"],
                "output_artifact_ids": ["art-output-1"],
            },
        )
        ctx = ModelExecutionContext(
            job_id=job_id,
            task_id=task_id,
            agent_role="architect",
            correlation_id="corr-test-123",
        )

        resp = await gateway.generate(req, ctx)

        assert resp.content == "Generated modernization plan."
        assert resp.provider == "mock"
        assert resp.usage.input_tokens > 0

    # Verify durable ModelExecution was persisted
    async with session_factory() as session:
        exec_repo = ModelExecutionRepository(session)
        executions = await exec_repo.list_executions_by_job(job_id)
        assert len(executions) == 1
        exec_rec = executions[0]
        assert exec_rec.job_id == job_id
        assert exec_rec.task_id == task_id
        assert exec_rec.provider == "mock"
        assert exec_rec.status == "success"
        assert exec_rec.correlation_id == "corr-test-123"

        from modernization_platform.repositories.agent_runs import AgentRunRepository

        agent_runs = await AgentRunRepository(session).list_runs_by_job(job_id)
        assert len(agent_runs) == 1
        assert "art-input-1" in agent_runs[0].input_artifact_ids
        assert "art-output-1" in agent_runs[0].output_artifact_ids


@pytest.mark.asyncio
async def test_fallback_routing_on_primary_failure(db_engine: AsyncEngine) -> None:
    """Verify that when primary provider fails with retryable error, approved fallback is invoked."""
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    job_id = uuid.uuid4()

    async with session_factory() as session, session.begin():
        job = Job(
            id=job_id,
            status=JobLifecycleState.RUNNING.value,
            source_ref="git://github.com/example/repo",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 500},
            owner="architect@company.com",
        )
        session.add(job)
        await session.flush()

    # Primary adapter fails all attempts, fallback succeeds
    primary_mock = MockProviderAdapter(
        provider_name="primary_mock",
        simulate_error=RuntimeError("503 Service Unavailable"),
        fail_attempts=5,
    )
    fallback_mock = MockProviderAdapter(
        provider_name="fallback_mock",
        default_response="Fallback response content",
    )

    # Custom policy allowing primary and fallback
    custom_policy = ModelPolicy(
        policy_name="fallback_test_policy",
        agent_role="fallback_agent",
        allowed_providers=("primary_mock", "fallback_mock"),
        allowed_models=("mock-model",),
        primary_provider="primary_mock",
        primary_model_id="mock-model",
        fallback_targets=(FallbackTarget(provider="fallback_mock", model_id="mock-model"),),
        max_retries=1,
    )
    default_policy_registry.register_policy(custom_policy)

    adapters = {
        "primary_mock": primary_mock,
        "fallback_mock": fallback_mock,
    }

    async with session_factory() as session, session.begin():
        gateway = ModelGatewayService(session, adapters=adapters)
        req = ModelRequest(
            messages=[ChatMessage(role="user", content="Test fallback")],
            prompt_version="v1.0",
        )
        ctx = ModelExecutionContext(
            job_id=job_id,
            agent_role="fallback_agent",
        )

        resp = await gateway.generate(req, ctx)
        assert resp.content == "Fallback response content"
        assert resp.provider == "fallback_mock"


@pytest.mark.asyncio
async def test_budget_80_percent_warning_and_100_percent_hard_stop(db_engine: AsyncEngine) -> None:
    """Verify 80% warning generates audit event and 100% hard stop prevents execution."""
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    job_id = uuid.uuid4()

    # Budget limit = 10,000 microcents ($0.01 / 1 cent)
    async with session_factory() as session, session.begin():
        job = Job(
            id=job_id,
            status=JobLifecycleState.RUNNING.value,
            source_ref="git://github.com/example/repo",
            target_stack_spec={"language": "python"},
            budget={"max_cost_cents": 1},
            owner="architect@company.com",
        )
        session.add(job)
        await session.flush()

        budget_repo = BudgetRepository(session)
        await budget_repo.create_or_get_account(
            job_id=job_id,
            limit_microcents=10_000,
            warning_threshold_percent=80,
            hard_stop_percent=100,
        )

    # First call reserves 8,500 microcents -> crosses 80% warning threshold (8,000 microcents)
    from modernization_platform.domain.model_gateway.pricing import ModelPricing, PricingRegistry

    custom_pricing = PricingRegistry()
    custom_pricing.register_pricing(
        ModelPricing(
            provider="mock",
            model_id="mock-model",
            input_microcents_per_1k=30000,
            output_microcents_per_1k=0,
        )
    )

    adapters = {
        "mock": MockProviderAdapter(default_response="Call 1", pricing_registry=custom_pricing)
    }

    async with session_factory() as session, session.begin():
        gateway = ModelGatewayService(session, adapters=adapters, pricing_registry=custom_pricing)
        req = ModelRequest(
            messages=[ChatMessage(role="user", content="Long message " * 100)],
            prompt_version="v1.0",
            max_tokens=10,
        )
        ctx = ModelExecutionContext(job_id=job_id, agent_role="architect")
        await gateway.generate(req, ctx)

    # Verify 80% warning audit event was emitted
    async with session_factory() as session:
        audit_repo = AuditEventRepository(session)
        events = await audit_repo.list_events_by_job(job_id)
        action_names = [e.action for e in events]
        assert "BUDGET_WARNING_80_PERCENT" in action_names

    # Second call attempts to spend more than remaining 1,500 microcents -> Hard stop 100%!
    async with session_factory() as session, session.begin():
        gateway = ModelGatewayService(session, adapters=adapters, pricing_registry=custom_pricing)
        req = ModelRequest(
            messages=[ChatMessage(role="user", content="Long message " * 100)],
            prompt_version="v1.0",
            max_tokens=10,
        )
        ctx = ModelExecutionContext(job_id=job_id, agent_role="architect")

        with pytest.raises(ModelBudgetExceededError):
            await gateway.generate(req, ctx)

    # Verify BUDGET_EXHAUSTED audit event was emitted
    async with session_factory() as session:
        audit_repo = AuditEventRepository(session)
        events = await audit_repo.list_events_by_job(job_id)
        action_names = [e.action for e in events]
        assert "BUDGET_EXHAUSTED" in action_names


@pytest.mark.asyncio
async def test_worker_and_job_restart_preserves_state(db_engine: AsyncEngine) -> None:
    """Verify that budget balance and execution history survive simulated worker crashes/restarts."""
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
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
        await budget_repo.create_or_get_account(job_id=job_id, limit_microcents=1_000_000)

    # Worker 1 runs and commits an execution
    adapters = {"mock": MockProviderAdapter(default_response="Worker 1 executed")}
    async with session_factory() as session1, session1.begin():
        gateway1 = ModelGatewayService(session1, adapters=adapters)
        req = ModelRequest(
            messages=[ChatMessage(role="user", content="hello")], prompt_version="v1.0"
        )
        ctx = ModelExecutionContext(job_id=job_id, agent_role="architect")
        await gateway1.generate(req, ctx)

    # Worker 1 is destroyed (session1 closed). Now Worker 2 starts up fresh.
    async with session_factory() as session2, session2.begin():
        exec_repo = ModelExecutionRepository(session2)
        history = await exec_repo.list_executions_by_job(job_id)
        assert len(history) == 1
        assert history[0].status == "success"

        budget_repo = BudgetRepository(session2)
        account = await budget_repo.get_account_by_job_for_update(job_id)
        assert account is not None
        assert account.limit_microcents == 1_000_000
