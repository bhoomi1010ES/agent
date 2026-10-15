"""PostgreSQL integration tests verifying database integrity constraints and deletion policies."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.artifact import Artifact
from modernization_platform.db.models.identity import Tenant, TenantMembership, UserAccount
from modernization_platform.db.models.job import Job
from modernization_platform.db.models.module import Module
from modernization_platform.db.models.module_attempt import ModuleAttempt


@pytest.mark.asyncio
async def test_foreign_key_constraint_rejects_invalid_parent(db_session: AsyncSession) -> None:
    """Verify PostgreSQL foreign key constraints reject child records with non-existent parent IDs."""
    non_existent_job_id = uuid.uuid4()

    invalid_artifact = Artifact(
        id=uuid.uuid4(),
        job_id=non_existent_job_id,
        type="SPECIFICATION",
        storage_ref="s3://artifacts/nonexistent.md",
        version=1,
        content_hash="a" * 64,
    )
    db_session.add(invalid_artifact)

    with pytest.raises(IntegrityError, match="foreign key constraint"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_membership_rejects_roles_outside_the_baseline_catalog(
    db_session: AsyncSession,
) -> None:
    """Verify the database role check prevents unrecognized privilege labels."""
    tenant = Tenant(slug="role-constraint", display_name="Role Constraint")
    user = UserAccount(issuer="https://identity.test", subject="role-constraint-user")
    db_session.add_all([tenant, user])
    await db_session.flush()
    db_session.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role="superuser",
        )
    )

    with pytest.raises(IntegrityError, match="role_allowed"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_unique_constraint_rejects_duplicate_module_attempt(
    db_session: AsyncSession,
) -> None:
    """Verify unique constraint uq_module_attempt_number rejects duplicate attempt numbers per module."""
    job = Job(
        id=uuid.uuid4(),
        owner="constraint-test",
        source_ref="https://example.invalid/legacy/unique-attempt.git",
    )
    db_session.add(job)
    await db_session.flush()

    module = Module(
        id=uuid.uuid4(),
        job_id=job.id,
        name="CustomerBillingModule",
        legacy_paths=["legacy/customer-billing.cob"],
        risk_score=4.0,
    )
    db_session.add(module)
    await db_session.flush()

    attempt1 = ModuleAttempt(
        id=uuid.uuid4(),
        module_id=module.id,
        attempt_number=1,
        branch="job/unique-attempt/customer-billing/1",
    )
    db_session.add(attempt1)
    await db_session.flush()

    # Attempt to insert identical attempt_number for same module
    attempt2 = ModuleAttempt(
        id=uuid.uuid4(),
        module_id=module.id,
        attempt_number=1,
        branch="job/unique-attempt/customer-billing/duplicate",
    )
    db_session.add(attempt2)

    with pytest.raises(IntegrityError, match="uq_module_attempt_number"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_check_constraint_rejects_non_positive_attempt_number(
    db_session: AsyncSession,
) -> None:
    """Verify check constraint ck_module_attempt_number_positive enforces attempt_number > 0."""
    job = Job(
        id=uuid.uuid4(),
        owner="constraint-test",
        source_ref="https://example.invalid/legacy/positive-attempt.git",
    )
    db_session.add(job)
    await db_session.flush()

    module = Module(
        id=uuid.uuid4(),
        job_id=job.id,
        name="CheckModule",
        legacy_paths=["legacy/check.cob"],
    )
    db_session.add(module)
    await db_session.flush()

    invalid_attempt = ModuleAttempt(
        id=uuid.uuid4(),
        module_id=module.id,
        attempt_number=0,  # Invalid: <= 0 violates check constraint
        branch="job/positive-attempt/check/0",
    )
    db_session.add(invalid_attempt)

    with pytest.raises(IntegrityError, match="ck_module_attempt_number_positive"):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_cascading_deletion_removes_child_modules(
    db_session: AsyncSession,
) -> None:
    """Verify ON DELETE CASCADE policy cleans up modules when parent job is deleted."""
    job = Job(
        id=uuid.uuid4(),
        owner="constraint-test",
        source_ref="https://example.invalid/legacy/cascade.git",
    )
    db_session.add(job)
    await db_session.flush()

    module = Module(
        id=uuid.uuid4(),
        job_id=job.id,
        name="CascadedChildModule",
        legacy_paths=["legacy/cascade.cob"],
    )
    db_session.add(module)
    await db_session.commit()

    # Verify child exists
    found_module = await db_session.get(Module, module.id)
    assert found_module is not None

    # Delete parent job
    found_job = await db_session.get(Job, job.id)
    assert found_job is not None
    await db_session.delete(found_job)
    await db_session.commit()

    # Expire and verify child module was cascaded away
    db_session.expire_all()
    res = await db_session.execute(select(Module).where(Module.id == module.id))
    assert res.scalar_one_or_none() is None
