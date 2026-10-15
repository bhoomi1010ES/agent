"""Authenticated identity and trusted background execution contexts."""

import uuid
from datetime import datetime

from pydantic import AwareDatetime

from modernization_platform.schemas.base import ContractModel
from modernization_platform.security.permissions import Permission, Role, permissions_for_roles


class AuthenticatedPrincipal(ContractModel):
    """Verified application identity resolved from a token and database membership."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    session_id: uuid.UUID
    subject: str
    issuer: str
    roles: frozenset[Role]
    expires_at: AwareDatetime
    authentication_method: str

    def has_permission(self, permission: Permission) -> bool:
        """Return whether the resolved database roles grant a permission."""
        try:
            return permission in permissions_for_roles(self.roles)
        except Exception:
            return False


class WorkerAuthorizationContext(ContractModel):
    """Non-secret identity references persisted with background work."""

    initiator_user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    job_id: uuid.UUID
    initiated_at: datetime


__all__ = ["AuthenticatedPrincipal", "WorkerAuthorizationContext"]
