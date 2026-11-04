"""Execution validation data models and output verification."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    is_success: bool = False
    error_message: Optional[str] = None


def verify_execution(result: ExecutionResult, expected_output: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Determine whether program execution concluded successfully and matches expected results."""
    if result.timed_out:
        return False, "Program execution timed out."

    if result.exit_code != 0:
        return False, f"Program exited with non-zero status code: {result.exit_code}."

    if expected_output:
        exp_clean = expected_output.strip().lower()
        std_clean = result.stdout.strip().lower()
        if exp_clean not in std_clean:
            return False, f"Expected output '{expected_output}' was not found in standard output."

    return True, None

