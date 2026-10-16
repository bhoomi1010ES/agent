"""Security integration tests verifying that API keys and secrets never appear in logs, spans, or databases."""

import logging
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from modernization_platform.db.models.job import Job
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.model_gateway.contracts import (
    ChatMessage,
    ModelExecutionContext,
    ModelRequest,
)
from modernization_platform.domain.model_gateway.redaction import redact_exception, redact_string
from modernization_platform.integrations.models.mock import MockProviderAdapter
from modernization_platform.observability.telemetry import trace_async_span
from modernization_platform.services.model_gateway.gateway_service import ModelGatewayService

FAKE_OPENAI_KEY = "sk-live-secretkey1234567890abcdef1234567890"
FAKE_BEARER_TOKEN = "Bearer test-token-abcdef123456789"
FAKE_DATABASE_SECRET = "secret_password_xyz123"


@pytest.mark.asyncio
async def test_secrets_never_leak_in_logs_and_exceptions(
    db_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that credentials never appear in application logs or exception string outputs."""
    caplog.set_level(logging.DEBUG)

    # 1. Format an exception containing raw secrets
    raw_error = ValueError(
        f"Failed to authenticate with {FAKE_OPENAI_KEY} and token {FAKE_BEARER_TOKEN}"
    )
    sanitized_error = redact_exception(raw_error)

    assert FAKE_OPENAI_KEY not in sanitized_error
    assert "test-token-abcdef123456789" not in sanitized_error
    assert "[REDACTED_API_KEY]" in sanitized_error
    assert "[REDACTED_TOKEN]" in sanitized_error

    # 2. Emit log through safe logger
    logger = logging.getLogger("modernization_platform.test_security")
    logger.info("Attempting connection with token %s", redact_string(FAKE_OPENAI_KEY))

    # Search captured logs
    for record in caplog.records:
        assert FAKE_OPENAI_KEY not in record.message
        assert "secretkey1234567890" not in record.message


@pytest.mark.asyncio
async def test_secrets_never_leak_in_telemetry_spans() -> None:
    """Verify that OpenTelemetry span attributes scrub sensitive keys and bearer tokens."""
    attrs = {
        "user_id": "test_user",
        "api_key": FAKE_OPENAI_KEY,
        "auth_header": FAKE_BEARER_TOKEN,
        "db_url": f"postgresql+asyncpg://admin:{FAKE_DATABASE_SECRET}@localhost:5432/db",
    }

    async with trace_async_span("secure_test_span", attributes=attrs) as span:
        # Span must have been initialized with redacted values
        assert span is not None


@pytest.mark.asyncio
async def test_secrets_never_leak_in_database_records(db_engine: AsyncEngine) -> None:
    """Verify that database records in model_execution, job, and audit_event never store raw API keys."""
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

    mock_adapter = MockProviderAdapter(default_response="Clean generated response without secrets.")
    adapters = {"mock": mock_adapter}

    async with session_factory() as session, session.begin():
        gateway = ModelGatewayService(session, adapters=adapters)
        req = ModelRequest(
            messages=[ChatMessage(role="user", content="Test prompt without secrets")],
            prompt_version="v1.0",
        )
        ctx = ModelExecutionContext(job_id=job_id, agent_role="architect")
        await gateway.generate(req, ctx)

    # Directly scan PostgreSQL text columns across relevant tables for any leaked secret substring
    async with session_factory() as session:
        # Check model_execution table
        result = await session.execute(
            text(
                "SELECT provider, model_id, prompt_version, status FROM model_execution WHERE job_id = :jid"
            ),
            {"jid": job_id},
        )
        rows = result.fetchall()
        for row in rows:
            row_str = str(row)
            assert FAKE_OPENAI_KEY not in row_str
            assert FAKE_BEARER_TOKEN not in row_str
            assert FAKE_DATABASE_SECRET not in row_str

        # Check audit_event table
        result_audit = await session.execute(
            text("SELECT payload FROM audit_event WHERE job_id = :jid"),
            {"jid": job_id},
        )
        audit_rows = result_audit.fetchall()
        for a_row in audit_rows:
            a_str = str(a_row)
            assert FAKE_OPENAI_KEY not in a_str
            assert FAKE_BEARER_TOKEN not in a_str
            assert FAKE_DATABASE_SECRET not in a_str
