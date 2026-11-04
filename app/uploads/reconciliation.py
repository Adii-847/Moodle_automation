"""Authoritative state reconciliation against Moodle after network or uncertain outcomes."""

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import AssignmentModel, UploadAttemptModel, UploadStatus
from app.database.repositories import AssignmentRepository, AuditRepository, UploadAttemptRepository
from app.logging_config import get_logger
from app.moodle.client import MoodleClient
from app.moodle.schemas import MoodleSubmissionStatus, SubmissionState

logger = get_logger(__name__)


async def reconcile_assignment_submission(
    assignment_id: int,
    client: MoodleClient,
    session: Session,
    local_pdf: Optional[Path] = None,
) -> MoodleSubmissionStatus:
    """Query Moodle's authoritative status and synchronize local records without duplicate uploads."""
    assign_repo = AssignmentRepository(session)
    upload_repo = UploadAttemptRepository(session)
    audit_repo = AuditRepository(session)

    assignment = assign_repo.get_by_id(assignment_id)
    if not assignment:
        raise ValueError(f"Assignment id {assignment_id} not found in database.")

    status = await client.get_submission_status(assignment.moodle_assignment_id)

    # Update database record
    assignment.submission_status_moodle = status.status.value
    assignment.grading_status_moodle = status.grading_status.value

    latest_attempt = upload_repo.get_latest_for_assignment(assignment.id)
    if latest_attempt and latest_attempt.upload_status == UploadStatus.UNCONFIRMED.value:
        # Check if file was actually accepted
        if status.submitted_files:
            upload_repo.update_verification(
                latest_attempt.id,
                verified=True,
                status=UploadStatus.UPLOADED_DRAFT.value if status.status == SubmissionState.DRAFT else UploadStatus.FINALIZED.value,
            )
            audit_repo.log(
                event_type="RECONCILIATION_CONFIRMED",
                details={"assignment_id": assignment_id, "files": [f.filename for f in status.submitted_files]},
                assignment_id=assignment.id,
            )
        else:
            upload_repo.update_verification(
                latest_attempt.id,
                verified=False,
                status=UploadStatus.FAILED.value,
                error_message="Reconciliation confirmed no files present in Moodle.",
            )

    session.flush()
    return status

