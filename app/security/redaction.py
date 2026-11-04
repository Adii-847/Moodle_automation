"""String and dictionary sanitization helpers for security audit compliance."""

from app.logging_config import redact_dict, redact_string


def sanitize_log_message(msg: str) -> str:
    """Convenience alias for string redaction."""
    return redact_string(msg)


def sanitize_payload(payload: dict) -> dict:
    """Convenience alias for payload dictionary redaction."""
    return redact_dict(payload)

