"""PostgreSQL integration tests for repository layer CRUD, pagination, and queries."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
        name="Payment Modernization Job", repository_url="https://github.com/example/pay"
    )
    await db_session.commit()
    assert job.id is not None
    assert job.status == "PENDING"

    # 2. Get by ID
    retrieved = await repo.get_by_id(job.id)
    assert retrieved is not None
    assert retrieved.name == "Payment Modernization Job"

    # 3. Update status
    updated = await repo.update_status(job.id, "RUNNING")
    await db_session.commit()
    assert updated.status == "RUNNING"

    # 4. List paginated
    items, total = await repo.list_jobs(offset=0, limit=10, status_filter="RUNNING")
    assert total >= 1
    assert any(j.id == job.id for j in items)


@pytest.mark.asyncio
async def test_artifact_repository_operations(db_session: AsyncSession) -> None:
    """Verify ArtifactRepository persistence, retrieval, and version lookup."""
    job_repo = JobRepository(db_session)
    artifact_repo = ArtifactRepository(db_session)

    job = await job_repo.create_job(name="Artifact Test Job")
    await db_session.commit()

    artifact = await artifact_repo.create_artifact(
        job_id=job.id,
        name="ir_ast.json",
        artifact_type="INTERMEDIATE_REPRESENTATION",
        storage_uri="s3://modernization-artifacts/ir_ast.json",
        scope="GLOBAL",
        version=1,
        content_hash="sha256:abc12345",
        metadata_payload={"node_count": 1420},
    )
    await db_session.commit()

    retrieved = await artifact_repo.get_by_id(artifact.id)
    assert retrieved is not None
    assert retrieved.content_hash == "sha256:abc12345"
    assert retrieved.metadata_payload == {"node_count": 1420}

    # Test scope and version lookup
    versioned = await artifact_repo.get_by_scope_and_version(
        job_id=job.id, name="ir_ast.json", scope="GLOBAL", version=1
    )
    assert versioned is not None
    assert versioned.id == artifact.id


@pytest.mark.asyncio
async def test_module_and_attempt_repositories(db_session: AsyncSession) -> None:
    """Verify ModuleRepository and ModuleAttemptRepository lineage."""
    job_repo = JobRepository(db_session)
    module_repo = ModuleRepository(db_session)
    attempt_repo = ModuleAttemptRepository(db_session)

    job = await job_repo.create_job(name="Module Test Job")
    await db_session.commit()

    module = await module_repo.create_module(
        job_id=job.id,
        name="BillingEngine",
        file_path="src/billing/engine.cob",
        complexity_score=5,
    )
    await db_session.commit()

    attempt = await attempt_repo.create_attempt(
        module_id=module.id,
        job_id=job.id,
        attempt_number=1,
        status="RUNNING",
    )
    await db_session.commit()

    retrieved_attempt = await attempt_repo.get_attempt_by_number(module.id, 1)
    assert retrieved_attempt is not None
    assert retrieved_attempt.id == attempt.id
    assert retrieved_attempt.attempt_number == 1


@pytest.mark.asyncio
async def test_agent_run_repository(db_session: AsyncSession) -> None:
    """Verify AgentRunRepository creation, status update, and listing."""
    job_repo = JobRepository(db_session)
    agent_repo = AgentRunRepository(db_session)

    job = await job_repo.create_job(name="Agent Test Job")
    await db_session.commit()

    agent_run = await agent_repo.create_agent_run(
        job_id=job.id,
        agent_type="DISCOVERY_AGENT",
        model_name="deepseek-r1",
        model_provider="openrouter",
    )
    await db_session.commit()

    updated = await agent_repo.update_status(agent_run.id, "COMPLETED", {"tokens_used": 1540})
    await db_session.commit()
    assert updated.status == "COMPLETED"
    assert updated.output_metrics == {"tokens_used": 1540}


@pytest.mark.asyncio
async def test_test_repository_cases_and_results(db_session: AsyncSession) -> None:
    """Verify TestRepository manages test cases and associated execution results."""
    job_repo = JobRepository(db_session)
    test_repo = TestRepository(db_session)

    job = await job_repo.create_job(name="Test Execution Job")
    await db_session.commit()

    test_case = await test_repo.create_test_case(
        job_id=job.id,
        name="test_calculate_tax_exemption",
        test_type="EQUIVALENCE",
        input_payload={"customer_type": "EXEMPT", "amount": 100.0},
        expected_output={"tax": 0.0},
    )
    await db_session.commit()

    result = await test_repo.record_test_result(
        test_case_id=test_case.id,
        job_id=job.id,
        status="PASSED",
        actual_output={"tax": 0.0},
        execution_time_ms=14.5,
    )
    await db_session.commit()

    results = await test_repo.list_results_for_case(test_case.id)
    assert len(results) == 1
    assert results[0].id == result.id
    assert results[0].status == "PASSED"


@pytest.mark.asyncio
async def test_gate_repository_and_decisions(db_session: AsyncSession) -> None:
    """Verify GateRepository manages interrupt gates and human decisions."""
    job_repo = JobRepository(db_session)
    gate_repo = GateRepository(db_session)

    job = await job_repo.create_job(name="Approval Job")
    await db_session.commit()

    gate = await gate_repo.create_gate(
        job_id=job.id,
        gate_level="G1_DISCOVERY_PLAN",
        description="Requires architecture team sign-off before transformation",
    )
    await db_session.commit()

    decision = await gate_repo.record_decision(
        gate_id=gate.id,
        job_id=job.id,
        decision="APPROVED",
        approver_identity="lead_architect@enterprise.org",
        rationale="Decomposition plan is sound and verified against legacy rules.",
    )
    await db_session.commit()

    retrieved_gate = await gate_repo.get_gate_with_decisions(gate.id)
    assert retrieved_gate is not None
    assert retrieved_gate.status == "APPROVED"
    assert len(retrieved_gate.decisions) == 1
    assert retrieved_gate.decisions[0].id == decision.id
