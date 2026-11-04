"""Retry policies, transient failure classification, and exponential backoff with jitter."""

import random
from typing import Set, Type

from app.moodle.client import (
    MoodleAuthenticationError,
    MoodleNotFoundError,
    MoodlePermissionError,
)

PERMANENT_ERROR_TYPES: Set[Type[Exception]] = {
    MoodleAuthenticationError,
    MoodlePermissionError,
    MoodleNotFoundError,
    ValueError,
    SyntaxError,
    FileNotFoundError,
}


def is_transient_error(error: Exception) -> bool:
    """Classify whether an exception is considered transient and eligible for automatic retry."""
    if any(isinstance(error, exc_type) for exc_type in PERMANENT_ERROR_TYPES):
        return False

    error_str = str(error).lower()
    permanent_keywords = [
        "invalid token",
        "access denied",
        "permission denied",
        "syntax error",
        "file not found",
        "not found",
        "locked",
    ]
    if any(kw in error_str for kw in permanent_keywords):
        return False

    return True


def calculate_backoff_seconds(
    retry_count: int,
    base_seconds: float = 2.0,
    max_seconds: float = 300.0,
    jitter: bool = True,
) -> float:
    """Compute exponential backoff delay with randomized jitter."""
    delay = min(base_seconds * (2 ** retry_count), max_seconds)
    if jitter:
        # Full jitter between 50% and 100% of calculated backoff
        delay = delay * random.uniform(0.5, 1.0)
    return round(delay, 2)

