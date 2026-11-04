"""Repository layer for database operations and transactional encapsulation."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.database.models import (
    AccountModel,
    ArtifactModel,
    ArtifactType,
    AssignmentClassification,
    AssignmentModel,
    AuditEventModel,
    CourseModel,
    JobStage,
    JobStatus,
    ProcessingJobModel,
    UploadAttemptModel,
    UploadStatus,
)


class AccountRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(
        self,
        account_uid: str,
        student_name: str,
        student_uid: str,
        moodle_base_url: str,
        auth_mode: str = "auto",
    ) -> AccountModel:
        stmt = select(AccountModel).where(AccountModel.account_uid == account_uid)
        account = self.session.execute(stmt).scalar_one_or_none()
        if not account:
            account = AccountModel(
                account_uid=account_uid,
                student_name=student_name,
                student_uid=student_uid,
                moodle_base_url=moodle_base_url,
                auth_mode=auth_mode,
            )
            self.session.add(account)
            self.session.flush()
        return account

    def update_last_authenticated(self, account_uid: str) -> None:
        stmt = select(AccountModel).where(AccountModel.account_uid == account_uid)
        account = self.session.execute(stmt).scalar_one_or_none()
        if account:
            account.last_authenticated_at = datetime.now(timezone.utc)
            self.session.flush()


class CourseRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_course(
        self,
        moodle_course_id: int,
        short_name: str,
        full_name: str,
        category_name: Optional[str] = None,
        is_enrolled: bool = True,
    ) -> CourseModel:
        stmt = select(CourseModel).where(CourseModel.moodle_course_id == moodle_course_id)
        course = self.session.execute(stmt).scalar_one_or_none()
        if course:
            course.short_name = short_name
            course.full_name = full_name
            course.category_name = category_name
            course.is_enrolled = is_enrolled
            course.last_scanned_at = datetime.now(timezone.utc)
        else:
            course = CourseModel(
                moodle_course_id=moodle_course_id,
                short_name=short_name,
                full_name=full_name,
                category_name=category_name,
                is_enrolled=is_enrolled,
                last_scanned_at=datetime.now(timezone.utc),
            )
            self.session.add(course)
        self.session.flush()
        return course

    def get_by_moodle_id(self, moodle_course_id: int) -> Optional[CourseModel]:
        stmt = select(CourseModel).where(CourseModel.moodle_course_id == moodle_course_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_all_enrolled(self) -> List[CourseModel]:
        stmt = select(CourseModel).where(CourseModel.is_enrolled == True).order_by(CourseModel.moodle_course_id)
        return list(self.session.execute(stmt).scalars().all())


class AssignmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_moodle_id(self, moodle_assignment_id: int) -> Optional[AssignmentModel]:
        stmt = select(AssignmentModel).where(AssignmentModel.moodle_assignment_id == moodle_assignment_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, assignment_id: int) -> Optional[AssignmentModel]:
        return self.session.get(AssignmentModel, assignment_id)

    def upsert_assignment(
        self,
        course_id: int,
        moodle_assignment_id: int,
        name: str,
        fingerprint: str,
        description_html: Optional[str] = None,
        description_text: Optional[str] = None,
        due_date: Optional[datetime] = None,
        allow_submissions_from_date: Optional[datetime] = None,
        cutoff_date: Optional[datetime] = None,
        max_files: int = 1,
        max_file_size_bytes: int = 26214400,
        accepted_file_types: Optional[str] = None,
        submission_status_moodle: str = "new",
        grading_status_moodle: Optional[str] = None,
        classification: str = AssignmentClassification.UNKNOWN.value,
        requires_confirmation: bool = False,
    ) -> tuple[AssignmentModel, bool]:
        """Upsert assignment. Returns (assignment, created_or_updated_fingerprint_flag)."""
        stmt = select(AssignmentModel).where(AssignmentModel.moodle_assignment_id == moodle_assignment_id)
        assignment = self.session.execute(stmt).scalar_one_or_none()
        content_changed = False

        if assignment:
            if assignment.assignment_fingerprint != fingerprint:
                content_changed = True
                assignment.assignment_fingerprint = fingerprint
            assignment.name = name
            assignment.course_id = course_id
            assignment.description_html = description_html
            assignment.description_text = description_text
            assignment.due_date = due_date
            assignment.allow_submissions_from_date = allow_submissions_from_date
            assignment.cutoff_date = cutoff_date
            assignment.max_files = max_files
            assignment.max_file_size_bytes = max_file_size_bytes
            assignment.accepted_file_types = accepted_file_types
            assignment.submission_status_moodle = submission_status_moodle
            assignment.grading_status_moodle = grading_status_moodle
            assignment.classification = classification
            assignment.requires_confirmation = requires_confirmation
        else:
            content_changed = True
            assignment = AssignmentModel(
                course_id=course_id,
                moodle_assignment_id=moodle_assignment_id,
                name=name,
                assignment_fingerprint=fingerprint,
                description_html=description_html,
                description_text=description_text,
                due_date=due_date,
                allow_submissions_from_date=allow_submissions_from_date,
                cutoff_date=cutoff_date,
                max_files=max_files,
                max_file_size_bytes=max_file_size_bytes,
                accepted_file_types=accepted_file_types,
                submission_status_moodle=submission_status_moodle,
                grading_status_moodle=grading_status_moodle,
                classification=classification,
                requires_confirmation=requires_confirmation,
            )
            self.session.add(assignment)

        self.session.flush()
        return assignment, content_changed

    def mark_review_required(self, assignment_id: int, reason: str) -> None:
        assignment = self.session.get(AssignmentModel, assignment_id)
        if assignment:
            assignment.needs_manual_review = True
            assignment.review_reason = reason
            assignment.classification = AssignmentClassification.NEEDS_MANUAL_REVIEW.value
            self.session.flush()

    def get_by_classification(self, classification: str) -> List[AssignmentModel]:
        stmt = select(AssignmentModel).where(AssignmentModel.classification == classification).order_by(AssignmentModel.due_date)
        return list(self.session.execute(stmt).scalars().all())

    def get_all(self) -> List[AssignmentModel]:
        stmt = select(AssignmentModel).order_by(AssignmentModel.id)
        return list(self.session.execute(stmt).scalars().all())


class ProcessingJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_key(self, job_key: str) -> Optional[ProcessingJobModel]:
        stmt = select(ProcessingJobModel).where(ProcessingJobModel.job_key == job_key)
        return self.session.execute(stmt).scalar_one_or_none()

    def create_or_get_job(
        self,
        job_key: str,
        assignment_id: int,
        stage: str = JobStage.DISCOVERED.value,
        correlation_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[ProcessingJobModel, bool]:
        job = self.get_by_key(job_key)
        if job:
            return job, False

        job = ProcessingJobModel(
            job_key=job_key,
            assignment_id=assignment_id,
            stage=stage,
            status=JobStatus.PENDING.value,
            correlation_id=correlation_id,
            metadata_json=json.dumps(metadata or {}),
        )
        self.session.add(job)
        self.session.flush()
        return job, True

    def transition_stage(
        self,
        job_id: int,
        new_stage: str,
        new_status: str = JobStatus.PENDING.value,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingJobModel:
        job = self.session.get(ProcessingJobModel, job_id)
        if not job:
            raise ValueError(f"Job id {job_id} not found.")

        job.stage = new_stage
        job.status = new_status
        if metadata:
            curr_meta = json.loads(job.metadata_json or "{}")
            curr_meta.update(metadata)
            job.metadata_json = json.dumps(curr_meta)
        self.session.flush()
        return job

    def record_failure(
        self,
        job_id: int,
        error_code: str,
        error_message: str,
        is_permanent: bool,
        next_retry_at: Optional[datetime] = None,
    ) -> ProcessingJobModel:
        job = self.session.get(ProcessingJobModel, job_id)
        if not job:
            raise ValueError(f"Job id {job_id} not found.")

        job.status = JobStatus.FAILED.value
        job.last_error_code = error_code
        job.last_error_message = error_message
        job.is_permanent_failure = is_permanent
        job.retry_count += 1
        job.next_retry_at = next_retry_at
        self.session.flush()
        return job

    def get_interrupted_jobs(self) -> List[ProcessingJobModel]:
        """Find jobs that were running when the process crashed/stopped."""
        stmt = select(ProcessingJobModel).where(ProcessingJobModel.status == JobStatus.RUNNING.value)
        return list(self.session.execute(stmt).scalars().all())

    def get_due_retries(self, now: datetime) -> List[ProcessingJobModel]:
        stmt = select(ProcessingJobModel).where(
            and_(
                ProcessingJobModel.status == JobStatus.FAILED.value,
                ProcessingJobModel.is_permanent_failure == False,
                ProcessingJobModel.next_retry_at <= now,
                ProcessingJobModel.retry_count < ProcessingJobModel.max_retries,
            )
        )
        return list(self.session.execute(stmt).scalars().all())


class ArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    def save_artifact(
        self,
        assignment_id: int,
        artifact_type: str,
        file_path: str,
        file_size_bytes: int,
        sha256_checksum: str,
        job_id: Optional[int] = None,
        is_validated: bool = False,
        validation_notes: Optional[str] = None,
    ) -> ArtifactModel:
        artifact = ArtifactModel(
            assignment_id=assignment_id,
            job_id=job_id,
            artifact_type=artifact_type,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            sha256_checksum=sha256_checksum,
            is_validated=is_validated,
            validation_notes=validation_notes,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def get_latest_artifact(self, assignment_id: int, artifact_type: str) -> Optional[ArtifactModel]:
        stmt = (
            select(ArtifactModel)
            .where(
                and_(
                    ArtifactModel.assignment_id == assignment_id,
                    ArtifactModel.artifact_type == artifact_type,
                )
            )
            .order_by(ArtifactModel.id.desc())
        )
        return self.session.execute(stmt).scalars().first()

    def mark_validated(self, artifact_id: int, notes: Optional[str] = None) -> None:
        art = self.session.get(ArtifactModel, artifact_id)
        if art:
            art.is_validated = True
            art.validation_notes = notes
            self.session.flush()


class UploadAttemptRepository:
    def __init__(self, session: Session):
        self.session = session

    def record_attempt(
        self,
        assignment_id: int,
        artifact_id: int,
        attempt_number: int,
        status: str = UploadStatus.INITIATED.value,
        file_item_id: Optional[int] = None,
        response_data: Optional[str] = None,
    ) -> UploadAttemptModel:
        attempt = UploadAttemptModel(
            assignment_id=assignment_id,
            artifact_id=artifact_id,
            attempt_number=attempt_number,
            upload_status=status,
            moodle_file_item_id=file_item_id,
            moodle_response_data=response_data,
        )
        self.session.add(attempt)
        self.session.flush()
        return attempt

    def update_verification(
        self,
        attempt_id: int,
        verified: bool,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        attempt = self.session.get(UploadAttemptModel, attempt_id)
        if attempt:
            attempt.verified_by_moodle = verified
            attempt.upload_status = status
            attempt.error_message = error_message
            if verified:
                attempt.verification_timestamp = datetime.now(timezone.utc)
            self.session.flush()

    def get_latest_for_assignment(self, assignment_id: int) -> Optional[UploadAttemptModel]:
        stmt = (
            select(UploadAttemptModel)
            .where(UploadAttemptModel.assignment_id == assignment_id)
            .order_by(UploadAttemptModel.id.desc())
        )
        return self.session.execute(stmt).scalars().first()


class AuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def log(
        self,
        event_type: str,
        details: Dict[str, Any],
        assignment_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> AuditEventModel:
        event = AuditEventModel(
            event_type=event_type,
            assignment_id=assignment_id,
            correlation_id=correlation_id,
            details=json.dumps(details),
        )
        self.session.add(event)
        self.session.flush()
        return event

