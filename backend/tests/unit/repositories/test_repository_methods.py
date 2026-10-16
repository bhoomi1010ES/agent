"""Unit tests for repository layer methods, query builders, and exception translation."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modernization_platform.core.exceptions import PersistenceError
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.module import Module
from modernization_platform.db.models.test_case import TestCase
from modernization_platform.repositories.agent_runs import AgentRunRepository
from modernization_platform.repositories.artifacts import ArtifactRepository
from modernization_platform.repositories.audit_events import AuditEventRepository
from modernization_platform.repositories.gates import GateRepository
from modernization_platform.repositories.jobs import JobRepository
from modernization_platform.repositories.module_attempts import ModuleAttemptRepository
from modernization_platform.repositories.modules import ModuleRepository
from modernization_platform.repositories.tests import TestRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_job_repository_unit(mock_session: AsyncMock) -> None:
    repo = JobRepository(mock_session)

    # create_job
    job = await repo.create_job(
        owner="architect_team",
        source_ref="https://github.com/example/legacy",
        target_stack_spec={"language": "python", "framework": "fastapi"},
    )
    assert job.owner == "architect_team"
    assert job.status in ("pending", "queued")
    mock_session.add.assert_called_once_with(job)
    mock_session.flush.assert_awaited()

    # get_by_id
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = job
    mock_session.execute.return_value = mock_res
    found = await repo.get_by_id_scoped(
        job_id=job.id,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert found is job

    # get_by_id not found returns None
    mock_res_empty = MagicMock()
    mock_res_empty.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res_empty
    assert (
        await repo.get_by_id_scoped(
            job_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            membership_id=uuid.uuid4(),
        )
        is None
    )

    # update_status
    mock_session.execute.return_value = mock_res
    updated = await repo.update_status(job.id, "running")
    assert updated is not None
    assert updated.status == "running"

    # list_jobs
    mock_result_items = MagicMock()
    mock_result_items.scalars.return_value.all.return_value = [job]
    mock_result_count = MagicMock()
    mock_result_count.scalar_one.return_value = 1
    mock_session.execute.side_effect = [mock_result_items, mock_result_count]

    items = await repo._list_jobs_unscoped(offset=0, limit=10, status="running")
    assert items == [job]

    # list_jobs_scoped & count_jobs_scoped
    mock_res_scoped = MagicMock()
    mock_res_scoped.scalars.return_value.all.return_value = [job]
    mock_res_count = MagicMock()
    mock_res_count.scalar.return_value = 1
    mock_session.execute.side_effect = [mock_res_scoped, mock_res_count]

    scoped_jobs = await repo.list_jobs_scoped(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        limit=10,
        offset=0,
    )
    assert scoped_jobs == [job]
    count = await repo.count_jobs_scoped(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert count == 1


@pytest.mark.asyncio
async def test_artifact_repository_unit(mock_session: AsyncMock) -> None:
    repo = ArtifactRepository(mock_session)
    job_id = uuid.uuid4()

    # append_artifact
    artifact = await repo._append_artifact_after_authorization(
        job_id=job_id,
        artifact_type="IR_AST",
        content_hash="sha256:123456",
        storage_ref="s3://artifacts/ir_ast.json",
        version=1,
    )
    assert artifact.type == "IR_AST"
    assert artifact.version == 1
    mock_session.add.assert_called_once_with(artifact)

    # get_by_id
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = artifact
    mock_session.execute.return_value = mock_res
    found = await repo.get_by_id_scoped(
        artifact_id=artifact.id,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert found is artifact

    # list_artifacts_by_job
    mock_res_list = MagicMock()
    mock_res_list.scalars.return_value.all.return_value = [artifact]
    mock_session.execute.return_value = mock_res_list
    results = await repo._list_artifacts_by_job_unscoped(job_id)
    assert results == [artifact]

    # get_by_job_and_type_version
    mock_res_version = MagicMock()
    mock_res_version.scalar_one_or_none.return_value = artifact
    mock_session.execute.return_value = mock_res_version
    ver_art = await repo._get_by_job_and_type_version_unscoped(job_id, "IR_AST", 1)
    assert ver_art is artifact

    # list_artifacts_scoped & get_by_job_and_type_scoped
    mock_res_art_scoped = MagicMock()
    mock_res_art_scoped.scalars.return_value.all.return_value = [artifact]
    mock_res_art_single = MagicMock()
    mock_res_art_single.scalar_one_or_none.return_value = artifact
    mock_session.execute.side_effect = [mock_res_art_scoped, mock_res_art_single]

    art_list = await repo.list_artifacts_scoped(
        job_id=job_id,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert art_list == [artifact]

    single_art = await repo.get_by_job_and_type_scoped(
        job_id=job_id,
        artifact_type="IR_AST",
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert single_art is artifact


@pytest.mark.asyncio
async def test_module_and_attempt_repository_unit(mock_session: AsyncMock) -> None:
    mod_repo = ModuleRepository(mock_session)
    att_repo = ModuleAttemptRepository(mock_session)
    job_id = uuid.uuid4()

    # ModuleRepository.create_module
    module = await mod_repo.create_module(
        job_id=job_id,
        name="BillingEngine",
        legacy_paths=["legacy/cobol/billing.cob"],
    )
    assert module.name == "BillingEngine"
    mock_session.add.assert_called_with(module)

    # ModuleRepository.get_by_id
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = module
    mock_session.execute.return_value = mock_res
    found_mod = await mod_repo.get_by_id(module.id)
    assert found_mod is module

    # ModuleRepository.list_by_job
    mock_res_list = MagicMock()
    mock_res_list.scalars.return_value.all.return_value = [module]
    mock_session.execute.return_value = mock_res_list
    modules = await mod_repo.list_by_job(job_id)
    assert modules == [module]

    # ModuleAttemptRepository.create_attempt
    attempt = await att_repo.create_attempt(
        module_id=module.id,
        attempt_number=1,
        branch="features/attempt-1",
    )
    assert attempt.attempt_number == 1

    # ModuleAttemptRepository.list_by_module
    mock_res_att = MagicMock()
    mock_res_att.scalars.return_value.all.return_value = [attempt]
    mock_session.execute.return_value = mock_res_att
    attempts = await att_repo.list_by_module(module.id)
    assert attempts == [attempt]

    # ModuleAttemptRepository.record_outcome
    mock_res_single = MagicMock()
    mock_res_single.scalar_one_or_none.return_value = attempt
    mock_session.execute.return_value = mock_res_single
    updated_att = await att_repo.record_outcome(attempt.id, "success")
    assert updated_att is not None
    assert updated_att.outcome == "success"


@pytest.mark.asyncio
async def test_agent_run_repository_unit(mock_session: AsyncMock) -> None:
    repo = AgentRunRepository(mock_session)
    job_id = uuid.uuid4()

    # record_run
    run = await repo.record_run(
        job_id=job_id,
        agent="DISCOVERY_AGENT",
        model="deepseek-r1",
        prompt_version="1.0.0",
    )
    assert run.agent == "DISCOVERY_AGENT"
    mock_session.add.assert_called_with(run)

    # get_by_id
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = run
    mock_session.execute.return_value = mock_res
    found_run = await repo.get_by_id(run.id)
    assert found_run is run

    # list_runs_by_job
    mock_res_list = MagicMock()
    mock_res_list.scalars.return_value.all.return_value = [run]
    mock_session.execute.return_value = mock_res_list
    runs = await repo.list_runs_by_job(job_id)
    assert runs == [run]


@pytest.mark.asyncio
async def test_test_repository_unit(mock_session: AsyncMock) -> None:
    repo = TestRepository(mock_session)
    job_id = uuid.uuid4()

    # create_test_case
    case = await repo.create_test_case(
        job_id=job_id,
        suite_version=1,
        layer="EQUIVALENCE",
        legacy_capture_ref="captures/test_case_1.json",
    )
    assert case.layer == "EQUIVALENCE"

    # get_test_case_by_id
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = case
    mock_session.execute.return_value = mock_res
    found_case = await repo.get_test_case_by_id(case.id)
    assert found_case is case

    # record_test_result
    result = await repo.record_test_result(
        test_case_id=case.id,
        system="MODERNIZED",
        outcome="passed",
    )
    assert result.outcome == "passed"

    # list_results_by_test_case
    mock_res_results = MagicMock()
    mock_res_results.scalars.return_value.all.return_value = [result]
    mock_session.execute.return_value = mock_res_results
    results = await repo.list_results_by_test_case(case.id)
    assert results == [result]


@pytest.mark.asyncio
async def test_gate_repository_unit(mock_session: AsyncMock) -> None:
    repo = GateRepository(mock_session)
    job_id = uuid.uuid4()

    # create_gate
    gate = await repo.create_gate(job_id=job_id, gate_type="G1_DISCOVERY_PLAN")
    assert gate.gate_type == "G1_DISCOVERY_PLAN"

    # record_authorized_decision accepts only a gate returned by a scoped query
    actor_user_id = uuid.uuid4()
    decision = await repo.record_authorized_decision(
        gate=gate,
        actor_user_id=actor_user_id,
        decision="approved",
        feedback="Decomposition verified.",
    )
    assert decision.decision == "approved"
    assert decision.actor == str(actor_user_id)
    # get_by_id_scoped with for_update
    mock_res_gate = MagicMock()
    mock_res_gate.scalar_one_or_none.return_value = gate
    mock_session.execute.return_value = mock_res_gate
    found_gate = await repo.get_by_id_scoped(
        gate_id=gate.id,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        for_update=True,
    )
    assert found_gate is gate


@pytest.mark.asyncio
async def test_audit_event_repository_unit(mock_session: AsyncMock) -> None:
    repo = AuditEventRepository(mock_session)
    job_id = uuid.uuid4()

    # append_event
    event = await repo.append_event(
        actor="operator_1",
        action="JOB_STARTED",
        job_id=job_id,
        correlation_id="corr-1",
        payload={"source": "api"},
    )
    assert event.action == "JOB_STARTED"
    mock_session.add.assert_called_with(event)

    # get_by_id
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = event
    mock_session.execute.return_value = mock_res
    found = await repo.get_by_id(event.id)
    assert found is event

    # list_events_by_job
    mock_res_list = MagicMock()
    mock_res_list.scalars.return_value.all.return_value = [event]
    mock_session.execute.return_value = mock_res_list
    events = await repo.list_events_by_job(job_id, limit=50, offset=0)
    assert events == [event]

    # list_events with action and actor filters
    all_events = await repo.list_events(action="JOB_STARTED", actor="operator_1")
    assert all_events == [event]

    # list_events_by_job_scoped & count_events_by_job_scoped
    mock_res_audit_scoped = MagicMock()
    mock_res_audit_scoped.scalars.return_value.all.return_value = [event]
    mock_res_audit_count = MagicMock()
    mock_res_audit_count.scalar.return_value = 1
    mock_session.execute.side_effect = [mock_res_audit_scoped, mock_res_audit_count]

    audit_list = await repo.list_events_by_job_scoped(
        job_id=job_id,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert audit_list == [event]

    audit_count = await repo.count_events_by_job_scoped(
        job_id=job_id,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
    )
    assert audit_count == 1


@pytest.mark.asyncio
async def test_artifact_auto_versioning(mock_session: AsyncMock) -> None:
    """Verify append_artifact auto-calculates next monotonic version."""
    repo = ArtifactRepository(mock_session)
    job_id = uuid.uuid4()

    mock_res = MagicMock()
    mock_res.scalar.return_value = 3
    mock_session.execute.return_value = mock_res

    artifact = await repo._append_artifact_after_authorization(
        job_id=job_id,
        artifact_type="CODE",
        content_hash="sha256:789",
        storage_ref="s3://code/v4.py",
        version=None,
    )
    assert artifact.version == 4


@pytest.mark.asyncio
async def test_module_update_status(mock_session: AsyncMock) -> None:
    """Verify ModuleRepository.update_status updates state."""
    repo = ModuleRepository(mock_session)
    module_id = uuid.uuid4()
    module = Module(id=module_id, job_id=uuid.uuid4(), name="TestMod", legacy_paths=["test.cob"])

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = module
    mock_session.execute.return_value = mock_res

    updated = await repo.update_status(module_id, "completed")
    assert updated is not None
    assert updated.status == "completed"


@pytest.mark.asyncio
async def test_list_test_cases_by_job(mock_session: AsyncMock) -> None:
    """Verify TestRepository.list_test_cases_by_job filtering."""
    repo = TestRepository(mock_session)
    job_id = uuid.uuid4()

    case = TestCase(job_id=job_id, suite_version=1, layer="unit", legacy_capture_ref="ref")
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [case]
    mock_session.execute.return_value = mock_res

    cases = await repo.list_test_cases_by_job(job_id, suite_version=1, module_name="ModA")
    assert cases == [case]


@pytest.mark.asyncio
async def test_list_gates_by_job(mock_session: AsyncMock) -> None:
    """Verify GateRepository.list_gates_by_job filtering."""
    repo = GateRepository(mock_session)
    job_id = uuid.uuid4()

    gate = Gate(job_id=job_id, gate_type="G2")
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [gate]
    mock_session.execute.return_value = mock_res

    gates = await repo._list_gates_by_job_unscoped(job_id, state="pending")
    assert gates == [gate]


@pytest.mark.asyncio
async def test_repository_translates_exceptions(mock_session: AsyncMock) -> None:
    """Verify repository methods catch database exceptions and raise PersistenceError."""
    repo = JobRepository(mock_session)
    mock_session.flush.side_effect = RuntimeError("Deadlock")

    with pytest.raises(PersistenceError, match="create_job"):
        await repo.create_job(owner="test", source_ref="ref")
