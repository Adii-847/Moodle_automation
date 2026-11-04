"""Path traversal protection, boundary validation, and input sanitization."""

from pathlib import Path


class SecurityViolationError(Exception):
    """Raised when an operation breaches security boundaries or attempts path traversal."""
    pass


def validate_safe_path(target_path: Path, allowed_root: Path) -> Path:
    """Ensure that the target path resolves strictly within the allowed workspace boundary."""
    root_resolved = allowed_root.resolve()
    target_resolved = target_path.resolve()

    try:
        target_resolved.relative_to(root_resolved)
    except ValueError:
        raise SecurityViolationError(
            f"Path traversal detected: '{target_path}' is outside permitted directory '{allowed_root}'."
        )

    return target_resolved


def sanitize_input_text(text: str) -> str:
    """Strip dangerous control characters and null bytes from external inputs."""
    if not text:
        return ""
    # Strip null bytes and non-printable control characters (except newline, carriage return, tab)
    return "".join(ch for ch in text if ch in ("\n", "\r", "\t") or (ord(ch) >= 32 and ord(ch) != 127))

