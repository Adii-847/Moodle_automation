"""Operational metrics aggregation and status reporting."""

from dataclasses import dataclass
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    ArtifactModel,
    ArtifactType,
    AssignmentClassification,
    AssignmentModel,
    JobStatus,
    ProcessingJobModel,
    UploadAttemptModel,
    UploadStatus,
)


@dataclass
class SystemMetrics:
    total_assignments: int
    overdue_assignments: int
    due_soon_assignments: int
    review_required_assignments: int
    total_jobs: int
    pending_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    total_artifacts: int
    generated_pdfs: int
    total_upload_attempts: int
    verified_submissions: int
    unconfirmed_uploads: int


class MetricsCollector:
    """Queries and aggregates runtime performance and queue depth metrics."""

    def __init__(self, session: Session):
        self.session = session

    def collect(self) -> SystemMetrics:
        # Assignments
        total_assign = self.session.scalar(select(func.count(AssignmentModel.id))) or 0
        overdue = self.session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.classification == AssignmentClassification.OVERDUE_UNSUBMITTED.value)
        ) or 0
        due_soon = self.session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.classification == AssignmentClassification.DUE_SOON_UNSUBMITTED.value)
        ) or 0
        needs_review = self.session.scalar(
            select(func.count(AssignmentModel.id)).where(AssignmentModel.needs_manual_review == True)
        ) or 0

        # Jobs
        total_jobs = self.session.scalar(select(func.count(ProcessingJobModel.id))) or 0
        pending = self.session.scalar(select(func.count(ProcessingJobModel.id)).where(ProcessingJobModel.status == JobStatus.PENDING.value)) or 0
        running = self.session.scalar(select(func.count(ProcessingJobModel.id)).where(ProcessingJobModel.status == JobStatus.RUNNING.value)) or 0
        completed = self.session.scalar(select(func.count(ProcessingJobModel.id)).where(ProcessingJobModel.status == JobStatus.COMPLETED.value)) or 0
        failed = self.session.scalar(select(func.count(ProcessingJobModel.id)).where(ProcessingJobModel.status == JobStatus.FAILED.value)) or 0

        # Artifacts
        total_arts = self.session.scalar(select(func.count(ArtifactModel.id))) or 0
        pdfs = self.session.scalar(
            select(func.count(ArtifactModel.id)).where(ArtifactModel.artifact_type == ArtifactType.GENERATED_PDF.value)
        ) or 0

        # Uploads
        total_uploads = self.session.scalar(select(func.count(UploadAttemptModel.id))) or 0
        verified = self.session.scalar(
            select(func.count(UploadAttemptModel.id)).where(UploadAttemptModel.verified_by_moodle == True)
        ) or 0
        unconfirmed = self.session.scalar(
            select(func.count(UploadAttemptModel.id)).where(UploadAttemptModel.upload_status == UploadStatus.UNCONFIRMED.value)
        ) or 0

        return SystemMetrics(
            total_assignments=total_assign,
            overdue_assignments=overdue,
            due_soon_assignments=due_soon,
            review_required_assignments=needs_review,
            total_jobs=total_jobs,
            pending_jobs=pending,
            running_jobs=running,
            completed_jobs=completed,
            failed_jobs=failed,
            total_artifacts=total_arts,
            generated_pdfs=pdfs,
            total_upload_attempts=total_uploads,
            verified_submissions=verified,
            unconfirmed_uploads=unconfirmed,
        )

