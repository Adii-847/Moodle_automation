"""Structured JSON logging configuration with automated credential and sensitive data redaction."""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Regular expressions for identifying sensitive patterns
SENSITIVE_PATTERNS = [
    (re.compile(r"(wstoken=)([a-zA-Z0-9_-]+)", re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(token[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_-]{10,})([\"']?)", re.IGNORECASE), r"\1[REDACTED_TOKEN]\3"),
    (re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)([^\"'\s,]+)([\"']?)", re.IGNORECASE), r"\1[REDACTED_PASSWORD]\3"),
    (re.compile(r"(authorization[\"']?\s*[:=]\s*[\"']?Bearer\s+)([a-zA-Z0-9_\-\.]+)([\"']?)", re.IGNORECASE), r"\1[REDACTED_AUTH]\3"),
    (re.compile(r"(cookie[\"']?\s*[:=]\s*[\"']?)([^\"'\r\n]+)([\"']?)", re.IGNORECASE), r"\1[REDACTED_COOKIE]\3"),
    (re.compile(r"(MoodleSession=)([a-zA-Z0-9]+)", re.IGNORECASE), r"\1[REDACTED_SESSION]"),
]


def redact_string(text: str) -> str:
    """Sanitize strings by redacting known credential and token patterns."""
    if not isinstance(text, str):
        return text
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(data: Any) -> Any:
    """Recursively redact dictionary keys and string values."""
    sensitive_keys = {"token", "wstoken", "password", "secret", "authorization", "cookie", "session"}
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if str(k).lower() in sensitive_keys:
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_dict(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_dict(item) for item in data]
    elif isinstance(data, str):
        return redact_string(data)
    return data


class StructuredJsonFormatter(logging.Formatter):
    """Custom logging formatter outputting single-line JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        record_dict: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_string(record.getMessage()),
        }

        # Include structured context if present
        for field in ("correlation_id", "assignment_id", "course_id", "job_id", "stage", "error_code"):
            val = getattr(record, field, None)
            if val is not None:
                record_dict[field] = val

        if record.exc_info:
            record_dict["exception"] = redact_string(self.formatException(record.exc_info))

        return json.dumps(record_dict, default=str)


def configure_logging(log_level: str = "INFO", json_format: bool = True) -> None:
    """Configure root logger with structured JSON or console formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to prevent duplicates
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s"))

    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the given name."""
    return logging.getLogger(name)

