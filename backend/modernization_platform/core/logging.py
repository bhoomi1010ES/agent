"""Structured JSON and development console logging with sensitive data redaction."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from modernization_platform.config.settings import Settings
from modernization_platform.core.ids import get_correlation_id

# Regex patterns matching sensitive information to redact from logs
_REDACT_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{10,}"),
    re.compile(r"(?i)(password['\":\s=]+)[^\s,;'\"]+"),
    re.compile(r"(?i)(secret['\":\s=]+)[^\s,;'\"]+"),
    re.compile(r"(?i)(token['\":\s=]+)[^\s,;'\"]+"),
    re.compile(r"(?i)(api[_-]?key['\":\s=]+)[^\s,;'\"]+"),
    re.compile(r"(?i)(authorization['\":\s=]+)[^\s,;'\"]+"),
    re.compile(r"(?i)((?:set-)?cookie['\":\s=]+)[^\r\n]+"),
    re.compile(r"(?i)(client[_-]?secret['\":\s=]+)[^\s,;'\"]+"),
    re.compile(
        r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.DOTALL
    ),
]


class RedactingFilter(logging.Filter):
    """Filter that intercepts log records and redacts credentials, tokens, and secrets."""

    def redact_text(self, text: str) -> str:
        """Replace sensitive patterns with [REDACTED]."""
        try:
            result = text
            for pattern in _REDACT_PATTERNS:
                result = pattern.sub(
                    r"\1[REDACTED]" if r"\1" in pattern.pattern else "[REDACTED]", result
                )
            return result
        except Exception:
            return "[REDACTED_ERROR]"

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize message and string arguments on the log record."""
        try:
            if isinstance(record.msg, str):
                record.msg = self.redact_text(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    clean_dict = {}
                    for k, v in record.args.items():
                        clean_dict[k] = self.redact_text(str(v)) if isinstance(v, str) else v
                    record.args = clean_dict
                elif isinstance(record.args, tuple):
                    clean_list: list[Any] = []
                    for a in record.args:
                        if isinstance(a, dict):
                            clean_list.append(
                                {
                                    k: (self.redact_text(str(v)) if isinstance(v, str) else v)
                                    for k, v in a.items()
                                }
                            )
                        elif isinstance(a, str):
                            clean_list.append(self.redact_text(a))
                        else:
                            clean_list.append(a)
                    record.args = tuple(clean_list)
            return True
        except Exception:
            return True


class JSONFormatter(logging.Formatter):
    """Formatter that outputs structured JSON log entries."""

    def __init__(self, environment: str = "development") -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a single-line JSON string."""
        try:
            log_data: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
                "environment": self.environment,
            }

            # Prepare context for future phases (job_id, module_id, agent_name, worker_id)
            for attr in ("job_id", "module_id", "agent_name", "worker_id", "trace_id", "span_id"):
                val = getattr(record, attr, None)
                if val is not None:
                    log_data[attr] = val

            if record.exc_info and record.exc_info[0]:
                log_data["exception"] = {
                    "type": record.exc_info[0].__name__,
                    "message": str(record.exc_info[1]),
                    "traceback": self.formatException(record.exc_info),
                }

            return json.dumps(log_data, default=str)
        except Exception as exc:
            # Safe fallback if formatting fails
            return json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "ERROR",
                    "logger": "modernization_platform.core.logging",
                    "message": f"Logging formatting failure: {exc}",
                    "environment": self.environment,
                }
            )


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter with correlation ID for local development."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for development console readability."""
        try:
            cid = getattr(record, "correlation_id", None) or get_correlation_id()
            time_str = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
            msg = record.getMessage()
            base = f"[{time_str}] [{record.levelname:<8}] [{cid[:8]}] {record.name}: {msg}"
            if record.exc_info and record.exc_info[0]:
                base += f"\n{self.formatException(record.exc_info)}"
            return base
        except Exception:
            return super().format(record)


def setup_logging(settings: Settings) -> None:
    """Configure platform structured logging without duplicating existing handlers."""
    try:
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

        # Clear existing handlers to prevent duplicated output
        root_logger.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

        # Attach redacting filter
        handler.addFilter(RedactingFilter())

        # Select formatter based on configuration
        if settings.log_format == "json":
            handler.setFormatter(JSONFormatter(environment=settings.environment))
        else:
            handler.setFormatter(ConsoleFormatter())

        root_logger.addHandler(handler)

        # Mute excessively noisy third-party loggers
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    except Exception as exc:
        sys.stderr.write(f"Failed to setup platform logging: {exc}\n")
        raise
