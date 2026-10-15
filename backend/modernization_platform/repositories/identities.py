"""Identity and session lookups used to resolve verified tokens into principals."""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.db.models.identity import (
    AuthSession,
    Tenant,
    TenantMembership,
    UserAccount,
)
from modernization_platform.repositories.base import BaseRepository
from modernization_platform.security.authentication import VerifiedToken
from modernization_platform.security.permissions import Role
from modernization_platform.security.principals import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


def hash_token_id(issuer: str, token_id: str) -> str:
    """Create a non-reversible lookup key without persisting the raw token identifier."""
    try:
        return hashlib.sha256(f"{issuer}\x00{token_id}".encode()).hexdigest()
    except Exception as exc:
        logger.exception("hash_token_id failed | %s", type(exc).__name__)
        raise


class IdentityRepository(BaseRepository[UserAccount]):
    """Resolve active identities, memberships, tenants, and allowlisted sessions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def resolve_principal(self, token: VerifiedToken) -> AuthenticatedPrincipal | None:
        """Resolve a verified token without trusting role claims from the credential."""
        try:
            statement = (
                select(UserAccount, Tenant, TenantMembership, AuthSession)
                .join(
                    TenantMembership,
                    TenantMembership.user_id == UserAccount.id,
                )
                .join(Tenant, Tenant.id == TenantMembership.tenant_id)
                .join(
                    AuthSession,
                    (AuthSession.user_id == UserAccount.id) & (AuthSession.tenant_id == Tenant.id),
                )
                .where(
                    UserAccount.issuer == token.issuer,
                    UserAccount.subject == token.subject,
                    UserAccount.active.is_(True),
                    Tenant.id == token.tenant_id,
                    Tenant.active.is_(True),
                    TenantMembership.active.is_(True),
                    AuthSession.token_id_hash == hash_token_id(token.issuer, token.token_id),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > datetime.now(UTC),
                )
            )
            result = await self.session.execute(statement)
            row = result.one_or_none()
            if row is None:
                return None
            user, tenant, membership, auth_session = cast(
                tuple[UserAccount, Tenant, TenantMembership, AuthSession], tuple(row)
            )
            try:
                role = Role(membership.role)
            except ValueError:
                return None
            return AuthenticatedPrincipal(
                user_id=user.id,
                tenant_id=tenant.id,
                membership_id=membership.id,
                session_id=auth_session.id,
                subject=user.subject,
                issuer=user.issuer,
                roles=frozenset({role}),
                expires_at=token.expires_at,
                authentication_method=auth_session.authentication_method,
            )
        except Exception as exc:
            raise self._translate_error("resolve_principal", exc) from exc

    async def resolve_active_membership(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        membership_id: uuid.UUID,
    ) -> tuple[UserAccount, TenantMembership] | None:
        """Revalidate current identity and role state for background work."""
        try:
            statement = (
                select(UserAccount, TenantMembership)
                .join(TenantMembership, TenantMembership.user_id == UserAccount.id)
                .join(Tenant, Tenant.id == TenantMembership.tenant_id)
                .where(
                    UserAccount.id == user_id,
                    UserAccount.active.is_(True),
                    TenantMembership.id == membership_id,
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.active.is_(True),
                    Tenant.active.is_(True),
                )
            )
            result = await self.session.execute(statement)
            row = result.one_or_none()
            return (
                cast(tuple[UserAccount, TenantMembership], tuple(row)) if row is not None else None
            )
        except Exception as exc:
            raise self._translate_error("resolve_active_membership", exc) from exc


__all__ = ["IdentityRepository", "hash_token_id"]
