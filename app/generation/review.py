"""Review and safety gating for generated solution plans and source code."""

import ast
from typing import Optional

from app.generation.planner import ProgrammingLanguage, SolutionPlan
from app.generation.solution_generator import GeneratedSolution
from app.logging_config import get_logger

logger = get_logger(__name__)


def validate_python_syntax(code: str) -> tuple[bool, Optional[str]]:
    """Verify that Python source code parses into a valid abstract syntax tree without syntax errors."""
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}, col {e.offset}: {e.msg}"
    except Exception as e:
        return False, f"Failed to parse Python code: {e}"


def review_solution(solution: GeneratedSolution) -> tuple[bool, Optional[str]]:
    """Gating check before execution or artifact inclusion."""
    if not solution.source_code or len(solution.source_code.strip()) == 0:
        return False, "Generated solution source code is empty."

    if solution.language == ProgrammingLanguage.PYTHON:
        valid, err = validate_python_syntax(solution.source_code)
        if not valid:
            logger.error("Generated Python solution failed syntax validation", extra={"error": err})
            return False, err

    return True, None

