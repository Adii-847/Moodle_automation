"""Unit tests for isolated program execution, sandboxing, and validation."""

import os
import pytest

from app.config import AppSettings
from app.execution.environments import create_safe_subprocess_env
from app.execution.runner import ProgramRunner
from app.execution.validation import verify_execution
from app.generation.planner import ProgrammingLanguage, SolutionPlan
from app.generation.solution_generator import GeneratedSolution


def test_safe_subprocess_env_redaction():
    os.environ["MOODLE_API_TOKEN"] = "super_secret_token"
    os.environ["SECRET_KEY"] = "very_secret"
    os.environ["DATABASE_URL"] = "postgres://pass"

    settings = AppSettings()
    clean_env = create_safe_subprocess_env(settings)

    assert "MOODLE_API_TOKEN" not in clean_env
    assert "SECRET_KEY" not in clean_env
    assert "DATABASE_URL" not in clean_env


def test_python_program_execution_success(tmp_path):
    code = """print('=== Execution Output ===')
print('Result: 42')
"""
    file_path = tmp_path / "solution.py"
    file_path.write_text(code, encoding="utf-8")

    plan = SolutionPlan(
        assignment_id=1,
        title="Test Math",
        language=ProgrammingLanguage.PYTHON,
        file_extension=".py",
        objective="Print 42",
        input_requirements="",
        expected_output="Result: 42",
    )
    solution = GeneratedSolution(
        assignment_id=1,
        language=ProgrammingLanguage.PYTHON,
        source_code=code,
        file_path=file_path,
        checksum="dummy_checksum",
        plan=plan,
    )

    runner = ProgramRunner()
    result = runner.execute(solution)

    assert result.is_success is True
    assert result.exit_code == 0
    assert "Result: 42" in result.stdout
    assert result.duration_seconds >= 0.0

    valid, err = verify_execution(result, expected_output="Result: 42")
    assert valid is True
    assert err is None


def test_python_program_execution_timeout(tmp_path):
    code = """import time
while True:
    time.sleep(0.1)
"""
    file_path = tmp_path / "hang.py"
    file_path.write_text(code, encoding="utf-8")

    settings = AppSettings(SANDBOX_MAX_EXECUTION_TIME_SECONDS=1)
    plan = SolutionPlan(
        assignment_id=2,
        title="Hang Test",
        language=ProgrammingLanguage.PYTHON,
        file_extension=".py",
        objective="Test timeout",
        input_requirements="",
        expected_output="",
    )
    solution = GeneratedSolution(
        assignment_id=2,
        language=ProgrammingLanguage.PYTHON,
        source_code=code,
        file_path=file_path,
        checksum="dummy",
        plan=plan,
    )

    runner = ProgramRunner(settings)
    result = runner.execute(solution)

    assert result.timed_out is True
    assert result.is_success is False
    assert result.exit_code != 0


def test_python_program_execution_failure(tmp_path):
    code = """import sys
print('About to crash...', file=sys.stderr)
sys.exit(3)
"""
    file_path = tmp_path / "fail.py"
    file_path.write_text(code, encoding="utf-8")

    plan = SolutionPlan(
        assignment_id=3,
        title="Fail Test",
        language=ProgrammingLanguage.PYTHON,
        file_extension=".py",
        objective="Test failure",
        input_requirements="",
        expected_output="",
    )
    solution = GeneratedSolution(
        assignment_id=3,
        language=ProgrammingLanguage.PYTHON,
        source_code=code,
        file_path=file_path,
        checksum="dummy",
        plan=plan,
    )

    runner = ProgramRunner()
    result = runner.execute(solution)

    assert result.is_success is False
    assert result.exit_code == 3
    assert "About to crash..." in result.stderr

    valid, err = verify_execution(result)
    assert valid is False


def test_sql_execution(tmp_path):
    sql_code = """CREATE TABLE items (id INT, name TEXT);
INSERT INTO items VALUES (1, 'Widget');
SELECT * FROM items;
"""
    file_path = tmp_path / "query.sql"
    file_path.write_text(sql_code, encoding="utf-8")

    plan = SolutionPlan(
        assignment_id=4,
        title="SQL Test",
        language=ProgrammingLanguage.SQL,
        file_extension=".sql",
        objective="Test SQL in memory",
        input_requirements="",
        expected_output="",
    )
    solution = GeneratedSolution(
        assignment_id=4,
        language=ProgrammingLanguage.SQL,
        source_code=sql_code,
        file_path=file_path,
        checksum="dummy",
        plan=plan,
    )

    runner = ProgramRunner()
    result = runner.execute(solution)

    assert result.is_success is True
    assert "Widget" in result.stdout

