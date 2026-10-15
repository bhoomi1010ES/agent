"""Identifier utilities and correlation ID management."""

import logging
import re
import uuid
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Correlation ID pattern: 1-64 characters, alphanumeric, hyphens, and underscores only
_CORRELATION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

# Context variable to hold request correlation ID across async execution contexts
_correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def is_valid_correlation_id(value: str | None) -> bool:
    """Validate correlation ID format and length to prevent header injection and log pollution."""
    try:
        if not value:
            return False
        return bool(_CORRELATION_ID_PATTERN.match(value))
    except Exception as exc:
        logger.exception("is_valid_correlation_id failed | %s: %s", type(exc).__name__, exc)
        return False


def generate_correlation_id() -> str:
    """Generate a new UUIDv4 string for request correlation."""
    try:
        return str(uuid.uuid4())
    except Exception as exc:
        logger.exception("generate_correlation_id failed | %s: %s", type(exc).__name__, exc)
        raise


def get_correlation_id() -> str:
    """Retrieve current correlation ID from context, or generate a fresh one if unset."""
    try:
        cid = _correlation_id_ctx.get()
        if not cid:
            cid = generate_correlation_id()
            _correlation_id_ctx.set(cid)
        return cid
    except Exception as exc:
        logger.exception("get_correlation_id failed | %s: %s", type(exc).__name__, exc)
        return generate_correlation_id()


def set_correlation_id(correlation_id: str) -> str:
    """Validate and set the correlation ID in the current async context."""
    try:
        cid = (
            correlation_id if is_valid_correlation_id(correlation_id) else generate_correlation_id()
        )
        _correlation_id_ctx.set(cid)
        return cid
    except Exception as exc:
        logger.exception("set_correlation_id failed | %s: %s", type(exc).__name__, exc)
        fallback = generate_correlation_id()
        _correlation_id_ctx.set(fallback)
        return fallback
