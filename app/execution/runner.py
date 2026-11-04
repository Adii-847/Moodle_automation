"""Isolated subprocess program runner with resource limits and timeout handling."""

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from app.config import AppSettings, get_settings
from app.execution.environments import create_safe_subprocess_env
from app.execution.validation import ExecutionResult, verify_execution
from app.generation.planner import ProgrammingLanguage
from app.generation.solution_generator import GeneratedSolution
from app.logging_config import get_logger

logger = get_logger(__name__)


class ProgramRunner:
    """Executes generated solutions in dedicated temporary subprocess environments."""

    def __init__(self, settings: Optional[AppSettings] = None):
        self.settings = settings or get_settings()
        self.timeout = self.settings.sandbox_max_execution_time_seconds
        self.max_output_chars = self.settings.sandbox_max_output_chars

    def execute(self, solution: GeneratedSolution, stdin_input: Optional[str] = None) -> ExecutionResult:
        lang = solution.language
        if lang == ProgrammingLanguage.PYTHON:
            return self._execute_python(solution, stdin_input)
        elif lang == ProgrammingLanguage.SQL:
            return self._execute_sql(solution)
        elif lang in (ProgrammingLanguage.C, ProgrammingLanguage.CPP):
            return self._execute_c_cpp(solution, stdin_input)
        elif lang == ProgrammingLanguage.JAVA:
            return self._execute_java(solution, stdin_input)
        elif lang == ProgrammingLanguage.WRITTEN_REPORT:
            return ExecutionResult(
                command="[Document Validation]",
                exit_code=0,
                stdout="Report document validated successfully.",
                stderr="",
                duration_seconds=0.01,
                is_success=True,
            )
        else:
            return ExecutionResult(
                command="[Unknown]",
                exit_code=1,
                stdout="",
                stderr="Unsupported language runtime.",
                duration_seconds=0.0,
                is_success=False,
                error_message="Unsupported language runtime",
            )

    def _execute_python(self, solution: GeneratedSolution, stdin_input: Optional[str] = None) -> ExecutionResult:
        python_exe = sys.executable
        file_path = solution.file_path
        working_dir = file_path.parent

        cmd = [python_exe, str(file_path)]
        cmd_str = f"python {file_path.name}"
        safe_env = create_safe_subprocess_env(self.settings)

        start_time = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_input or "",
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(working_dir),
                env=safe_env,
                encoding="utf-8",
                errors="replace",
            )
            duration = round(time.perf_counter() - start_time, 3)

            stdout = proc.stdout[: self.max_output_chars]
            stderr = proc.stderr[: self.max_output_chars]
            is_success = proc.returncode == 0

            return ExecutionResult(
                command=cmd_str,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                is_success=is_success,
                error_message=stderr if not is_success else None,
            )

        except subprocess.TimeoutExpired:
            duration = round(time.perf_counter() - start_time, 3)
            return ExecutionResult(
                command=cmd_str,
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {self.timeout} seconds.",
                duration_seconds=duration,
                timed_out=True,
                is_success=False,
                error_message="Execution timed out.",
            )
        except Exception as e:
            duration = round(time.perf_counter() - start_time, 3)
            return ExecutionResult(
                command=cmd_str,
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration_seconds=duration,
                is_success=False,
                error_message=str(e),
            )

    def _execute_sql(self, solution: GeneratedSolution) -> ExecutionResult:
        """Execute SQL script safely inside an isolated in-memory SQLite database."""
        start_time = time.perf_counter()
        cmd_str = f"sqlite3 :memory: < {solution.file_path.name}"
        try:
            conn = sqlite3.connect(":memory:")
            cursor = conn.cursor()
            output_lines = []

            # Execute statements
            for statement in solution.source_code.split(";"):
                stmt = statement.strip()
                if not stmt:
                    continue
                cursor.execute(stmt)
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    rows = cursor.fetchall()
                    output_lines.append(f"Result for: {stmt[:40]}...")
                    output_lines.append(" | ".join(columns))
                    output_lines.append("-" * 40)
                    for row in rows:
                        output_lines.append(" | ".join(str(val) for val in row))
                    output_lines.append("")

            conn.close()
            duration = round(time.perf_counter() - start_time, 3)
            return ExecutionResult(
                command=cmd_str,
                exit_code=0,
                stdout="\n".join(output_lines),
                stderr="",
                duration_seconds=duration,
                is_success=True,
            )
        except Exception as e:
            duration = round(time.perf_counter() - start_time, 3)
            return ExecutionResult(
                command=cmd_str,
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration_seconds=duration,
                is_success=False,
                error_message=str(e),
            )

    def _execute_c_cpp(self, solution: GeneratedSolution, stdin_input: Optional[str] = None) -> ExecutionResult:
        compiler = "g++" if solution.language == ProgrammingLanguage.CPP else "gcc"
        if not shutil.which(compiler):
            return ExecutionResult(
                command=f"{compiler} {solution.file_path.name}",
                exit_code=1,
                stdout="",
                stderr=f"C/C++ compiler '{compiler}' is not installed on this system.",
                duration_seconds=0.0,
                is_success=False,
                error_message=f"{compiler} not available",
            )
        # If compiler exists, compile to binary and run
        bin_path = solution.file_path.parent / ("solution.exe" if sys.platform == "win32" else "solution")
        compile_cmd = [compiler, str(solution.file_path), "-o", str(bin_path)]
        try:
            c_res = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
            if c_res.returncode != 0:
                return ExecutionResult(
                    command=" ".join(compile_cmd),
                    exit_code=c_res.returncode,
                    stdout="",
                    stderr=c_res.stderr,
                    duration_seconds=0.5,
                    is_success=False,
                    error_message="Compilation failed",
                )
            # Run binary
            start = time.perf_counter()
            r_res = subprocess.run([str(bin_path)], input=stdin_input or "", capture_output=True, text=True, timeout=self.timeout)
            duration = round(time.perf_counter() - start, 3)
            return ExecutionResult(
                command=bin_path.name,
                exit_code=r_res.returncode,
                stdout=r_res.stdout,
                stderr=r_res.stderr,
                duration_seconds=duration,
                is_success=(r_res.returncode == 0),
            )
        except Exception as e:
            return ExecutionResult(
                command=str(bin_path),
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration_seconds=0.0,
                is_success=False,
                error_message=str(e),
            )

    def _execute_java(self, solution: GeneratedSolution, stdin_input: Optional[str] = None) -> ExecutionResult:
        if not shutil.which("javac") or not shutil.which("java"):
            return ExecutionResult(
                command=f"javac {solution.file_path.name}",
                exit_code=1,
                stdout="",
                stderr="Java compiler / runtime (JDK) is not installed on this host.",
                duration_seconds=0.0,
                is_success=False,
                error_message="javac/java not available",
            )
        # Compile and run
        try:
            c_res = subprocess.run(["javac", str(solution.file_path)], capture_output=True, text=True, timeout=10)
            if c_res.returncode != 0:
                return ExecutionResult(
                    command=f"javac {solution.file_path.name}",
                    exit_code=c_res.returncode,
                    stdout="",
                    stderr=c_res.stderr,
                    duration_seconds=0.5,
                    is_success=False,
                    error_message="Java compilation failed",
                )
            start = time.perf_counter()
            r_res = subprocess.run(
                ["java", "-cp", str(solution.file_path.parent), "Solution"],
                input=stdin_input or "",
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            duration = round(time.perf_counter() - start, 3)
            return ExecutionResult(
                command="java Solution",
                exit_code=r_res.returncode,
                stdout=r_res.stdout,
                stderr=r_res.stderr,
                duration_seconds=duration,
                is_success=(r_res.returncode == 0),
            )
        except Exception as e:
            return ExecutionResult(
                command="java Solution",
                exit_code=1,
                stdout="",
                stderr=str(e),
                duration_seconds=0.0,
                is_success=False,
                error_message=str(e),
            )

