"""Submission status and verification helper utilities."""

from pathlib import Path
from typing import Optional

from app.logging_config import get_logger
from app.moodle.client import MoodleClient
from app.moodle.schemas import MoodleFinalizeResult, MoodleSubmissionStatus, MoodleUploadResult, SubmissionState

logger = get_logger(__name__)


async def verify_assignment_state(client: MoodleClient, assignment_id: int) -> MoodleSubmissionStatus:
    """Authoritatively query Moodle for current assignment submission status."""
    status = await client.get_submission_status(assignment_id)
    logger.info(
        "Queried assignment submission status",
        extra={
            "assignment_id": assignment_id,
            "status": status.status.value,
            "can_submit": status.can_submit,
            "file_count": len(status.submitted_files),
        },
    )
    return status


async def upload_and_optionally_finalize(
    client: MoodleClient,
    assignment_id: int,
    file_path: Path,
    auto_finalize: bool = False,
) -> tuple[MoodleUploadResult, Optional[MoodleFinalizeResult]]:
    """Upload draft file and optionally finalize submission if configured."""
    upload_res = await client.upload_submission_file(assignment_id, file_path)
    finalize_res = None
    if upload_res.success and auto_finalize:
        finalize_res = await client.finalize_submission(assignment_id)
    return upload_res, finalize_res

