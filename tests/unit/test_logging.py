"""Unit tests for structured logging and credential redaction."""

import json
import logging
from io import StringIO

from app.logging_config import StructuredJsonFormatter, redact_dict, redact_string


def test_redact_sensitive_tokens():
    text = "Request sent to https://moodle.edu/server.php?wstoken=secret_token_12345&foo=bar"
    redacted = redact_string(text)
    assert "secret_token_12345" not in redacted
    assert "[REDACTED_TOKEN]" in redacted


def test_redact_passwords_and_cookies():
    text = '{"username": "student", "password": "SuperSecretPassword123", "cookie": "MoodleSession=abc123xyz"}'
    redacted = redact_string(text)
    assert "SuperSecretPassword123" not in redacted
    assert "abc123xyz" not in redacted


def test_structured_json_formatter():
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Processing with token: wstoken=abc999xyz",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "corr-123"
    record.assignment_id = 456

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test_logger"
    assert parsed["correlation_id"] == "corr-123"
    assert parsed["assignment_id"] == 456
    assert "abc999xyz" not in parsed["message"]
    assert "[REDACTED_TOKEN]" in parsed["message"]

