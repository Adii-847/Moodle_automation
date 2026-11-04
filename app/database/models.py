"""SQLAlchemy 2.0 ORM models for Moodle Assignment Automation System."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AssignmentClassification(str, Enum):
    OVERDUE_UNSUBMITTED = "OVERDUE_UNSUBMITTED"
    DUE_SOON_UNSUBMITTED = "DUE_SOON_UNSUBMITTED"
    SUBMITTED_AWAITING_GRADING = "SUBMITTED_AWAITING_GRADING"
    SUBMITTED_AWAITING_CONFIRMATION = "SUBMITTED_AWAITING_CONFIRMATION"
    ALREADY_GRADED = "ALREADY_GRADED"
    CLOSED_OR_UNAVAILABLE = "CLOSED_OR_UNAVAILABLE"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    UNKNOWN = "UNKNOWN"


class JobStage(str, Enum):
    DISCOVERED = "DISCOVERED"
    ELIGIBILITY_CHECK = "ELIGIBILITY_CHECK"
    GENERATING = "GENERATING"
    EXECUTING = "EXECUTING"
    CAPTURING = "CAPTURING"
    PDF_BUILDING = "PDF_BUILDING"
    PDF_VALIDATING = "PDF_VALIDATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    AWAITING_MANUAL_ACTION = "AWAITING_MANUAL_ACTION"


class ArtifactType(str, Enum):
    SOLUTION_CODE = "SOLUTION_CODE"
    EXECUTION_OUTPUT = "EXECUTION_OUTPUT"
    CODE_SCREENSHOT = "CODE_SCREENSHOT"
    OUTPUT_SCREENSHOT = "OUTPUT_SCREENSHOT"
    GENERATED_PDF = "GENERATED_PDF"


class UploadStatus(str, Enum):
    INITIATED = "INITIATED"
    UPLOADED_DRAFT = "UPLOADED_DRAFT"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"
    UNCONFIRMED = "UNCONFIRMED"
    RECONCILED = "RECONCILED"


class AccountModel(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_uid: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    student_name: Mapped[str] = mapped_column(String(200), nullable=False)
    student_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    moodle_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(50), default="auto")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_authenticated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CourseModel(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moodle_course_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    short_name: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(500), nullable=False)
    category_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_enrolled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    assignments: Mapped[List["AssignmentModel"]] = relationship("AssignmentModel", back_populates="course", cascade="all, delete-orphan")


class AssignmentModel(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moodle_assignment_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    allow_submissions_from_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cutoff_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    grading_due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    max_files: Mapped[int] = mapped_column(Integer, default=1)
    max_file_size_bytes: Mapped[int] = mapped_column(Integer, default=26214400)  # 25 MB
    accepted_file_types: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    submission_status_moodle: Mapped[str] = mapped_column(String(100), default="new")
    grading_status_moodle: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    classification: Mapped[str] = mapped_column(String(100), default=AssignmentClassification.UNKNOWN.value, index=True)
    assignment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    course: Mapped["CourseModel"] = relationship("CourseModel", back_populates="assignments")
    jobs: Mapped[List["ProcessingJobModel"]] = relationship("ProcessingJobModel", back_populates="assignment", cascade="all, delete-orphan")
    artifacts: Mapped[List["ArtifactModel"]] = relationship("ArtifactModel", back_populates="assignment", cascade="all, delete-orphan")
    upload_attempts: Mapped[List["UploadAttemptModel"]] = relationship("UploadAttemptModel", back_populates="assignment", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("course_id", "moodle_assignment_id", name="uq_course_assignment"),
    )


class ProcessingJobModel(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    assignment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(50), default=JobStage.DISCOVERED.value, index=True)
    status: Mapped[str] = mapped_column(String(50), default=JobStatus.PENDING.value, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_permanent_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    assignment: Mapped["AssignmentModel"] = relationship("AssignmentModel", back_populates="jobs")
    artifacts: Mapped[List["ArtifactModel"]] = relationship("ArtifactModel", back_populates="job")


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignment: Mapped["AssignmentModel"] = relationship("AssignmentModel", back_populates="artifacts")
    job: Mapped[Optional["ProcessingJobModel"]] = relationship("ProcessingJobModel", back_populates="artifacts")
    upload_attempts: Mapped[List["UploadAttemptModel"]] = relationship("UploadAttemptModel", back_populates="artifact")


class UploadAttemptModel(Base):
    __tablename__ = "upload_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id: Mapped[int] = mapped_column(Integer, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    upload_status: Mapped[str] = mapped_column(String(50), default=UploadStatus.INITIATED.value, index=True)
    moodle_file_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    moodle_response_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_by_moodle: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignment: Mapped["AssignmentModel"] = relationship("AssignmentModel", back_populates="upload_attempts")
    artifact: Mapped["ArtifactModel"] = relationship("ArtifactModel", back_populates="upload_attempts")


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    assignment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

