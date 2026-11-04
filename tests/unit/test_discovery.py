"""Unit tests for assignment discovery, deadline rules, and deduplication."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import AppSettings
from app.database.models import AssignmentClassification, Base, JobStage
from app.discovery.deadline_rules import classify_assignment
from app.discovery.deduplication import compute_assignment_fingerprint, has_assignment_changed
from app.discovery.scanner import AssignmentScanner
from app.moodle.schemas import (
    GradingState,
    MoodleAssignment,
    MoodleCourse,
    MoodleSubmissionStatus,
    SubmissionState,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_classify_overdue_unsubmitted():
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)  # past

    assign = MoodleAssignment(id=1, course_id=1, name="Lab 1", duedate=due)
    status = MoodleSubmissionStatus(assignment_id=1, status=SubmissionState.NEW, can_submit=True)

    cls, reason = classify_assignment(assign, status, tz, now_utc=now)
    assert cls == AssignmentClassification.OVERDUE_UNSUBMITTED
    assert reason is None


def test_classify_due_soon():
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    due = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)  # 2 days in future

    assign = MoodleAssignment(id=1, course_id=1, name="Lab 2", duedate=due)
    status = MoodleSubmissionStatus(assignment_id=1, status=SubmissionState.NEW, can_submit=True)

    cls, reason = classify_assignment(assign, status, tz, now_utc=now)
    assert cls == AssignmentClassification.DUE_SOON_UNSUBMITTED


def test_classify_already_graded():
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)

    assign = MoodleAssignment(id=1, course_id=1, name="Lab 3", duedate=due)
    status = MoodleSubmissionStatus(
        assignment_id=1,
        status=SubmissionState.SUBMITTED,
        grading_status=GradingState.GRADED,
        is_graded=True,
    )

    cls, _ = classify_assignment(assign, status, tz, now_utc=now)
    assert cls == AssignmentClassification.ALREADY_GRADED


def test_fingerprint_computation():
    due = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    a1 = MoodleAssignment(id=10, course_id=1, name="Lab 1", intro_text="Write quicksort", duedate=due)
    a2 = MoodleAssignment(id=10, course_id=1, name="Lab 1", intro_text="Write quicksort", duedate=due)
    a3 = MoodleAssignment(id=10, course_id=1, name="Lab 1", intro_text="Write mergesort", duedate=due)

    fp1 = compute_assignment_fingerprint(a1)
    fp2 = compute_assignment_fingerprint(a2)
    fp3 = compute_assignment_fingerprint(a3)

    assert fp1 == fp2
    assert fp1 != fp3
    assert has_assignment_changed(fp1, fp2) is False
    assert has_assignment_changed(fp1, fp3) is True


@pytest.mark.asyncio
async def test_assignment_scanner_end_to_end(db_session):
    client = AsyncMock()
    client.get_courses = AsyncMock(
        return_value=[
            MoodleCourse(id=101, shortname="CS201", fullname="Data Structures", category="CS", enrolled=True)
        ]
    )

    past_due = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    client.get_assignments = AsyncMock(
        return_value=[
            MoodleAssignment(
                id=501,
                course_id=101,
                name="Assignment 1: Binary Search Trees",
                intro_text="Implement BST insertion and traversal in Python.",
                duedate=past_due,
            )
        ]
    )

    client.get_submission_status = AsyncMock(
        return_value=MoodleSubmissionStatus(
            assignment_id=501,
            status=SubmissionState.NEW,
            can_submit=True,
        )
    )

    settings = AppSettings()
    scanner = AssignmentScanner(client=client, session=db_session, settings=settings)
    report = await scanner.scan()

    assert report.total_courses == 1
    assert report.total_assignments == 1
    assert report.overdue_assignments == 1
    assert report.new_or_updated_assignments == 1

    # Check database records
    from app.database.repositories import AssignmentRepository, ProcessingJobRepository

    assign_repo = AssignmentRepository(db_session)
    job_repo = ProcessingJobRepository(db_session)

    assign = assign_repo.get_by_moodle_id(501)
    assert assign is not None
    assert assign.classification == AssignmentClassification.OVERDUE_UNSUBMITTED.value

    jobs = assign_repo.get_by_classification(AssignmentClassification.OVERDUE_UNSUBMITTED.value)
    assert len(jobs) == 1

