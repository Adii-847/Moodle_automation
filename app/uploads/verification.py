"""Pre-upload eligibility checks and post-upload verification utilities."""

from pathlib import Path
from typing import Optional

from app.config import AppSettings
from app.database.models import AssignmentModel
from app.moodle.schemas import MoodleFile, MoodleSubmissionStatus, SubmissionState


def verify_upload_eligibility(
    assignment: AssignmentModel,
    status: MoodleSubmissionStatus,
    pdf_path: Path,
    settings: AppSettings,
) -> tuple[bool, Optional[str]]:
    """Strictly verify that the assignment is in a valid state to receive an upload."""
    if not pdf_path.exists():
        return False, f"Submission PDF does not exist at path: {pdf_path}"

    file_size = pdf_path.stat().st_size
    if file_size == 0:
        return False, "Submission PDF file is 0 bytes."

    # Check size limit against assignment max bytes and system config max bytes
    effective_max_bytes = min(assignment.max_file_size_bytes, settings.max_file_size_mb * 1024 * 1024)
    if file_size > effective_max_bytes:
        return False, f"PDF file size ({file_size} bytes) exceeds maximum limit ({effective_max_bytes} bytes)."

    # Check accepted file types
    if assignment.accepted_file_types:
        types = [t.strip().lower() for t in assignment.accepted_file_types.split(",") if t.strip()]
        if types and not any(pdf_path.name.lower().endswith(t) for t in types):
            return False, f"PDF extension is not in accepted types: {assignment.accepted_file_types}."

    # Check Moodle submission status
    if status.locked:
        return False, "Assignment submissions are locked in Moodle."

    if not status.can_submit and not status.can_edit:
        return False, "Student does not have permission to submit or edit this assignment."

    if status.status == SubmissionState.SUBMITTED and not settings.auto_final_submit:
        return False, "Assignment is already submitted for grading and auto-overwrite is disabled."

    return True, None


def is_equivalent_file_already_uploaded(moodle_files: list[MoodleFile], local_pdf: Path) -> bool:
    """Check if an equivalent file (by filename and exact size) is already present in Moodle."""
    local_size = local_pdf.stat().st_size
    local_name = local_pdf.name
    for mf in moodle_files:
        if mf.filename == local_name and mf.filesize == local_size:
            return True
    return False

