"""Central role and permission catalog for application authorization."""

from enum import StrEnum


class Role(StrEnum):
    """TDD-defined human roles."""

    OWNER = "owner"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ADMIN = "admin"


class Permission(StrEnum):
    """Explicit application permissions used by policy checks."""

    JOB_CREATE = "job.create"
    JOB_VIEW = "job.view"
    JOB_CANCEL = "job.cancel"
    JOB_MANAGE = "job.manage"
    ARTIFACT_VIEW = "artifact.view"
    ARTIFACT_CREATE = "artifact.create"
    ARTIFACT_MANAGE = "artifact.manage"
    REPOSITORY_VIEW = "repository.view"
    REPOSITORY_MANAGE = "repository.manage"
    GATE_VIEW = "gate.view"
    GATE_DECIDE = "gate.decide"
    AUDIT_VIEW = "audit.view"
    USER_MANAGE = "user.manage"
    TENANT_MANAGE = "tenant.manage"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(
        {
            Permission.JOB_CREATE,
            Permission.JOB_VIEW,
            Permission.JOB_CANCEL,
            Permission.JOB_MANAGE,
            Permission.ARTIFACT_VIEW,
            Permission.ARTIFACT_CREATE,
            Permission.ARTIFACT_MANAGE,
            Permission.REPOSITORY_VIEW,
            Permission.REPOSITORY_MANAGE,
            Permission.GATE_VIEW,
            Permission.AUDIT_VIEW,
        }
    ),
    Role.REVIEWER: frozenset(
        {
            Permission.JOB_VIEW,
            Permission.ARTIFACT_VIEW,
            Permission.REPOSITORY_VIEW,
            Permission.GATE_VIEW,
        }
    ),
    Role.APPROVER: frozenset(
        {
            Permission.JOB_VIEW,
            Permission.ARTIFACT_VIEW,
            Permission.REPOSITORY_VIEW,
            Permission.GATE_VIEW,
            Permission.GATE_DECIDE,
        }
    ),
    Role.ADMIN: frozenset(Permission),
}


def permissions_for_roles(roles: frozenset[Role]) -> frozenset[Permission]:
    """Return the immutable union of permissions for recognized roles."""
    try:
        permissions: set[Permission] = set()
        for role in roles:
            permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
        return frozenset(permissions)
    except Exception:
        return frozenset()


__all__ = ["ROLE_PERMISSIONS", "Permission", "Role", "permissions_for_roles"]
