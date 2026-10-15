"""Unit tests for structured logging, formatting, and sensitive data redaction."""

import json
import logging

from modernization_platform.config.settings import Settings
from modernization_platform.core.ids import set_correlation_id
from modernization_platform.core.logging import (
    ConsoleFormatter,
    JSONFormatter,
    RedactingFilter,
    setup_logging,
)


def test_redacting_filter_masks_secrets() -> None:
    """Verify RedactingFilter scrubs Bearer tokens, passwords, and API keys."""
    filter_obj = RedactingFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Connecting with password='superSecretPassword123' and api_key=ak_live_9988776655443322",
        args=(),
        exc_info=None,
    )
    filter_obj.filter(record)

    assert "superSecretPassword123" not in record.msg
    assert "ak_live_9988776655443322" not in record.msg
    assert "[REDACTED]" in record.msg


def test_redacting_filter_bearer_token() -> None:
    """Verify Bearer tokens are redacted."""
    filter_obj = RedactingFilter()
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.testTokenData"
    clean = filter_obj.redact_text(text)
    assert "eyJhbGciOiJIUzI1Ni" not in clean
    assert "[REDACTED]" in clean


def test_json_formatter_structure() -> None:
    """Verify JSONFormatter emits structured JSON containing all mandatory fields."""
    set_correlation_id("test-correlation-uuid-1234")
    formatter = JSONFormatter(environment="test")
    record = logging.LogRecord(
        name="modernization_platform.test",
        level=logging.ERROR,
        pathname="app.py",
        lineno=42,
        msg="Sample error event",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "ERROR"
    assert data["logger"] == "modernization_platform.test"
    assert data["message"] == "Sample error event"
    assert data["correlation_id"] == "test-correlation-uuid-1234"
    assert data["environment"] == "test"
    assert "timestamp" in data


def test_console_formatter_output() -> None:
    """Verify ConsoleFormatter produces human-readable text."""
    set_correlation_id("corr-abc-123")
    formatter = ConsoleFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="app.py",
        lineno=10,
        msg="Development message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "INFO" in output
    assert "corr-abc" in output
    assert "Development message" in output


def test_setup_logging_avoids_duplicate_handlers() -> None:
    """Verify setup_logging configures root logger without multiplying handlers."""
    settings = Settings(log_level="DEBUG", log_format="json")
    setup_logging(settings)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG

    # Run setup again
    setup_logging(settings)
    assert len(root.handlers) == 1


def test_redacting_filter_dict_and_tuple_args() -> None:
    """Verify RedactingFilter cleans tuple and dict log arguments."""
    filter_obj = RedactingFilter()

    # Tuple args
    rec1 = logging.LogRecord(
        "test", logging.INFO, "f.py", 1, "User login %s", ("password=SecretPassword1",), None
    )
    filter_obj.filter(rec1)
    assert isinstance(rec1.args, tuple)
    assert "[REDACTED]" in str(rec1.args[0])

    # Dict passed as mapping arg to LogRecord
    rec2 = logging.LogRecord(
        "test",
        logging.INFO,
        "f.py",
        1,
        "Config dict %(secret)s",
        ({"secret": "token=SecretToken99"},),
        None,
    )
    filter_obj.filter(rec2)
    assert isinstance(rec2.args, dict)
    assert "[REDACTED]" in str(rec2.args["secret"])

    # Direct dict args
    rec3 = logging.LogRecord("test", logging.INFO, "f.py", 1, "Config dict", (), None)
    rec3.args = {"secret": "token=SecretToken99"}
    filter_obj.filter(rec3)
    assert isinstance(rec3.args, dict)
    assert "[REDACTED]" in str(rec3.args["secret"])


def test_json_formatter_with_exception_and_extra_fields() -> None:
    """Verify JSONFormatter includes exception tracebacks and multi-agent context fields."""
    import sys

    formatter = JSONFormatter(environment="test")
    try:
        raise ValueError("Simulated failure for json format")
    except ValueError:
        exc_info = sys.exc_info()

    rec = logging.LogRecord("test", logging.ERROR, "f.py", 1, "An error", (), exc_info)
    rec.job_id = "job-123"
    rec.module_id = "mod-456"
    rec.agent_name = "Intake"
    rec.worker_id = "worker-1"

    output = formatter.format(rec)
    data = json.loads(output)
    assert data["job_id"] == "job-123"
    assert data["module_id"] == "mod-456"
    assert data["agent_name"] == "Intake"
    assert data["worker_id"] == "worker-1"
    assert "exception" in data
    assert data["exception"]["type"] == "ValueError"
    assert "Simulated failure for json format" in data["exception"]["message"]
