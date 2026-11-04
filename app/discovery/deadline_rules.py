"""Deadline calculation and assignment status classification rules."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.database.models import AssignmentClassification
from app.moodle.schemas import (
    GradingState,
    MoodleAssignment,
    MoodleSubmissionStatus,
    SubmissionState,
)


def classify_assignment(
    assignment: MoodleAssignment,
    status: MoodleSubmissionStatus,
    tz: ZoneInfo,
    now_utc: Optional[datetime] = None,
    due_soon_threshold_days: int = 7,
) -> tuple[AssignmentClassification, Optional[str]]:
    """Determine classification and review reason according to authoritative Moodle state and institutional deadlines."""
    now = now_utc or datetime.now(timezone.utc)

    # 1. Graded
    if status.is_graded or status.grading_status == GradingState.GRADED:
        return AssignmentClassification.ALREADY_GRADED, None

    # 2. Submitted states
    if status.status == SubmissionState.SUBMITTED:
        return AssignmentClassification.SUBMITTED_AWAITING_GRADING, None

    if status.status == SubmissionState.DRAFT:
        return AssignmentClassification.SUBMITTED_AWAITING_CONFIRMATION, None

    # 3. Availability window checks
    if assignment.allowsubmissionsfromdate and now < assignment.allowsubmissionsfromdate:
        return AssignmentClassification.CLOSED_OR_UNAVAILABLE, "Assignment submission window is not yet open."

    # If Moodle reports cannot submit or is locked
    if status.locked or not status.can_submit:
        # Check if due date was missed or closed
        if assignment.duedate and now > assignment.duedate:
            return AssignmentClassification.CLOSED_OR_UNAVAILABLE, "Assignment is closed and submissions are locked."
        return AssignmentClassification.CLOSED_OR_UNAVAILABLE, "Submissions locked by instructor."

    if assignment.cutoffdate and now > assignment.cutoffdate:
        return AssignmentClassification.CLOSED_OR_UNAVAILABLE, "Past cutoff date; submissions disabled."

    # 4. Check due date
    if not assignment.duedate:
        # No due date specified
        return AssignmentClassification.NEEDS_MANUAL_REVIEW, "No due date defined for this assignment."

    # Convert due date to local timezone for accurate day boundaries if needed
    due_local = assignment.duedate.astimezone(tz)
    now_local = now.astimezone(tz)

    if now > assignment.duedate:
        return AssignmentClassification.OVERDUE_UNSUBMITTED, None

    due_soon_threshold = timedelta(days=due_soon_threshold_days)
    if assignment.duedate - now <= due_soon_threshold:
        return AssignmentClassification.DUE_SOON_UNSUBMITTED, None

    # Not due soon, still open
    return AssignmentClassification.UNKNOWN, None

