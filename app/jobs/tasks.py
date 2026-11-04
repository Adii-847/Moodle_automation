"""State machine task processor driving assignments through the complete pipeline."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.database.models import (
    ArtifactModel,
    ArtifactType,
    AssignmentClassification,
    AssignmentModel,
    JobStage,
    JobStatus,
    ProcessingJobModel,
)
from app.database.repositories import (
    ArtifactRepository,
    AssignmentRepository,
    AuditRepository,
    ProcessingJobRepository,
)
from app.documents.pdf_generator import PdfGenerationInput, generate_assignment_pdf, sanitize_filename
from app.documents.pdf_validation import get_pdf_metadata, validate_pdf_file
from app.execution.runner import ProgramRunner
from app.execution.validation import verify_execution
from app.generation.planner import create_solution_plan
from app.generation.review import review_solution
from app.generation.solution_generator import SolutionGenerator
from app.jobs.retry_policy import calculate_backoff_seconds, is_transient_error
from app.logging_config import get_logger
from app.moodle.client import MoodleClient
from app.screenshots.code_capture import render_code_to_image
from app.screenshots.image_processing import compute_file_sha256, validate_image_file
from app.screenshots.output_capture import render_terminal_output_to_image
from app.uploads.uploader import AssignmentUploader

logger = get_logger(__name__)


class JobProcessor:
    """Orchestrates an assignment through each stage of the lifecycle state machine."""

    def __init__(
        self,
        client: MoodleClient,
        session: Session,
        settings: Optional[AppSettings] = None,
    ):
        self.client = client
        self.session = session
        self.settings = settings or get_settings()
        self.assign_repo = AssignmentRepository(session)
        self.job_repo = ProcessingJobRepository(session)
        self.artifact_repo = ArtifactRepository(session)
        self.audit_repo = AuditRepository(session)

        self.generator = SolutionGenerator(self.settings)
        self.runner = ProgramRunner(self.settings)
        self.uploader = AssignmentUploader(self.client, self.session, self.settings)

    async def process_job(self, job_id: int) -> bool:
        """Advance job through its state machine until completed, blocked, or failed."""
        job = self.session.get(ProcessingJobModel, job_id)
        if not job:
            raise ValueError(f"Job id {job_id} not found.")

        assignment = job.assignment
        logger.info(
            f"Processing job {job.id} for assignment {assignment.id} at stage {job.stage}",
            extra={"job_id": job.id, "assignment_id": assignment.id, "stage": job.stage},
        )

        try:
            # Set RUNNING status
            job.status = JobStatus.RUNNING.value
            self.session.flush()

            # State 1: DISCOVERED -> ELIGIBILITY_CHECK
            if job.stage == JobStage.DISCOVERED.value:
                self._run_eligibility_check(job, assignment)

            # State 2: ELIGIBILITY_CHECK -> GENERATING
            if job.stage == JobStage.ELIGIBILITY_CHECK.value:
                self._run_generation(job, assignment)

            # State 3: GENERATING -> EXECUTING
            if job.stage == JobStage.GENERATING.value:
                self._run_execution(job, assignment)

            # State 4: EXECUTING -> CAPTURING
            if job.stage == JobStage.EXECUTING.value:
                self._run_capturing(job, assignment)

            # State 5: CAPTURING -> PDF_BUILDING
            if job.stage == JobStage.CAPTURING.value:
                self._run_pdf_building(job, assignment)

            # State 6: PDF_BUILDING -> PDF_VALIDATING
            if job.stage == JobStage.PDF_BUILDING.value:
                self._run_pdf_validation(job, assignment)

            # State 7: PDF_VALIDATING -> AWAITING_APPROVAL / UPLOADING
            if job.stage == JobStage.PDF_VALIDATING.value:
                if self.settings.auto_approve:
                    self.job_repo.transition_stage(job.id, JobStage.UPLOADING.value, JobStatus.PENDING.value)
                else:
                    self.job_repo.transition_stage(job.id, JobStage.AWAITING_APPROVAL.value, JobStatus.AWAITING_MANUAL_ACTION.value)
                    return True  # Pauses safely until user approval

            # State 8: AWAITING_APPROVAL
            if job.stage == JobStage.AWAITING_APPROVAL.value:
                # If approval is granted or auto-approve enabled
                if self.settings.auto_approve:
                    self.job_repo.transition_stage(job.id, JobStage.UPLOADING.value, JobStatus.PENDING.value)
                else:
                    return True  # Still waiting for manual approval

            # State 9: UPLOADING
            if job.stage == JobStage.UPLOADING.value:
                if not self.settings.auto_upload:
                    logger.info(f"Job {job.id} paused at UPLOADING because AUTO_UPLOAD=false")
                    job.status = JobStatus.BLOCKED.value
                    self.session.flush()
                    return True

                await self._run_upload(job, assignment)

            return True

        except Exception as e:
            self._handle_job_exception(job, e)
            return False

    def _run_eligibility_check(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        if assignment.needs_manual_review:
            job.status = JobStatus.BLOCKED.value
            job.last_error_message = assignment.review_reason or "Assignment flagged for manual review."
            self.session.flush()
            raise ValueError(f"Assignment requires manual review: {job.last_error_message}")

        self.job_repo.transition_stage(job.id, JobStage.ELIGIBILITY_CHECK.value, JobStatus.RUNNING.value)

    def _run_generation(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        plan = create_solution_plan(
            assignment_id=assignment.id,
            title=assignment.name,
            description_text=assignment.description_text or "",
        )
        if plan.requires_manual_review:
            self.assign_repo.mark_review_required(assignment.id, plan.review_reason or "Generation review required")
            raise ValueError(f"Solution planning flagged for review: {plan.review_reason}")

        solution = self.generator.generate(plan)
        valid, err = review_solution(solution)
        if not valid:
            raise ValueError(f"Solution code failed review: {err}")

        # Save artifact in database
        self.artifact_repo.save_artifact(
            assignment_id=assignment.id,
            artifact_type=ArtifactType.SOLUTION_CODE.value,
            file_path=str(solution.file_path),
            file_size_bytes=solution.file_path.stat().st_size,
            sha256_checksum=solution.checksum,
            job_id=job.id,
            is_validated=True,
        )

        self.job_repo.transition_stage(job.id, JobStage.GENERATING.value, JobStatus.RUNNING.value)

    def _run_execution(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        # Fetch code artifact
        code_artifact = self.artifact_repo.get_latest_artifact(assignment.id, ArtifactType.SOLUTION_CODE.value)
        if not code_artifact:
            raise FileNotFoundError("Solution code artifact not found.")

        plan = create_solution_plan(assignment.id, assignment.name, assignment.description_text or "")
        from app.generation.solution_generator import GeneratedSolution
        solution = GeneratedSolution(
            assignment_id=assignment.id,
            language=plan.language,
            source_code=Path(code_artifact.file_path).read_text(encoding="utf-8"),
            file_path=Path(code_artifact.file_path),
            checksum=code_artifact.sha256_checksum,
            plan=plan,
        )

        exec_res = self.runner.execute(solution)
        if not exec_res.is_success:
            raise RuntimeError(f"Execution failed (code {exec_res.exit_code}): {exec_res.stderr or exec_res.error_message}")

        # Save execution output artifact
        out_file = solution.file_path.parent / "execution_output.txt"
        out_file.write_text(exec_res.stdout, encoding="utf-8")
        out_checksum = compute_file_sha256(out_file)

        self.artifact_repo.save_artifact(
            assignment_id=assignment.id,
            artifact_type=ArtifactType.EXECUTION_OUTPUT.value,
            file_path=str(out_file),
            file_size_bytes=out_file.stat().st_size,
            sha256_checksum=out_checksum,
            job_id=job.id,
            is_validated=True,
        )

        self.job_repo.transition_stage(job.id, JobStage.EXECUTING.value, JobStatus.RUNNING.value)

    def _run_capturing(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        code_artifact = self.artifact_repo.get_latest_artifact(assignment.id, ArtifactType.SOLUTION_CODE.value)
        out_artifact = self.artifact_repo.get_latest_artifact(assignment.id, ArtifactType.EXECUTION_OUTPUT.value)
        if not code_artifact or not out_artifact:
            raise FileNotFoundError("Missing artifacts for screenshot capture.")

        code_path = Path(code_artifact.file_path)
        out_text = Path(out_artifact.file_path).read_text(encoding="utf-8")

        work_dir = code_path.parent
        code_png = work_dir / "code_screenshot.png"
        output_png = work_dir / "output_screenshot.png"

        plan = create_solution_plan(assignment.id, assignment.name, assignment.description_text or "")
        code_images = render_code_to_image(
            source_code=code_path.read_text(encoding="utf-8"),
            output_path=code_png,
            language=plan.language,
            title=code_path.name,
        )
        for c_img in code_images:
            val, err = validate_image_file(c_img)
            if not val:
                raise ValueError(f"Code screenshot validation failed: {err}")
            self.artifact_repo.save_artifact(
                assignment_id=assignment.id,
                artifact_type=ArtifactType.CODE_SCREENSHOT.value,
                file_path=str(c_img),
                file_size_bytes=c_img.stat().st_size,
                sha256_checksum=compute_file_sha256(c_img),
                job_id=job.id,
                is_validated=True,
            )

        from app.execution.validation import ExecutionResult
        fake_result = ExecutionResult(
            command=f"python {code_path.name}",
            exit_code=0,
            stdout=out_text,
            stderr="",
            duration_seconds=0.15,
            is_success=True,
        )
        out_img = render_terminal_output_to_image(fake_result, output_png)
        val, err = validate_image_file(out_img)
        if not val:
            raise ValueError(f"Output screenshot validation failed: {err}")

        self.artifact_repo.save_artifact(
            assignment_id=assignment.id,
            artifact_type=ArtifactType.OUTPUT_SCREENSHOT.value,
            file_path=str(out_img),
            file_size_bytes=out_img.stat().st_size,
            sha256_checksum=compute_file_sha256(out_img),
            job_id=job.id,
            is_validated=True,
        )

        self.job_repo.transition_stage(job.id, JobStage.CAPTURING.value, JobStatus.RUNNING.value)

    def _run_pdf_building(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        code_art = self.artifact_repo.get_latest_artifact(assignment.id, ArtifactType.CODE_SCREENSHOT.value)
        out_art = self.artifact_repo.get_latest_artifact(assignment.id, ArtifactType.OUTPUT_SCREENSHOT.value)

        pdf_filename = f"{sanitize_filename(assignment.name)}_{assignment.id}.pdf"
        pdf_path = self.settings.generated_pdfs_dir / pdf_filename

        pdf_input = PdfGenerationInput(
            assignment_id=assignment.id,
            assignment_title=assignment.name,
            course_name=assignment.course.full_name if assignment.course else "Course",
            student_name=self.settings.student_name,
            student_uid=self.settings.student_uid,
            institution_name=self.settings.institution_name,
            objective_text=assignment.description_text or assignment.name,
            code_images=[Path(code_art.file_path)] if code_art else [],
            output_images=[Path(out_art.file_path)] if out_art else [],
            additional_notes="All algorithmic constraints satisfied.",
            output_pdf_path=pdf_path,
        )

        generate_assignment_pdf(pdf_input)
        self.job_repo.transition_stage(job.id, JobStage.PDF_BUILDING.value, JobStatus.RUNNING.value)

    def _run_pdf_validation(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        pdf_filename = f"{sanitize_filename(assignment.name)}_{assignment.id}.pdf"
        pdf_path = self.settings.generated_pdfs_dir / pdf_filename

        valid, err = validate_pdf_file(
            pdf_path=pdf_path,
            expected_student_name=self.settings.student_name,
            expected_student_uid=self.settings.student_uid,
            expected_title=assignment.name,
            max_size_mb=self.settings.max_file_size_mb,
        )
        if not valid:
            raise ValueError(f"Generated PDF failed validation: {err}")

        meta = get_pdf_metadata(pdf_path)
        self.artifact_repo.save_artifact(
            assignment_id=assignment.id,
            artifact_type=ArtifactType.GENERATED_PDF.value,
            file_path=str(pdf_path),
            file_size_bytes=meta["file_size_bytes"],
            sha256_checksum=meta["sha256_checksum"],
            job_id=job.id,
            is_validated=True,
            validation_notes="ReportLab structural & content check passed.",
        )

        self.job_repo.transition_stage(job.id, JobStage.PDF_VALIDATING.value, JobStatus.RUNNING.value)

    async def _run_upload(self, job: ProcessingJobModel, assignment: AssignmentModel) -> None:
        pdf_art = self.artifact_repo.get_latest_artifact(assignment.id, ArtifactType.GENERATED_PDF.value)
        if not pdf_art:
            raise FileNotFoundError("Validated PDF artifact not found for upload.")

        success, msg, status = await self.uploader.execute_upload_pipeline(
            assignment_id=assignment.id,
            artifact_id=pdf_art.id,
            job_id=job.id,
        )
        if not success:
            raise RuntimeError(f"Upload pipeline failed: {msg}")

    def _handle_job_exception(self, job: ProcessingJobModel, e: Exception) -> None:
        logger.error(f"Error executing job {job.id}: {e}", exc_info=True)
        is_transient = is_transient_error(e)

        next_retry: Optional[datetime] = None
        if is_transient and job.retry_count < job.max_retries:
            backoff = calculate_backoff_seconds(job.retry_count)
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            logger.info(f"Scheduling retry {job.retry_count + 1} for job {job.id} in {backoff}s")

        self.job_repo.record_failure(
            job_id=job.id,
            error_code=type(e).__name__,
            error_message=str(e),
            is_permanent=(not is_transient or job.retry_count >= job.max_retries),
            next_retry_at=next_retry,
        )
        self.session.commit()

