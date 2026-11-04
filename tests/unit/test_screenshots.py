"""Unit tests for code and terminal output screenshot generation and validation."""

from pathlib import Path
import pytest

from app.execution.validation import ExecutionResult
from app.generation.planner import ProgrammingLanguage
from app.screenshots.code_capture import render_code_to_image
from app.screenshots.image_processing import compute_file_sha256, get_image_metadata, validate_image_file
from app.screenshots.output_capture import render_terminal_output_to_image


def test_code_screenshot_generation(tmp_path):
    code = """def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(factorial(5))
"""
    out_path = tmp_path / "code.png"
    images = render_code_to_image(
        source_code=code,
        output_path=out_path,
        language=ProgrammingLanguage.PYTHON,
        title="solution.py",
    )

    assert len(images) == 1
    target = images[0]
    assert target.exists()

    valid, err = validate_image_file(target)
    assert valid is True
    assert err is None

    meta = get_image_metadata(target)
    assert meta["width"] >= 800
    assert meta["height"] >= 100
    assert meta["format"] == "PNG"


def test_output_screenshot_generation(tmp_path):
    result = ExecutionResult(
        command="python solution.py",
        exit_code=0,
        stdout="=== Factorial Calculation Program ===\nfactorial(5) = 120\n",
        stderr="",
        duration_seconds=0.12,
        is_success=True,
    )

    out_path = tmp_path / "output.png"
    rendered = render_terminal_output_to_image(result, out_path)

    assert rendered.exists()
    valid, err = validate_image_file(rendered)
    assert valid is True
    assert err is None


def test_image_validation_empty_and_missing(tmp_path):
    missing_path = tmp_path / "nonexistent.png"
    valid, err = validate_image_file(missing_path)
    assert valid is False
    assert "not found" in err

    empty_path = tmp_path / "empty.png"
    empty_path.write_bytes(b"")
    valid, err = validate_image_file(empty_path)
    assert valid is False
    assert "empty" in err


def test_image_checksum(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Antigravity Screenshot Test", encoding="utf-8")
    digest = compute_file_sha256(f)
    assert len(digest) == 64
    assert digest == compute_file_sha256(f)

