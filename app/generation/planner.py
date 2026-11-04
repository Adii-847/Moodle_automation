"""Solution planning, language classification, and instruction analysis."""

import re
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ProgrammingLanguage(str, Enum):
    PYTHON = "python"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SQL = "sql"
    WRITTEN_REPORT = "written_report"
    UNKNOWN = "unknown"


class TestCase(BaseModel):
    input_data: str
    expected_output: Optional[str] = None
    description: Optional[str] = None


class SolutionPlan(BaseModel):
    assignment_id: int
    title: str
    language: ProgrammingLanguage
    file_extension: str
    objective: str
    input_requirements: str
    expected_output: str
    constraints: List[str] = Field(default_factory=list)
    sample_tests: List[TestCase] = Field(default_factory=list)
    required_sections: List[str] = Field(default_factory=lambda: ["Problem Statement", "Source Code", "Execution Output"])
    requires_manual_review: bool = False
    review_reason: Optional[str] = None


def detect_language(title: str, description: str) -> ProgrammingLanguage:
    """Classify the intended programming language or written format from instructions."""
    combined = f"{title} {description}".lower()

    # Direct language mentions
    if re.search(r"\b(python|python3|py)\b", combined):
        return ProgrammingLanguage.PYTHON
    if re.search(r"\b(c\+\+|cpp)\b", combined):
        return ProgrammingLanguage.CPP
    if re.search(r"\b(c\s+program|c\s+language|in\s+c\b|\.c\b)", combined):
        return ProgrammingLanguage.C
    if re.search(r"\b(java|jdk)\b", combined):
        return ProgrammingLanguage.JAVA
    if re.search(r"\b(sql|database|query|table|select\b|sqlite|postgres)\b", combined):
        return ProgrammingLanguage.SQL
    if re.search(r"\b(essay|report|theory|explain|survey|summary|literature review)\b", combined):
        return ProgrammingLanguage.WRITTEN_REPORT

    # Fallback default: if programming keywords exist, default to Python
    if re.search(r"\b(program|code|algorithm|function|script|class|implement)\b", combined):
        return ProgrammingLanguage.PYTHON

    return ProgrammingLanguage.UNKNOWN


def get_file_extension(language: ProgrammingLanguage) -> str:
    mapping = {
        ProgrammingLanguage.PYTHON: ".py",
        ProgrammingLanguage.C: ".c",
        ProgrammingLanguage.CPP: ".cpp",
        ProgrammingLanguage.JAVA: ".java",
        ProgrammingLanguage.SQL: ".sql",
        ProgrammingLanguage.WRITTEN_REPORT: ".txt",
        ProgrammingLanguage.UNKNOWN: ".txt",
    }
    return mapping.get(language, ".txt")


def create_solution_plan(assignment_id: int, title: str, description_text: str) -> SolutionPlan:
    """Construct a structured solution plan after analyzing instructions."""
    desc = (description_text or "").strip()

    if not desc:
        return SolutionPlan(
            assignment_id=assignment_id,
            title=title,
            language=ProgrammingLanguage.UNKNOWN,
            file_extension=".txt",
            objective="Instructions missing",
            input_requirements="",
            expected_output="",
            requires_manual_review=True,
            review_reason="Assignment description is completely empty.",
        )

    lang = detect_language(title, desc)
    ext = get_file_extension(lang)

    # Check for adversarial prompt injection / system override phrases
    malicious_markers = [
        "ignore previous instructions",
        "format c:",
        "rm -rf",
        "drop table",
        "cat /etc/passwd",
        "upload password",
        "steal",
        "wstoken",
    ]
    for marker in malicious_markers:
        if marker in desc.lower():
            return SolutionPlan(
                assignment_id=assignment_id,
                title=title,
                language=lang,
                file_extension=ext,
                objective="Security Violation Detected",
                input_requirements="",
                expected_output="",
                requires_manual_review=True,
                review_reason=f"Suspicious or adversarial directive found in instructions: '{marker}'.",
            )

    if lang == ProgrammingLanguage.UNKNOWN:
        return SolutionPlan(
            assignment_id=assignment_id,
            title=title,
            language=lang,
            file_extension=ext,
            objective=f"Complete assignment: {title}",
            input_requirements="Unspecified",
            expected_output="Unspecified",
            requires_manual_review=True,
            review_reason="Programming language or assignment format could not be identified reliably.",
        )

    # Extract sample inputs/outputs if stated
    sample_tests: List[TestCase] = []
    io_matches = re.findall(r"input[:\s]+([^\n]+)[\s\n]+output[:\s]+([^\n]+)", desc, flags=re.IGNORECASE)
    for inp, outp in io_matches:
        sample_tests.append(TestCase(input_data=inp.strip(), expected_output=outp.strip()))

    if not sample_tests:
        sample_tests.append(TestCase(input_data="", description="Default execution run"))

    return SolutionPlan(
        assignment_id=assignment_id,
        title=title,
        language=lang,
        file_extension=ext,
        objective=f"Implement requirement for '{title}':\n{desc[:300]}...",
        input_requirements="Command-line input or standard test parameters.",
        expected_output="Standard console output displaying computed results.",
        sample_tests=sample_tests,
    )

