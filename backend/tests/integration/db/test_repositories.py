"""PostgreSQL integration tests for repository layer CRUD, pagination, and queries."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.identity import UserAccount
from modernization_platform.repositories.agent_runs import AgentRunRepository
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.gates import GateRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.repositories.module_attempts import ModuleAttemptRepository
from modernization_platform.repositories.modules import ModuleRepository
from modernization_platform.repositories.tests import TestRepository


@pytest.mark.asyncio
async def test_job_repository_crud(db_session: AsyncSession) -> None:
    """Verify JobRepository create, retrieve, update, and paginated listing."""
    repo = JobRepository(db_session)

    # 1. Create
    job = await repo.create_job(
        owner="payments-team",
        source_ref="https://github.com/example/pay",
        target_stack_spec={"language": "python"},
    )
    await db_session.commit()
    assert job.id is not None
    assert job.status == "pending"

    # 2. Get by ID
    retrieved = await db_session.get(type(job), job.id)
    assert retrieved is not None
    assert retrieved.owner == "payments-team"
    assert retrieved.source_ref == "https://github.com/example/pay"

    # 3. Update status
    updated = await repo.update_status(job.id, "running")
    await db_session.commit()
    assert updated is not None
    assert updated.status == "running"

    # 4. List paginated
    items = await repo._list_jobs_unscoped(offset=0, limit=10, status="running")
    assert any(j.id == job.id for j in items)


@pytest.mark.asyncio
async def test_artifact_repository_operations(db_session: AsyncSession) -> None:
    """Verify ArtifactRepository persistence, retrieval, and version lookup."""
    job_repo = JobRepository(db_session)
    artifact_repo = ArtifactRepository(db_session)

    job = await job_repo.create_job(
        owner="artifact-test",
        source_ref="https://example.invalid/legacy/artifacts.git",
    )
    await db_session.commit()

    artifact = await artifact_repo._append_artifact_after_authorization(
        job_id=job.id,
        artifact_type="INTERMEDIATE_REPRESENTATION",
        storage_ref="s3://modernization-artifacts/ir_ast.json",
        version=1,
        content_hash="a" * 64,
        artifact_metadata={"node_count": 1420},
    )
    await db_session.commit()

    retrieved = await db_session.get(type(artifact), artifact.id)
    assert retrieved is not None
    assert retrieved.content_hash == "a" * 64
    assert retrieved.artifact_metadata == {"node_count": 1420}

    # Test scope and version lookup
    versioned = await artifact_repo._get_by_job_and_type_version_unscoped(
        job_id=job.id,
        artifact_type="INTERMEDIATE_REPRESENTATION",
        version=1,
    )
    assert versioned is not None
    assert versioned.id == artifact.id


@pytest.mark.asyncio
async def test_module_and_attempt_repositories(db_session: AsyncSession) -> None:
    """Verify ModuleRepository and ModuleAttemptRepository lineage."""
    job_repo = JobRepository(db_session)
    module_repo = ModuleRepository(db_session)
    attempt_repo = ModuleAttemptRepository(db_session)

    job = await job_repo.create_job(
        owner="module-test",
        source_ref="https://example.invalid/legacy/modules.git",
    )
    await db_session.commit()

    module = await module_repo.create_module(
        job_id=job.id,
        name="BillingEngine",
        legacy_paths=["src/billing/engine.cob"],
        risk_score=5.0,
    )
    await db_session.commit()

    attempt = await attempt_repo.create_attempt(
        module_id=module.id,
        attempt_number=1,
        branch=f"job/{job.id}/billing-engine/1",
    )
    await db_session.commit()

    attempts = await attempt_repo.list_by_module(module.id)
    assert len(attempts) == 1
    retrieved_attempt = attempts[0]
    assert retrieved_attempt.id == attempt.id
    assert retrieved_attempt.attempt_number == 1


@pytest.mark.asyncio
async def test_agent_run_repository(db_session: AsyncSession) -> None:
    """Verify AgentRunRepository creation, status update, and listing."""
    job_repo = JobRepository(db_session)
    agent_repo = AgentRunRepository(db_session)

    job = await job_repo.create_job(
        owner="agent-test",
        source_ref="https://example.invalid/legacy/agent-run.git",
    )
    await db_session.commit()

    agent_run = await agent_repo.record_run(
        job_id=job.id,
        agent="DISCOVERY_AGENT",
        model="deepseek-r1",
        prompt_version="1.0.0",
        tokens_input=1540,
        duration_ms=250,
    )
    await db_session.commit()

    retrieved = await agent_repo.get_by_id(agent_run.id)
    assert retrieved is not None
    assert retrieved.tokens_input == 1540

    runs = await agent_repo.list_runs_by_job(job.id, agent="DISCOVERY_AGENT")
    assert [run.id for run in runs] == [agent_run.id]


@pytest.mark.asyncio
async def test_test_repository_cases_and_results(db_session: AsyncSession) -> None:
    """Verify TestRepository manages test cases and associated execution results."""
    job_repo = JobRepository(db_session)
    test_repo = TestRepository(db_session)

    job = await job_repo.create_job(
        owner="verification-test",
        source_ref="https://example.invalid/legacy/test-execution.git",
    )
    await db_session.commit()

    test_case = await test_repo.create_test_case(
        job_id=job.id,
        suite_version=1,
        layer="EQUIVALENCE",
        module_name="tax-calculation",
        legacy_capture_ref="s3://captures/test_calculate_tax_exemption.json",
    )
    await db_session.commit()

    result = await test_repo.record_test_result(
        test_case_id=test_case.id,
        system="converted",
        outcome="pass",
    )
    await db_session.commit()

    results = await test_repo.list_results_by_test_case(test_case.id)
    assert len(results) == 1
    assert results[0].id == result.id
    assert results[0].outcome == "pass"


@pytest.mark.asyncio
async def test_gate_repository_and_decisions(db_session: AsyncSession) -> None:
    """Verify GateRepository manages interrupt gates and human decisions."""
    job_repo = JobRepository(db_session)
    gate_repo = GateRepository(db_session)

    job = await job_repo.create_job(
        owner="architecture-team",
        source_ref="https://example.invalid/legacy/approval.git",
    )
    await db_session.commit()

    gate = await gate_repo.create_gate(
        job_id=job.id,
        gate_type="G1_DISCOVERY_PLAN",
        needs_human_flags=[{"reason": "architecture sign-off required"}],
    )
    actor = UserAccount(
        issuer="https://identity.repository-test",
        subject="lead-architect",
        display_name="Lead Architect",
    )
    db_session.add(actor)
    await db_session.commit()

    decision = await gate_repo.record_authorized_decision(
        gate=gate,
        actor_user_id=actor.id,
        decision="approved",
        feedback="Decomposition plan is sound and verified against legacy rules.",
    )
    await db_session.commit()

    retrieved_gate = await db_session.get(type(gate), gate.id)
    assert retrieved_gate is not None
    assert retrieved_gate.state == "approved"

    decision_result = await db_session.execute(
        select(GateDecision).where(GateDecision.gate_id == gate.id)
    )
    decisions = list(decision_result.scalars().all())
    assert [item.id for item in decisions] == [decision.id]
