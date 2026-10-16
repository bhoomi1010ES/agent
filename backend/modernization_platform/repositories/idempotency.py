"""Idempotency repository for persisting and verifying idempotent operations."""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modernization_platform.core.decorators import log_errors
from modernization_platform.db.models.idempotency import IdempotencyRecord
from modernization_platform.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


@log_errors
def compute_request_hash(payload: Any) -> str:
    """Compute deterministic SHA-256 hash of a request payload."""
    try:
        if payload is None:
            serialized = ""
        elif isinstance(payload, (dict, list)):
            serialized = json.dumps(payload, sort_keys=True, default=str)
        else:
            serialized = str(payload)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    except Exception as exc:
        logger.exception("compute_request_hash failed | %s: %s", type(exc).__name__, exc)
        raise


class IdempotencyRepository(BaseRepository[IdempotencyRecord]):
    """Repository operations for IdempotencyRecord persistence."""

    compute_request_hash = staticmethod(compute_request_hash)

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @log_errors
    async def get_record(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        key: str,
    ) -> IdempotencyRecord | None:
        """Lookup an existing idempotency record scoped to tenant, user, action, and key."""
        try:
            stmt = select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.action == action,
                IdempotencyRecord.key == key,
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as exc:
            raise self._translate_error("get_record", exc) from exc

    @log_errors
    async def save_record(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        key: str,
        request_hash: str,
        response_code: int,
        response_body: dict[str, Any],
        resource_id: uuid.UUID | None = None,
    ) -> IdempotencyRecord:
        """Persist a new idempotency record."""
        try:
            record = IdempotencyRecord(
                id=uuid.uuid4(),
                key=key,
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                resource_id=resource_id,
                request_hash=request_hash,
                response_code=response_code,
                response_body=response_body,
                created_at=datetime.now(UTC),
            )
            self.session.add(record)
            await self.session.flush()
            return record
        except Exception as exc:
            raise self._translate_error("save_record", exc) from exc


__all__ = ["IdempotencyRepository", "compute_request_hash"]
