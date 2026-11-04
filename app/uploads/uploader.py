"""Safe assignment uploader with multi-stage verification and authoritative confirmation."""

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.database.models import (
    ArtifactModel,
    AssignmentModel,
    JobStage,
    JobStatus,
    ProcessingJobModel,
    UploadStatus,
)
from app.database.repositories import (
    ArtifactRepository,
    AssignmentRepository,
    AuditRepository,
    ProcessingJobRepository,
    UploadAttemptRepository,
)
from app.logging_config import get_logger
from app.moodle.client import MoodleClient
from app.moodle.schemas import MoodleSubmissionStatus, SubmissionState
from app.uploads.reconciliation import reconcile_assignment_submission
from app.uploads.verification import is_equivalent_file_already_uploaded, verify_upload_eligibility

logger = get_logger(__name__)


class AssignmentUploader:
    """Manages safe file uploading and submission state verification against Moodle."""

    def __init__(self, client: MoodleClient, session: Session, settings: Optional[AppSettings] = None):
        self.client = client
        self.session = session
        self.settings = settings or get_settings()
        self.assign_repo = AssignmentRepository(session)
        self.artifact_repo = ArtifactRepository(session)
        self.upload_repo = UploadAttemptRepository(session)
        self.job_repo = ProcessingJobRepository(session)
        self.audit_repo = AuditRepository(session)

    async def execute_upload_pipeline(
        self,
        assignment_id: int,
        artifact_id: int,
        job_id: Optional[int] = None,
    ) -> tuple[bool, str, Optional[MoodleSubmissionStatus]]:
        """Run the end-to-end safe upload, verification, and optional finalization pipeline."""
        assignment = self.assign_repo.get_by_id(assignment_id)
        if not assignment:
            return False, f"Assignment ID {assignment_id} not found.", None

        artifact = self.session.get(ArtifactModel, artifact_id)
        if not artifact:
            return False, f"Artifact ID {artifact_id} not found.", None

        pdf_path = Path(artifact.file_path)

        # 1. Authoritative check on Moodle
        try:
            status = await self.client.get_submission_status(assignment.moodle_assignment_id)
        except Exception as e:
            return False, f"Failed to retrieve Moodle status: {e}", None

        # 2. Eligibility verification
        eligible, reason = verify_upload_eligibility(assignment, status, pdf_path, self.settings)
        if not eligible:
            logger.warning(f"Assignment {assignment_id} is ineligible for upload: {reason}")
            return False, reason, status

        # 3. Deduplication check: check if exact file is already in Moodle
        if is_equivalent_file_already_uploaded(status.submitted_files, pdf_path):
            logger.info("Equivalent file already exists in Moodle; skipping upload.")
            return True, "File already present in Moodle.", status

        # 4. Record upload attempt as INITIATED
        attempt_count = len(assignment.upload_attempts) + 1
        attempt = self.upload_repo.record_attempt(
            assignment_id=assignment.id,
            artifact_id=artifact.id,
            attempt_number=attempt_count,
            status=UploadStatus.INITIATED.value,
        )

        # 5. Perform the upload
        try:
            upload_res = await self.client.upload_submission_file(assignment.moodle_assignment_id, pdf_path)
            if not upload_res.success:
                self.upload_repo.update_verification(
                    attempt.id,
                    verified=False,
                    status=UploadStatus.FAILED.value,
                    error_message=upload_res.error_message or "Upload rejected by Moodle.",
                )
                return False, f"Upload failed: {upload_res.error_message}", None
        except Exception as e:
            # Uncertain network outcome
            logger.error(f"Network error during file upload for assignment {assignment_id}: {e}")
            self.upload_repo.update_verification(
                attempt.id,
                verified=False,
                status=UploadStatus.UNCONFIRMED.value,
                error_message=str(e),
            )
            # Reconcile immediately to check if file actually landed
            reconciled = await reconcile_assignment_submission(assignment.id, self.client, self.session, pdf_path)
            return False, f"Upload uncertain, reconciled state: {reconciled.status.value}", reconciled

        # 6. Finalize submission if configured
        finalized_status = SubmissionState.DRAFT
        if self.settings.auto_final_submit:
            logger.info("AUTO_FINAL_SUBMIT is enabled; finalizing submission in Moodle")
            fin_res = await self.client.finalize_submission(assignment.moodle_assignment_id)
            if fin_res.success:
                finalized_status = fin_res.final_status
            else:
                logger.warning(f"Finalization failed: {fin_res.error_message}")

        # 7. Authoritatively verify resulting state from Moodle
        verified_status = await self.client.verify_submission(assignment.moodle_assignment_id)

        is_verified = (
            verified_status.status == SubmissionState.SUBMITTED
            if self.settings.auto_final_submit
            else (len(verified_status.submitted_files) > 0 or verified_status.status in (SubmissionState.DRAFT, SubmissionState.SUBMITTED))
        )

        final_db_status = UploadStatus.FINALIZED.value if verified_status.status == SubmissionState.SUBMITTED else UploadStatus.UPLOADED_DRAFT.value

        self.upload_repo.update_verification(
            attempt.id,
            verified=is_verified,
            status=final_db_status,
        )

        # Update assignment model
        assignment.submission_status_moodle = verified_status.status.value

        if job_id:
            next_stage = JobStage.SUBMITTED.value if verified_status.status == SubmissionState.SUBMITTED else JobStage.VERIFYING.value
            self.job_repo.transition_stage(job_id, next_stage, JobStatus.COMPLETED.value)

        self.audit_repo.log(
            event_type="UPLOAD_VERIFIED",
            details={
                "assignment_id": assignment.id,
                "moodle_id": assignment.moodle_assignment_id,
                "verified": is_verified,
                "status": verified_status.status.value,
            },
            assignment_id=assignment.id,
        )

        logger.info(
            "Upload and verification pipeline completed",
            extra={
                "assignment_id": assignment_id,
                "verified": is_verified,
                "status": verified_status.status.value,
            },
        )

        return is_verified, f"Completed with status: {verified_status.status.value}", verified_status

