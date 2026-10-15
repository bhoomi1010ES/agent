"""Tenant, identity, membership, session, and job-access persistence models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from modernization_platform.db.base import Base, ImmutableTimestampMixin, TimestampMixin
from modernization_platform.db.types import GUID, UTCDateTime


class Tenant(Base, TimestampMixin):
    """Organization boundary used for resource isolation."""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserAccount(Base, TimestampMixin):
    """Minimal local identity linked to an external issuer and stable subject."""

    __tablename__ = "user_account"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_user_account_issuer_subject"),)


class TenantMembership(Base, TimestampMixin):
    """A user's current role inside one tenant."""

    __tablename__ = "tenant_membership"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_tenant_user"),
        CheckConstraint(
            "role IN ('owner', 'reviewer', 'approver', 'admin')",
            name="role_allowed",
        ),
        Index("ix_tenant_membership_lookup", "tenant_id", "user_id", "active"),
    )


class AuthSession(Base, ImmutableTimestampMixin):
    """Allowlisted external access-token session supporting explicit revocation."""

    __tablename__ = "auth_session"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    token_id_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    authentication_method: Mapped[str] = mapped_column(
        String(50), nullable=False, default="oidc_jwt"
    )

    __table_args__ = (Index("ix_auth_session_active", "tenant_id", "user_id", "revoked_at"),)


class JobMember(Base, ImmutableTimestampMixin):
    """Explicit access grant connecting a tenant membership to a job."""

    __tablename__ = "job_member"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("tenant_membership.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("job_id", "membership_id", name="uq_job_member_job_membership"),
    )


__all__ = ["AuthSession", "JobMember", "Tenant", "TenantMembership", "UserAccount"]
