"""RBAC catalog and fail-closed policy tests."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from modernization_platform.core.exceptions import ForbiddenException
from modernization_platform.security.authorization import require_permission
from modernization_platform.security.permissions import Permission, Role, permissions_for_roles
from modernization_platform.security.principals import AuthenticatedPrincipal


def _principal(role: Role) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        subject="stable-subject",
        issuer="https://identity.test",
        roles=frozenset({role}),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        authentication_method="oidc_jwt",
    )


def test_only_approver_and_admin_can_decide_gates() -> None:
    for denied_role in (Role.OWNER, Role.REVIEWER):
        with pytest.raises(ForbiddenException):
            require_permission(_principal(denied_role), Permission.GATE_DECIDE)

    require_permission(_principal(Role.APPROVER), Permission.GATE_DECIDE)
    require_permission(_principal(Role.ADMIN), Permission.GATE_DECIDE)


def test_privileged_management_permissions_are_admin_only() -> None:
    for role in (Role.OWNER, Role.REVIEWER, Role.APPROVER):
        assert Permission.USER_MANAGE not in permissions_for_roles(frozenset({role}))
        assert Permission.TENANT_MANAGE not in permissions_for_roles(frozenset({role}))

    admin_permissions = permissions_for_roles(frozenset({Role.ADMIN}))
    assert Permission.USER_MANAGE in admin_permissions
    assert Permission.TENANT_MANAGE in admin_permissions


def test_audit_access_is_limited_to_job_owners_and_tenant_admins() -> None:
    for role in (Role.REVIEWER, Role.APPROVER):
        assert Permission.AUDIT_VIEW not in permissions_for_roles(frozenset({role}))

    assert Permission.AUDIT_VIEW in permissions_for_roles(frozenset({Role.OWNER}))
    assert Permission.AUDIT_VIEW in permissions_for_roles(frozenset({Role.ADMIN}))


def test_empty_role_set_fails_closed() -> None:
    principal = _principal(Role.OWNER).model_copy(update={"roles": frozenset()})
    with pytest.raises(ForbiddenException):
        require_permission(principal, Permission.JOB_VIEW)
