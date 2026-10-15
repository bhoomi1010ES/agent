"""Deny-by-default authorization policy primitives."""

import logging

from modernization_platform.core.exceptions import ForbiddenException
from modernization_platform.security.permissions import Permission, Role
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


def require_permission(
    principal: AuthenticatedPrincipal,
    permission: Permission,
) -> None:
    """Require one explicit permission and fail closed for unknown role state."""
    try:
        if not principal.roles or not principal.has_permission(permission):
            logger.warning(
                "Authorization denied | user_id=%s tenant_id=%s permission=%s",
                principal.user_id,
                principal.tenant_id,
                permission.value,
            )
            raise ForbiddenException()
    except ForbiddenException:
        raise
    except Exception as exc:
        logger.exception("Authorization policy evaluation failed | permission=%s", permission.value)
        raise ForbiddenException() from exc


def has_tenant_admin_scope(principal: AuthenticatedPrincipal) -> bool:
    """Return whether the principal has deliberate tenant-wide administrator scope."""
    try:
        return Role.ADMIN in principal.roles
    except Exception:
        return False


__all__ = ["has_tenant_admin_scope", "require_permission"]
