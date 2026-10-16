"""Integration tests for Model Gateway REST API endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.repositories.budgets import BudgetRepository
from modernization_platform.security.dependencies import get_current_principal
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal


def _principal(role: Role = Role.OWNER) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-owner",
        issuer="https://auth.modernization.internal",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.mark.asyncio
async def test_generate_model_completion_api(
    app: FastAPI,
    db_session: AsyncSession,
) -> None:
    """Verify POST /api/v1/jobs/{job_id}/models/generate executes under policy and records spend."""
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        status=JobLifecycleState.RUNNING.value,
        source_ref="git://github.com/example/repo",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 500},
        owner="developer@company.com",
    )
    db_session.add(job)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "agent_role": "architect",
            "messages": [{"role": "user", "content": "Generate architecture blueprint"}],
            "prompt_version": "architect-v1.0",
            "max_tokens": 100,
        }
        res = await client.post(
            f"/api/v1/jobs/{job_id}/models/generate",
            json=payload,
            headers={"X-Correlation-ID": "test-corr-id-123"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "content" in data
        assert data["provider"] in ["mock", "openai", "anthropic", "qwen"]
        assert data["input_tokens"] > 0
        assert "cost_cents" in data


@pytest.mark.asyncio
async def test_list_job_budgets_api(
    app: FastAPI,
    db_session: AsyncSession,
) -> None:
    """Verify GET /api/v1/jobs/{job_id}/budgets returns active and reserved budget tracking."""
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        status=JobLifecycleState.RUNNING.value,
        source_ref="git://github.com/example/repo",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 500},
        owner="developer@company.com",
    )
    db_session.add(job)
    await db_session.flush()

    budget_repo = BudgetRepository(db_session)
    await budget_repo.create_or_get_account(job_id=job_id, limit_microcents=2_000_000)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get(f"/api/v1/jobs/{job_id}/budgets")
        assert res.status_code == 200
        budgets = res.json()
        assert len(budgets) >= 1
        assert budgets[0]["job_id"] == str(job_id)
        assert budgets[0]["limit_microcents"] == 2_000_000
        assert budgets[0]["limit_cents"] == 200.0


@pytest.mark.asyncio
async def test_list_model_executions_and_metrics_api(
    app: FastAPI,
    db_session: AsyncSession,
) -> None:
    """Verify GET /api/v1/jobs/{job_id}/models/executions and GET /api/v1/models/metrics."""
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: db_session

    job_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Check executions
        res_exec = await client.get(f"/api/v1/jobs/{job_id}/models/executions")
        assert res_exec.status_code == 200
        assert isinstance(res_exec.json(), list)

        # Check metrics
        res_metrics = await client.get("/api/v1/models/metrics")
        assert res_metrics.status_code == 200
        metrics_data = res_metrics.json()
        assert "model_calls_total" in metrics_data
        assert "model_cost_microcents_total" in metrics_data
