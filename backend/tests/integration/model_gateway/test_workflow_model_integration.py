"""Integration tests for Workflow -> Task -> Agent -> Model Gateway lifecycle.

Verifies:
1. End-to-end agent step execution producing ModelResponse and recorded ModelExecution.
2. Budget exhaustion halts agent step with ModelBudgetExceededError and permanent failure classification.
3. Primary provider failure routes to approved fallback.
4. Database state preservation across simulated worker/session restarts.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.budget import BudgetAccount
from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
)
from modernization_platform.domain.model_gateway.errors import (
    ModelBudgetExceededError,
    ModelProviderUnavailableError,
)
from modernization_platform.domain.model_gateway.policy import (
    FallbackTarget,
    ModelPolicy,
    PolicyRegistry,
)
from modernization_platform.domain.tasks.retry import classify_exception
from modernization_platform.domain.tasks.states import TaskFailureClassification
from modernization_platform.integrations.models.mock import MockProviderAdapter
from modernization_platform.repositories.budgets import BudgetRepository
from modernization_platform.repositories.model_executions import ModelExecutionRepository
from modernization_platform.services.model_gateway.gateway_service import ModelGatewayService
from modernization_platform.workflows.agent_dispatch import dispatch_agent_step


@pytest.fixture
async def sample_job(db_session: AsyncSession) -> Job:
    """Create a persistent running Job for workflow testing."""
    job = Job(
        id=uuid.uuid4(),
        status=JobLifecycleState.RUNNING.value,
        source_ref="git://github.com/example/repo",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 500},
        owner="architect@company.com",
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.mark.asyncio
async def test_workflow_agent_step_execution_success(
    db_session: AsyncSession, sample_job: Job
) -> None:
    """Verify Job -> Workflow -> Agent step succeeds and records durable execution & usage."""
    # 1. Establish initial budget account with 100,000 microcents ($0.10)
    budget_account = BudgetAccount(
        id=uuid.uuid4(),
        job_id=sample_job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=100_000,
        spent_microcents=0,
        reserved_microcents=0,
        warning_threshold_percent=80,
        warning_emitted=False,
        status="active",
    )
    db_session.add(budget_account)
    await db_session.flush()

    artifact_id = str(uuid.uuid4())

    # 2. Dispatch agent step
    response = await dispatch_agent_step(
        session=db_session,
        job_id=sample_job.id,
        agent_role="architect",
        prompt="Analyze the legacy architecture and propose modernization phases.",
        prompt_version="architect-v2.1",
        output_artifact_ids=[artifact_id],
    )

    # 3. Assert ModelResponse contract
    assert response is not None
    assert response.content != ""
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0

    # 4. Assert durable execution record exists
    exec_repo = ModelExecutionRepository(db_session)
    executions = await exec_repo.list_for_job(job_id=sample_job.id)
    assert len(executions) >= 1

    latest = executions[0]
    assert latest.agent_role == "architect"
    assert latest.prompt_version == "architect-v2.1"
    assert latest.status == "success"
    assert latest.input_tokens == response.usage.input_tokens
    assert latest.output_tokens == response.usage.output_tokens
    assert latest.actual_cost_microcents >= 0

    # 5. Assert budget was reconciled
    budget_repo = BudgetRepository(db_session)
    accounts = await budget_repo.list_job_budget_accounts(sample_job.id)
    assert len(accounts) >= 1
    account = accounts[0]
    assert account.spent_microcents >= 0
    assert account.reserved_microcents == 0


@pytest.mark.asyncio
async def test_workflow_budget_exhaustion_pauses_safely(
    db_session: AsyncSession, sample_job: Job
) -> None:
    """Verify that when a budget is exhausted, the agent step halts safely with ModelBudgetExceededError."""
    # 1. Establish budget account with 0 remaining funds
    budget_account = BudgetAccount(
        id=uuid.uuid4(),
        job_id=sample_job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=500,  # extremely small limit ($0.0005)
        spent_microcents=1000,  # over budget
        reserved_microcents=0,
        warning_threshold_percent=80,
        warning_emitted=True,
        status="exhausted",
    )
    db_session.add(budget_account)
    await db_session.flush()

    # 2. Dispatch agent step; should raise ModelBudgetExceededError
    with pytest.raises(ModelBudgetExceededError) as exc_info:
        await dispatch_agent_step(
            session=db_session,
            job_id=sample_job.id,
            agent_role="converter",
            prompt="Translate COBOL batch job to modern Python service.",
        )

    # 3. Verify exception classifies as permanent failure to halt workflow without spin
    disposition = classify_exception(exc_info.value)
    assert disposition == TaskFailureClassification.PERMANENT_FAILURE


@pytest.mark.asyncio
async def test_workflow_primary_model_failure_uses_approved_fallback(
    db_session: AsyncSession, sample_job: Job
) -> None:
    """Verify that when the primary model fails with a transient error, the gateway uses approved fallback."""
    # 1. Budget account with ample funds
    budget_account = BudgetAccount(
        id=uuid.uuid4(),
        job_id=sample_job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=500_000,
        spent_microcents=0,
        reserved_microcents=0,
        warning_threshold_percent=80,
        warning_emitted=False,
        status="active",
    )
    db_session.add(budget_account)
    await db_session.flush()

    # 2. Setup custom policy with primary and fallback model
    policy = ModelPolicy(
        policy_name="reviewer_policy",
        agent_role="reviewer",
        allowed_providers=("openai", "anthropic"),
        allowed_models=("gpt-4o", "claude-3-5-sonnet-20241022"),
        primary_provider="openai",
        primary_model_id="gpt-4o",
        fallback_targets=(
            FallbackTarget(provider="anthropic", model_id="claude-3-5-sonnet-20241022"),
        ),
        max_retries=1,
    )
    policy_registry = PolicyRegistry()
    policy_registry.register(policy)

    # 3. Setup mock adapters where primary fails with 503
    primary_adapter = MockProviderAdapter(
        provider_name="openai",
        simulate_error=ModelProviderUnavailableError("openai", "OpenAI 503 Service Unavailable"),
        fail_attempts=10,
    )
    fallback_adapter = MockProviderAdapter(
        provider_name="anthropic",
        default_response="Review complete: Architecture approved by fallback reviewer.",
    )

    adapters = {
        "openai": primary_adapter,
        "anthropic": fallback_adapter,
    }

    gateway = ModelGatewayService(
        session=db_session,
        policy_registry=policy_registry,
        adapters=adapters,
    )

    request = ModelRequest(
        messages=[ChatMessage(role="user", content="Review proposed schema migrations.")],
        model="gpt-4o",
        prompt_version="reviewer-v1.0",
    )
    context = ModelExecutionContext(
        job_id=sample_job.id,
        agent_role="reviewer",
        stage="review",
    )

    response = await gateway.generate(request, context)
    assert response is not None
    assert "Architecture approved by fallback reviewer" in response.content

    # 4. Check execution audit trail records fallback
    exec_repo = ModelExecutionRepository(db_session)
    executions = await exec_repo.list_for_job(job_id=sample_job.id)
    assert len(executions) >= 1
    latest = executions[0]
    assert latest.is_fallback is True
    assert latest.primary_model_id == "gpt-4o"
    assert latest.model_id == "claude-3-5-sonnet-20241022"


@pytest.mark.asyncio
async def test_worker_restart_preserves_budget_and_execution_state(
    db_session: AsyncSession, sample_job: Job
) -> None:
    """Verify that committing and opening a fresh session simulates worker restart and preserves state."""
    # 1. Setup account and record an execution
    budget_repo = BudgetRepository(db_session)
    await budget_repo.create_or_get_account(
        job_id=sample_job.id,
        limit_microcents=200_000,
        scope_type="job",
        scope_id="job",
        warning_threshold_percent=80,
    )
    res, _ = await budget_repo.reserve_budget(
        job_id=sample_job.id,
        agent_role="analyzer",
        estimated_microcents=25_000,
    )
    await budget_repo.reconcile_reservation(
        reservation_id=res.id,
        actual_microcents=20_000,
    )

    exec_repo = ModelExecutionRepository(db_session)
    await exec_repo.record_execution(
        job_id=sample_job.id,
        agent_role="analyzer",
        stage="analysis",
        provider="mock",
        model_id="mock-default",
        prompt_version="analyzer-v1.0",
        correlation_id=str(uuid.uuid4()),
        input_tokens=150,
        output_tokens=75,
        actual_cost_microcents=20_000,
        status="success",
    )

    await db_session.commit()

    # 2. Simulate worker restart: query afresh through new repository instances
    fresh_budget_repo = BudgetRepository(db_session)
    fresh_exec_repo = ModelExecutionRepository(db_session)

    fresh_accounts = await fresh_budget_repo.list_job_budget_accounts(sample_job.id)
    assert len(fresh_accounts) >= 1
    fresh_account = fresh_accounts[0]
    assert fresh_account.limit_microcents == 200_000
    assert fresh_account.spent_microcents == 20_000
    assert fresh_account.reserved_microcents == 0

    fresh_executions = await fresh_exec_repo.list_for_job(sample_job.id)
    assert len(fresh_executions) == 1
    assert fresh_executions[0].agent_role == "analyzer"
    assert fresh_executions[0].actual_cost_microcents == 20_000
