"""Centralized credential, token, and secret redaction engine."""

import logging
import re
from typing import Any

from modernization_platform.core.decorators import log_errors

logger = logging.getLogger(__name__)

# Sensitive pattern regexes covering API keys, bearer tokens, URLs with passwords, private keys
_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI & generic sk- keys
    (re.compile(r"\bsk-[a-zA-Z0-9_\-]{8,}\b"), "[REDACTED_API_KEY]"),
    # Anthropic prefix keys
    (
        re.compile(r"\b(anthropic-[a-zA-Z0-9_\-]{8,}|ant-[a-zA-Z0-9_\-]{8,})\b"),
        "[REDACTED_API_KEY]",
    ),
    # Bearer tokens
    (re.compile(r"(?i)(bearer\s+)(?!\[REDACTED)[a-zA-Z0-9_\-\.]{8,}"), r"\1[REDACTED_TOKEN]"),
    # Database and HTTP URLs with credentials: postgresql://user:pass@host:port/db
    (
        re.compile(r"([a-zA-Z0-9+_-]+://)([^:]+):(.+?)(@[a-zA-Z0-9.\-_]+(?::\d+)?/[^\s\"']*)"),
        r"\1\2:*****\4",
    ),
    # Generic API key and secret assignments (with negative lookahead to prevent double-redaction)
    (
        re.compile(r"(?i)(api[_-]?key['\":\s=]+)(?!\[REDACTED)[^\s,;'\"]{6,}"),
        r"\1[REDACTED_API_KEY]",
    ),
    (
        re.compile(r"(?i)(client[_-]?secret['\":\s=]+)(?!\[REDACTED)[^\s,;'\"]{6,}"),
        r"\1[REDACTED_SECRET]",
    ),
    (
        re.compile(r"(?i)(password['\":\s=]+)(?!\[REDACTED|\*\*\*\*)[^\s,;'\"]+"),
        r"\1[REDACTED_PASSWORD]",
    ),
    (re.compile(r"(?i)(secret['\":\s=]+)(?!\[REDACTED)[^\s,;'\"]{6,}"), r"\1[REDACTED_SECRET]"),
    (re.compile(r"(?i)(token['\":\s=]+)(?!\[REDACTED)[^\s,;'\"]{6,}"), r"\1[REDACTED_TOKEN]"),
    # Authorization header values (non-bearer)
    (
        re.compile(r"(?i)(authorization['\":\s=]+)(?!bearer|\[REDACTED)[^\s,;'\"]{6,}"),
        r"\1[REDACTED_AUTH]",
    ),
    # Private keys
    (
        re.compile(
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
]

_SENSITIVE_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "password",
        "token",
        "access_token",
        "auth_token",
        "authorization",
        "bearer",
        "client_secret",
        "private_key",
    }
)


@log_errors
def redact_string(text: str) -> str:
    """Scrub sensitive credentials, tokens, and URLs from a raw text string."""
    try:
        if not text:
            return text
        result = text
        for pattern, replacement in _REDACTION_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
    except Exception as exc:
        logger.exception("redact_string failed | %s: %s", type(exc).__name__, exc)
        return "[REDACTED_ERROR]"


@log_errors
def redact_data(obj: Any) -> Any:
    """Recursively scrub sensitive keys and string values in nested dictionaries and collections."""
    try:
        if isinstance(obj, str):
            return redact_string(obj)
        if isinstance(obj, dict):
            sanitized: dict[str, Any] = {}
            for k, v in obj.items():
                k_str = str(k).lower().strip()
                if any(s in k_str for s in _SENSITIVE_KEY_NAMES):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = redact_data(v)
            return sanitized
        if isinstance(obj, list):
            return [redact_data(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(redact_data(item) for item in obj)
        if isinstance(obj, set):
            return {redact_data(item) for item in obj}
        return obj
    except Exception as exc:
        logger.exception("redact_data failed | %s: %s", type(exc).__name__, exc)
        return "[REDACTED_ERROR]"


@log_errors
def redact_exception(exc: Exception) -> str:
    """Safely format an exception without leaking credentials from connection strings or messages."""
    try:
        raw_msg = f"{type(exc).__name__}: {exc}"
        return redact_string(raw_msg)
    except Exception as err:
        logger.exception("redact_exception failed | %s: %s", type(err).__name__, err)
        return "[REDACTED_EXCEPTION]"


__all__ = ["redact_data", "redact_exception", "redact_string"]
