"""Assignment discovery scanner orchestrating Moodle sync, classification, and deduplication."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.database.models import (
    AssignmentClassification,
    AssignmentModel,
    CourseModel,
    JobStage,
    JobStatus,
)
from app.database.repositories import (
    AssignmentRepository,
    AuditRepository,
    CourseRepository,
    ProcessingJobRepository,
)
from app.discovery.deadline_rules import classify_assignment
from app.discovery.deduplication import compute_assignment_fingerprint, generate_job_key
from app.logging_config import get_logger
from app.moodle.client import MoodleClient
from app.moodle.schemas import MoodleAssignment

logger = get_logger(__name__)


@dataclass
class ScanReport:
    total_courses: int = 0
    total_assignments: int = 0
    new_or_updated_assignments: int = 0
    overdue_assignments: int = 0
    due_soon_assignments: int = 0
    review_required_assignments: int = 0
    submitted_assignments: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class AssignmentScanner:
    """Discovers courses, fetches assignments, classifies deadlines, and persists updates."""

    def __init__(self, client: MoodleClient, session: Session, settings: Optional[AppSettings] = None):
        self.client = client
        self.session = session
        self.settings = settings or get_settings()
        self.course_repo = CourseRepository(session)
        self.assign_repo = AssignmentRepository(session)
        self.job_repo = ProcessingJobRepository(session)
        self.audit_repo = AuditRepository(session)
        self.tz = self.settings.get_zoneinfo()

    async def scan(self, course_ids: Optional[List[int]] = None) -> ScanReport:
        report = ScanReport()
        logger.info("Initiating assignment scan", extra={"course_ids": course_ids})

        try:
            # 1. Discover courses
            moodle_courses = await self.client.get_courses()
            report.total_courses = len(moodle_courses)

            course_map = {}
            for mc in moodle_courses:
                course_record = self.course_repo.upsert_course(
                    moodle_course_id=mc.id,
                    short_name=mc.shortname,
                    full_name=mc.fullname,
                    category_name=mc.category,
                    is_enrolled=mc.enrolled,
                )
                course_map[mc.id] = course_record

            target_cids = course_ids or [mc.id for mc in moodle_courses]

            # 2. Discover assignments
            moodle_assignments = await self.client.get_assignments(target_cids)
            report.total_assignments = len(moodle_assignments)

            now_utc = datetime.now(timezone.utc)

            for ma in moodle_assignments:
                course_rec = course_map.get(ma.course_id)
                if not course_rec:
                    course_rec = self.course_repo.get_by_moodle_id(ma.course_id)
                    if not course_rec:
                        course_rec = self.course_repo.upsert_course(
                            moodle_course_id=ma.course_id,
                            short_name=f"Course {ma.course_id}",
                            full_name=f"Course {ma.course_id}",
                        )

                # Fetch authoritative submission status
                try:
                    sub_status = await self.client.get_submission_status(ma.id)
                except Exception as e:
                    logger.warning(f"Could not fetch submission status for assignment {ma.id}: {e}")
                    report.errors.append(f"Assignment {ma.id}: {e}")
                    continue

                classification, review_reason = classify_assignment(
                    assignment=ma,
                    status=sub_status,
                    tz=self.tz,
                    now_utc=now_utc,
                )

                fingerprint = compute_assignment_fingerprint(ma)

                # Check if instructions are empty or missing
                needs_review = classification == AssignmentClassification.NEEDS_MANUAL_REVIEW
                if not ma.intro_text or len(ma.intro_text.strip()) == 0:
                    needs_review = True
                    review_reason = review_reason or "Assignment instructions are empty or missing."
                    classification = AssignmentClassification.NEEDS_MANUAL_REVIEW

                assignment_rec, changed = self.assign_repo.upsert_assignment(
                    course_id=course_rec.id,
                    moodle_assignment_id=ma.id,
                    name=ma.name,
                    fingerprint=fingerprint,
                    description_html=ma.intro_html,
                    description_text=ma.intro_text,
                    due_date=ma.duedate,
                    allow_submissions_from_date=ma.allowsubmissionsfromdate,
                    cutoff_date=ma.cutoffdate,
                    max_files=ma.maxfiles,
                    max_file_size_bytes=ma.maxbytes,
                    accepted_file_types=ma.filetypeslist,
                    submission_status_moodle=sub_status.status.value,
                    grading_status_moodle=sub_status.grading_status.value,
                    classification=classification.value,
                    requires_confirmation=ma.requiresubmissionstatement,
                )

                if needs_review:
                    self.assign_repo.mark_review_required(assignment_rec.id, review_reason or "Review required")

                if changed:
                    report.new_or_updated_assignments += 1

                # Update counts
                if classification == AssignmentClassification.OVERDUE_UNSUBMITTED:
                    report.overdue_assignments += 1
                elif classification == AssignmentClassification.DUE_SOON_UNSUBMITTED:
                    report.due_soon_assignments += 1
                elif classification in (
                    AssignmentClassification.SUBMITTED_AWAITING_GRADING,
                    AssignmentClassification.SUBMITTED_AWAITING_CONFIRMATION,
                ):
                    report.submitted_assignments += 1
                elif classification == AssignmentClassification.NEEDS_MANUAL_REVIEW:
                    report.review_required_assignments += 1

                # If assignment is eligible for processing (OVERDUE or DUE_SOON and changed/new), create or get job
                if classification in (
                    AssignmentClassification.OVERDUE_UNSUBMITTED,
                    AssignmentClassification.DUE_SOON_UNSUBMITTED,
                ) and not needs_review:
                    job_key = generate_job_key(assignment_rec.id, JobStage.DISCOVERED.value, fingerprint)
                    self.job_repo.create_or_get_job(
                        job_key=job_key,
                        assignment_id=assignment_rec.id,
                        stage=JobStage.DISCOVERED.value,
                        correlation_id=f"scan_{now_utc.strftime('%Y%m%d%H%M%S')}_{ma.id}",
                    )

            self.audit_repo.log(
                event_type="SCAN_COMPLETED",
                details={
                    "total_courses": report.total_courses,
                    "total_assignments": report.total_assignments,
                    "new_or_updated": report.new_or_updated_assignments,
                    "overdue": report.overdue_assignments,
                },
            )

        except Exception as e:
            logger.error(f"Scan failed with error: {e}", exc_info=True)
            report.errors.append(str(e))
            raise

        logger.info(
            "Scan completed successfully",
            extra={
                "courses": report.total_courses,
                "assignments": report.total_assignments,
                "overdue": report.overdue_assignments,
            },
        )
        return report

