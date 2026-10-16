"""Integration API tests for Job lifecycle and state machine endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.db.models.job import Job
from modernization_platform.db.session import get_db_session
from modernization_platform.security.dependencies import get_current_principal
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal


def _principal(
    role: Role = Role.OWNER,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="test-architect",
        issuer="https://auth.modernization.internal",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="oidc_jwt",
    )


@pytest.fixture
def mock_db_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_job_success(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/jobs",
                json={
                    "source_repository": "https://github.com/acme/legacy-monolith",
                    "source_revision": "v1.2.3",
                    "target_stack": {
                        "language": "python",
                        "framework": "fastapi",
                        "database": "postgresql",
                    },
                    "budget": {
                        "max_cost_cents": 50000,
                        "max_repair_attempts": 3,
                    },
                },
                headers={"X-Correlation-ID": "corr-create-001"},
            )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["status"] in ("queued", "pending")
        assert data["version"] == 1
        assert "created_at" in data
        mock_db_session.commit.assert_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_job_with_idempotency_key(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    idem_key = "idemp-" + str(uuid.uuid4())
    payload = {
        "source_repository": "https://github.com/acme/legacy-monolith",
        "source_revision": "v1.2.3",
        "target_stack": {"language": "python"},
        "budget": {"max_cost_cents": 50000},
    }

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # First attempt: no existing idempotency record found
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = None
            mock_db_session.execute.return_value = mock_res

            resp1 = await client.post(
                "/api/v1/jobs",
                json=payload,
                headers={"Idempotency-Key": idem_key},
            )
            assert resp1.status_code == 201

            # Second attempt with cached record
            from modernization_platform.db.models.idempotency import IdempotencyRecord

            added_idem = next(
                call[0][0]
                for call in mock_db_session.add.call_args_list
                if isinstance(call[0][0], IdempotencyRecord)
            )

            cached_record = MagicMock()
            cached_record.request_hash = added_idem.request_hash
            cached_record.status_code = 201
            cached_record.response_body = resp1.json()
            cached_record.resource_id = added_idem.resource_id

            mock_res_cached = MagicMock()
            mock_res_cached.scalar_one_or_none.return_value = cached_record

            mock_res_job = MagicMock()
            mock_res_job.scalar_one_or_none.return_value = Job(
                id=added_idem.resource_id,
                owner=str(principal.user_id),
                owner_user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                status="queued",
                version=1,
                source_ref="https://github.com/acme/legacy-monolith@v1.2.3",
                target_stack_spec={"language": "python"},
                budget={"max_cost_cents": 50000},
            )
            mock_db_session.execute.side_effect = [mock_res_cached, mock_res_job]

            resp2 = await client.post(
                "/api/v1/jobs",
                json=payload,
                headers={"Idempotency-Key": idem_key},
            )
            assert resp2.status_code == 201
            assert resp2.json()["job_id"] == resp1.json()["job_id"]

            # Third attempt with mismatched request hash -> 409
            mock_db_session.execute.side_effect = None
            mock_db_session.execute.return_value = mock_res_cached
            mismatched_payload = {
                "source_repository": "https://github.com/acme/other-monolith",
                "source_revision": "v2.0.0",
                "target_stack": {"language": "python"},
                "budget": {"max_cost_cents": 10000},
            }
            resp3 = await client.post(
                "/api/v1/jobs",
                json=mismatched_payload,
                headers={"Idempotency-Key": idem_key},
            )
            assert resp3.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_job_status_endpoint(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        current_stage="analysis",
        version=2,
        source_ref="https://github.com/acme/legacy@main",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
        started_at=datetime.now(UTC),
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = job
    mock_db_session.execute.return_value = mock_res

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/jobs/{job_id}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == str(job_id)
        assert data["status"] == "running"
        assert data["current_stage"] == "analysis"
        assert data["version"] == 2
        assert data["needs_human"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pause_and_resume_job_lifecycle(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="running",
        version=1,
        source_ref="https://github.com/acme/legacy@main",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )

    # First mock: query with_for_update returns running job (version 1)
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = job
    mock_db_session.execute.return_value = mock_res

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Pause job
            pause_resp = await client.post(
                f"/api/v1/jobs/{job_id}/pause",
                json={"expected_version": 1, "reason": "Operator requested pause"},
            )
            assert pause_resp.status_code == 200
            p_data = pause_resp.json()
            assert p_data["status"] == "paused"
            assert p_data["version"] == 2
            assert p_data["action"] == "pause"

            # 2. Stale version pause attempt returns 409
            stale_resp = await client.post(
                f"/api/v1/jobs/{job_id}/pause",
                json={"expected_version": 1, "reason": "Stale attempt"},
            )
            assert stale_resp.status_code == 409

            # 3. Resume job from paused state
            resume_resp = await client.post(
                f"/api/v1/jobs/{job_id}/resume",
                json={"expected_version": 2, "reason": "Operator resumed"},
            )
            assert resume_resp.status_code == 200
            r_data = resume_resp.json()
            assert r_data["status"] == "running"
            assert r_data["version"] == 3
            assert r_data["action"] == "resume"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cancel_job_lifecycle(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        owner=str(principal.user_id),
        owner_user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        status="queued",
        version=1,
        source_ref="https://github.com/acme/legacy@main",
        target_stack_spec={"language": "python"},
        budget={"max_cost_cents": 50000},
    )

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = job
    mock_db_session.execute.return_value = mock_res

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            cancel_resp = await client.post(
                f"/api/v1/jobs/{job_id}/cancel",
                json={"expected_version": 1, "reason": "Cancelled by user"},
            )
            assert cancel_resp.status_code == 200
            c_data = cancel_resp.json()
            assert c_data["status"] == "cancelled"
            assert c_data["version"] == 2

            # Attempting to pause or resume a cancelled (terminal) job returns 409
            illegal_pause = await client.post(
                f"/api/v1/jobs/{job_id}/pause",
                json={"expected_version": 2},
            )
            assert illegal_pause.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_forbidden_role_cannot_manage_lifecycle(
    app: FastAPI, mock_db_session: AsyncMock
) -> None:
    # Reviewer role does not have Permission.JOB_MANAGE or Permission.JOB_CANCEL
    principal = _principal(Role.REVIEWER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    job_id = uuid.uuid4()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp_pause = await client.post(
                f"/api/v1/jobs/{job_id}/pause",
                json={"expected_version": 1},
            )
            assert resp_pause.status_code == 403

            resp_cancel = await client.post(
                f"/api/v1/jobs/{job_id}/cancel",
                json={"expected_version": 1},
            )
            assert resp_cancel.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_invalid_idempotency_key_format(app: FastAPI, mock_db_session: AsyncMock) -> None:
    principal = _principal(Role.OWNER)
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Overlong idempotency key (> 128 chars)
            resp = await client.post(
                "/api/v1/jobs",
                json={
                    "source_repository": "https://github.com/acme/legacy",
                    "source_revision": "v1.0",
                    "target_stack": {"language": "python"},
                    "budget": {"max_cost_cents": 50000},
                },
                headers={"Idempotency-Key": "k" * 130},
            )
            assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()
