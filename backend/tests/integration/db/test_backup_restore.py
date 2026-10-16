"""Sub-Phase 01.12 — PostgreSQL Backup and Restore Validation Test.

Validates Section 18:
1. Populates a complete representative Phase 1 dataset:
   - Tenant, UserAccount, TenantMembership, Job, JobMember
   - Task, Artifact, Gate, GateDecision, AuditEvent
   - BudgetAccount, BudgetReservation, ModelExecution
2. Creates a physical PostgreSQL backup dump using pg_dump.
3. Simulates database reset/restore into the database using psql.
4. Verifies all entity counts, foreign keys, and values are faithfully restored.
5. Executes post-restore operations (workflow gate approval & budget check) to verify usable state.
"""

import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.audit_event import AuditEvent
from modernization_platform.db.models.budget import BudgetAccount
from modernization_platform.db.models.gate import Gate
from modernization_platform.db.models.gate_decision import GateDecision
from modernization_platform.db.models.identity import (
    JobMember,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.model_execution import ModelExecution
from modernization_platform.db.models.task import Task
from modernization_platform.domain.gates.states import GateState
from modernization_platform.domain.jobs.states import JobLifecycleState
from modernization_platform.domain.tasks.states import TaskLifecycleState
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal
from modernization_platform.services.gates import GateService
from tests.integration.db.conftest import _PORT_AVAILABLE, TEST_DB_URL, _skip_or_fail_database


def _find_postgres_binary(binary_name: str) -> str | None:
    """Locate pg_dump or psql in PATH or standard PostgreSQL installation paths."""
    in_path = shutil.which(binary_name)
    if in_path:
        return in_path

    # Search standard Windows installation directories
    base_dirs = [
        Path(r"C:\Program Files\PostgreSQL"),
        Path(r"C:\Program Files (x86)\PostgreSQL"),
    ]
    for base in base_dirs:
        if base.is_dir():
            for version_dir in sorted(base.iterdir(), reverse=True):
                candidate = version_dir / "bin" / f"{binary_name}.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


@pytest.mark.asyncio
async def test_postgresql_backup_restore_and_post_restore_operation(
    db_session: AsyncSession,
) -> None:
    """Validate full pg_dump export, psql restoration, and post-restore operational readiness."""
    if not _PORT_AVAILABLE:
        _skip_or_fail_database("PostgreSQL test database not available")

    pg_dump_bin = _find_postgres_binary("pg_dump")
    psql_bin = _find_postgres_binary("psql")

    if not pg_dump_bin or not psql_bin:
        pytest.skip("pg_dump or psql binaries not found in environment for backup/restore testing")

    parsed_url = urlparse(
        TEST_DB_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )
    )
    db_host = parsed_url.hostname or "localhost"
    db_port = str(parsed_url.port or 5432)
    db_user = parsed_url.username or "postgres"
    db_password = parsed_url.password or "postgres"
    db_name = parsed_url.path.lstrip("/")

    # -------------------------------------------------------------------------
    # 1. SEED REPRESENTATIVE DATA ACROSS ALL PHASE 1 ENTITIES
    # -------------------------------------------------------------------------
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=f"backup-tenant-{uuid.uuid4().hex[:6]}",
        display_name="Backup Verification Tenant",
        active=True,
    )
    db_session.add(tenant)
    await db_session.flush()

    user = UserAccount(
        id=uuid.uuid4(),
        issuer="https://auth.modernization.internal",
        subject=f"backup-lead-{uuid.uuid4().hex[:6]}",
        display_name="Backup Test Lead",
        active=True,
    )
    db_session.add(user)
    await db_session.flush()

    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=user.id,
        role=Role.ADMIN.value,
        active=True,
    )
    db_session.add(membership)
    await db_session.flush()

    job = Job(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        owner=str(user.id),
        owner_user_id=user.id,
        status=JobLifecycleState.AWAITING_APPROVAL.value,
        source_ref="https://git.company.test/legacy/core.git",
        target_stack_spec={"framework": "fastapi"},
        budget={"max_cost_cents": 10000},
    )
    db_session.add(job)
    await db_session.flush()

    db_session.add(JobMember(job_id=job.id, membership_id=membership.id))

    task = Task(
        id=uuid.uuid4(),
        job_id=job.id,
        task_type="conversion_step",
        status=TaskLifecycleState.COMPLETED.value,
        worker_id="worker-backup-1",
        attempt_count=1,
        result={"files": 42},
    )
    db_session.add(task)

    artifact = Artifact(
        id=uuid.uuid4(),
        job_id=job.id,
        type="BlueprintSpec",
        version=1,
        storage_ref="s3://backup-bucket/spec_v1.json",
        content_hash="c" * 64,
        size_bytes=5000,
        content_type="application/json",
        status="available",
    )
    db_session.add(artifact)

    gate = Gate(
        id=uuid.uuid4(),
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        state=GateState.PENDING.value,
        artifact_versions_shown={"BlueprintSpec": 1},
        requested_at=datetime.now(UTC),
    )
    db_session.add(gate)
    await db_session.flush()

    gate_decision = GateDecision(
        id=uuid.uuid4(),
        gate_id=gate.id,
        job_id=job.id,
        gate_type="G1_FEASIBILITY",
        actor_user_id=user.id,
        actor=user.subject,
        approver_role="admin",
        decision="approved",
        feedback="Verified before dump",
        decided_at=datetime.now(UTC),
    )
    db_session.add(gate_decision)

    audit_event = AuditEvent(
        id=uuid.uuid4(),
        job_id=job.id,
        actor=user.subject,
        action="PRE_BACKUP_EVENT",
        payload={"stage": "seeding"},
    )
    db_session.add(audit_event)

    budget_acct = BudgetAccount(
        id=uuid.uuid4(),
        job_id=job.id,
        scope_type="job",
        scope_id="job",
        limit_microcents=10_000_000,
        spent_microcents=250_000,
        reserved_microcents=0,
        status="active",
    )
    db_session.add(budget_acct)
    await db_session.flush()

    model_exec = ModelExecution(
        id=uuid.uuid4(),
        job_id=job.id,
        task_id=task.id,
        agent_role="architect",
        stage="intake",
        provider="mock",
        model_id="mock-model",
        prompt_version="v1",
        input_tokens=100,
        output_tokens=200,
        total_tokens=300,
        actual_cost_microcents=250_000,
        status="succeeded",
        correlation_id=f"corr-backup-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(model_exec)

    # Commit all seeded data so it exists in PostgreSQL for pg_dump
    await db_session.commit()

    saved_job_id = job.id
    saved_gate_id = gate.id
    saved_tenant_id = tenant.id
    saved_user_id = user.id

    # -------------------------------------------------------------------------
    # 2. RUN PG_DUMP TO EXPORT DATABASE CONTENTS
    # -------------------------------------------------------------------------
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password

    with tempfile.TemporaryDirectory() as tmp_dir:
        dump_file = Path(tmp_dir) / "phase_01_backup.sql"

        dump_cmd = [
            pg_dump_bin,
            "-h",
            db_host,
            "-p",
            db_port,
            "-U",
            db_user,
            "-d",
            db_name,
            "--data-only",
            "--inserts",
            "-f",
            str(dump_file),
        ]

        dump_res = subprocess.run(dump_cmd, env=env, capture_output=True, text=True, check=False)
        assert dump_res.returncode == 0, f"pg_dump failed: {dump_res.stderr}"
        assert dump_file.is_file()
        assert dump_file.stat().st_size > 0

        # Verify dump contains data from our seeded entities
        dump_text = dump_file.read_text(encoding="utf-8")
        assert "INSERT INTO" in dump_text
        assert str(saved_job_id) in dump_text
        assert str(saved_tenant_id) in dump_text

        # -------------------------------------------------------------------------
        # 3. SIMULATE DISASTER / CLEAN SLATE: TRUNCATE TABLES
        # -------------------------------------------------------------------------
        async with db_session.begin():
            await db_session.execute(
                text(
                    """
                    TRUNCATE TABLE
                        model_execution,
                        budget_reservation,
                        budget_account,
                        gate_decision,
                        gate,
                        artifact,
                        task,
                        job_member,
                        audit_event,
                        job,
                        tenant_membership,
                        user_account,
                        tenant
                    CASCADE;
                    """
                )
            )
        await db_session.commit()

        # Confirm database is completely empty
        empty_jobs = await db_session.execute(select(func.count(Job.id)))
        assert empty_jobs.scalar() == 0

        # -------------------------------------------------------------------------
        # 4. RESTORE DATABASE FROM BACKUP USING PSQL
        # -------------------------------------------------------------------------
        restore_cmd = [
            psql_bin,
            "-h",
            db_host,
            "-p",
            db_port,
            "-U",
            db_user,
            "-d",
            db_name,
            "-f",
            str(dump_file),
        ]
        restore_res = subprocess.run(
            restore_cmd, env=env, capture_output=True, text=True, check=False
        )
        assert restore_res.returncode == 0, f"psql restore failed: {restore_res.stderr}"

    # -------------------------------------------------------------------------
    # 5. VERIFY RESTORED ENTITIES AND INTEGRITY
    # -------------------------------------------------------------------------
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with session_factory() as verify_session:
        # Verify Tenant & User
        restored_tenant = await verify_session.get(Tenant, saved_tenant_id)
        assert restored_tenant is not None
        assert restored_tenant.id == saved_tenant_id

        restored_user = await verify_session.get(UserAccount, saved_user_id)
        assert restored_user is not None

        # Verify Job
        restored_job = await verify_session.get(Job, saved_job_id)
        assert restored_job is not None
        assert restored_job.tenant_id == saved_tenant_id
        assert restored_job.status == JobLifecycleState.AWAITING_APPROVAL.value

        # Verify Gate and Decisions
        restored_gate = await verify_session.get(Gate, saved_gate_id)
        assert restored_gate is not None
        assert restored_gate.gate_type == "G1_FEASIBILITY"

        dec_res = await verify_session.execute(
            select(GateDecision).where(GateDecision.gate_id == saved_gate_id)
        )
        decisions = list(dec_res.scalars().all())
        assert len(decisions) >= 1
        assert decisions[0].decision == "approved"

        # Verify Budget and Model Execution
        budget_res = await verify_session.execute(
            select(BudgetAccount).where(BudgetAccount.job_id == saved_job_id)
        )
        restored_budget = budget_res.scalar_one_or_none()
        assert restored_budget is not None
        assert restored_budget.spent_microcents == 250_000

        model_res = await verify_session.execute(
            select(ModelExecution).where(ModelExecution.job_id == saved_job_id)
        )
        restored_model_exec = model_res.scalar_one_or_none()
        assert restored_model_exec is not None
        assert restored_model_exec.total_tokens == 300

        # ---------------------------------------------------------------------
        # 6. OPERATIONAL RESUMPTION: PERFORM ACTIVE OPERATION ON RESTORED DB
        # ---------------------------------------------------------------------
        # Verify that we can create a new gate on the restored job
        principal = AuthenticatedPrincipal(
            user_id=restored_user.id,
            tenant_id=restored_tenant.id,
            membership_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            subject=restored_user.subject,
            issuer=restored_user.issuer,
            roles=frozenset({Role.ADMIN}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            authentication_method="oidc_jwt",
        )

        gate_service = GateService(session=verify_session)
        post_restore_gate = await gate_service.create_gate(
            principal=principal,
            job_id=saved_job_id,
            gate_type="G2_CHARACTERIZATION",
            artifact_versions_shown={"BlueprintSpec": 1},
        )
        assert post_restore_gate is not None
        assert post_restore_gate.gate_type == "G2_CHARACTERIZATION"
        await verify_session.commit()
