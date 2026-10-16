"""Sub-Phase 01.12 — Budget Limits, Warnings, and Provider Failure Recovery E2E Validation.

Validates Section 10 & Section 11:
1. Below 80%: Invocations succeed without warnings.
2. At/above 80%: Warning emitted exactly once.
3. Subsequent requests >80%: Do not re-emit warning.
4. Hard cap at 100%: Invocations strictly rejected with ModelBudgetExceededError BEFORE calling provider.
5. Provider failure: Reserved budget is reconciled to 0 and released without leakage.
6. Fallback execution: Primary failure automatically routes to approved fallback within the single reservation.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.budget import BudgetAccount
from modernization_platform.db.models.identity import (
    Tenant,
    TenantMembership,
    UserAccount,
)
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
from modernization_platform.domain.model_gateway.pricing import (
    ModelPricing,
    default_pricing_registry,
)
from modernization_platform.integrations.models.mock import MockProviderAdapter
from modernization_platform.repositories.budgets import BudgetRepository
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.model_gateway.gateway_service import (
    ModelGatewayService,
)


async def _create_test_identity(
    session: AsyncSession,
    *,
    tenant: Tenant,
    role: Role,
    subject: str,
) -> tuple[UserAccount, TenantMembership, AuthenticatedPrincipal]:
    user = UserAccount(
        issuer="https://auth.modernization.internal",
        subject=subject,
        display_name=subject.capitalize(),
        active=True,
    )
    session.add(user)
    await session.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role=role.value,
        active=True,
    )
    session.add(membership)
    await session.flush()

    principal = AuthenticatedPrincipal(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        session_id=uuid.uuid4(),
        subject=subject,
        issuer=user.issuer,
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=2),
        authentication_method="oidc_jwt",
    )
    return user, membership, principal


@pytest.mark.asyncio
async def test_budget_80_percent_warning_once_and_100_percent_hard_stop(
    db_session: AsyncSession,
) -> None:
    """Validate 80% threshold warning is emitted exactly once and 100% cap halts requests."""
    tenant = Tenant(
        id=uuid.uuid4(),
        slug="budget-test-corp",
        display_name="Budget Test Corp",
        active=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    _user, _mem, owner_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="budget-owner"
    )

    job = Job(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        owner=str(owner_principal.user_id),
        owner_user_id=owner_principal.user_id,
        status=JobLifecycleState.RUNNING.value,
        source_ref="https://git.company.test/repo.git",
        target_stack_spec={"lang": "python"},
        budget={"max_cost_cents": 10},
    )
    db_session.add(job)
    await db_session.flush()

    # Limit = 100,000 microcents ($0.10). 80% threshold = 80,000 microcents.
    budget_repo = BudgetRepository(db_session)
    account = BudgetAccount(
        id=uuid.uuid4(),
        job_id=job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=100_000,
        spent_microcents=0,
        reserved_microcents=0,
        warning_threshold_percent=80,
        warning_emitted=False,
        status="active",
    )
    db_session.add(account)
    await db_session.flush()

    # 1. Spend 70,000 microcents (70%): Below warning threshold
    res1, should_warn1 = await budget_repo.reserve_budget(
        job_id=job.id,
        agent_role="architect",
        scope_type="job",
        scope_id="job",
        estimated_microcents=70_000,
    )
    assert should_warn1 is False
    await budget_repo.reconcile_reservation(
        reservation_id=res1.id,
        actual_microcents=70_000,
    )
    await db_session.commit()

    reloaded_acct = await budget_repo.get_account_by_job_for_update(job_id=job.id)
    assert reloaded_acct is not None
    assert reloaded_acct.spent_microcents == 70_000
    assert reloaded_acct.warning_emitted is False

    # 2. Spend 15,000 microcents: Total becomes 85,000 (85% > 80%): Warning emitted once!
    res2, should_warn2 = await budget_repo.reserve_budget(
        job_id=job.id,
        agent_role="architect",
        scope_type="job",
        scope_id="job",
        estimated_microcents=15_000,
    )
    assert should_warn2 is True
    await budget_repo.reconcile_reservation(
        reservation_id=res2.id,
        actual_microcents=15_000,
    )
    await db_session.commit()

    reloaded_acct = await budget_repo.get_account_by_job_for_update(job_id=job.id)
    assert reloaded_acct is not None
    assert reloaded_acct.spent_microcents == 85_000
    assert reloaded_acct.warning_emitted is True

    # 3. Spend 5,000 microcents: Total becomes 90,000: Warning NOT emitted again
    res3, should_warn3 = await budget_repo.reserve_budget(
        job_id=job.id,
        agent_role="architect",
        scope_type="job",
        scope_id="job",
        estimated_microcents=5_000,
    )
    assert should_warn3 is False
    await budget_repo.reconcile_reservation(
        reservation_id=res3.id,
        actual_microcents=5_000,
    )
    await db_session.commit()

    reloaded_acct = await budget_repo.get_account_by_job_for_update(job_id=job.id)
    assert reloaded_acct is not None
    assert reloaded_acct.spent_microcents == 90_000

    # 4. Attempt to spend 20,000 microcents: Exceeds 100,000 hard stop!
    with pytest.raises(ModelBudgetExceededError):
        await budget_repo.reserve_budget(
            job_id=job.id,
            agent_role="architect",
            scope_type="job",
            scope_id="job",
            estimated_microcents=20_000,
        )

    # Verify no dangling reservation was left
    reloaded_acct = await budget_repo.get_account_by_job_for_update(job_id=job.id)
    assert reloaded_acct is not None
    assert reloaded_acct.reserved_microcents == 0
    assert reloaded_acct.spent_microcents == 90_000


@pytest.mark.asyncio
async def test_provider_failure_reservation_refund_and_fallback(
    db_session: AsyncSession,
) -> None:
    """Validate that provider failure safely refunds reserved budget, and fallback routes inside budget."""
    tenant = Tenant(
        id=uuid.uuid4(),
        slug="fallback-corp",
        display_name="Fallback Corp",
        active=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    _user, _mem, owner_principal = await _create_test_identity(
        db_session, tenant=tenant, role=Role.OWNER, subject="dev-lead"
    )

    job = Job(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        owner=str(owner_principal.user_id),
        owner_user_id=owner_principal.user_id,
        status=JobLifecycleState.RUNNING.value,
        source_ref="https://git.company.test/repo.git",
        target_stack_spec={"lang": "python"},
        budget={"max_cost_cents": 500},
    )
    db_session.add(job)
    await db_session.flush()

    budget_repo = BudgetRepository(db_session)
    account = BudgetAccount(
        id=uuid.uuid4(),
        job_id=job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=500_000,
        spent_microcents=0,
        reserved_microcents=0,
        warning_threshold_percent=80,
        warning_emitted=False,
        status="active",
    )
    db_session.add(account)
    await db_session.flush()

    # 1. Primary provider fails with simulated 503 Service Unavailable
    primary_mock = MockProviderAdapter(
        provider_name="primary-mock",
        default_model="primary-model",
        simulate_error=ModelProviderUnavailableError(provider="primary-mock", reason="503 Outage"),
        fail_attempts=10,
    )
    fallback_mock = MockProviderAdapter(
        provider_name="fallback-mock",
        default_model="fallback-model",
        default_response="Response from fallback provider",
    )

    # Register test pricing for fallback
    default_pricing_registry.register_pricing(
        ModelPricing(
            provider="fallback-mock",
            model_id="fallback-model",
            input_microcents_per_1k=100,
            output_microcents_per_1k=200,
        )
    )

    # Policy configuring fallback from primary-mock to fallback-mock
    policy_registry = PolicyRegistry()
    policy_registry.register(
        ModelPolicy(
            policy_name="architect-fallback-policy",
            agent_role="architect",
            allowed_providers=("primary-mock", "fallback-mock"),
            allowed_models=("primary-model", "fallback-model"),
            primary_provider="primary-mock",
            primary_model_id="primary-model",
            fallback_targets=(FallbackTarget(provider="fallback-mock", model_id="fallback-model"),),
        )
    )

    gateway = ModelGatewayService(
        session=db_session,
        adapters={"primary-mock": primary_mock, "fallback-mock": fallback_mock},
        policy_registry=policy_registry,
    )

    context = ModelExecutionContext(
        job_id=job.id,
        agent_role="architect",
        stage="analysis",
    )
    request = ModelRequest(
        messages=[ChatMessage(role="user", content="Test fallback routing.")],
        prompt_version="test-v1",
    )

    response = await gateway.generate(request=request, context=context)

    # Assert fallback provider handled the request successfully
    assert response is not None
    assert response.provider == "fallback-mock"
    assert response.model_id == "fallback-model"
    assert response.content == "Response from fallback provider"

    # Assert budget reconciled accurately with no dangling reservation
    reloaded_acct = await budget_repo.get_account_by_job_for_update(job_id=job.id)
    assert reloaded_acct is not None
    assert reloaded_acct.reserved_microcents == 0
    assert reloaded_acct.spent_microcents > 0
