"""Unit tests for state machine, job processor, retry policy, and crash recovery."""

from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import AppSettings
from app.database.models import (
    AssignmentClassification,
    AssignmentModel,
    Base,
    CourseModel,
    JobStage,
    JobStatus,
    ProcessingJobModel,
)
from app.jobs.retry_policy import calculate_backoff_seconds, is_transient_error
from app.jobs.scheduler import AssignmentScheduler
from app.jobs.tasks import JobProcessor
from app.moodle.client import MoodleAuthenticationError, MoodleError


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


def test_retry_policy_classification():
    assert is_transient_error(ConnectionResetError("Remote disconnected")) is True
    assert is_transient_error(TimeoutError("Timeout occurred")) is True
    assert is_transient_error(MoodleError("Gateway timeout 504")) is True

    # Permanent errors
    assert is_transient_error(MoodleAuthenticationError("Invalid token")) is False
    assert is_transient_error(ValueError("Bad value")) is False
    assert is_transient_error(FileNotFoundError("Missing")) is False


def test_backoff_calculation():
    b0 = calculate_backoff_seconds(0, base_seconds=2.0, jitter=False)
    b1 = calculate_backoff_seconds(1, base_seconds=2.0, jitter=False)
    b2 = calculate_backoff_seconds(2, base_seconds=2.0, jitter=False)
    assert b0 == 2.0
    assert b1 == 4.0
    assert b2 == 8.0

    bj = calculate_backoff_seconds(1, base_seconds=2.0, jitter=True)
    assert 2.0 <= bj <= 4.0


@pytest.mark.asyncio
async def test_job_processor_pipeline_through_approval(tmp_path, db_session):
    settings = AppSettings(
        BASE_DATA_DIR=tmp_path,
        AUTO_APPROVE=False,
        AUTO_UPLOAD=False,
    )

    course = CourseModel(moodle_course_id=10, short_name="CS101", full_name="Intro CS")
    db_session.add(course)
    db_session.flush()

    assign = AssignmentModel(
        course_id=course.id,
        moodle_assignment_id=99,
        name="Lab 1: Factorial",
        description_text="Write a Python program to calculate factorial using recursion.",
        assignment_fingerprint="fp99",
        classification=AssignmentClassification.OVERDUE_UNSUBMITTED.value,
    )
    db_session.add(assign)
    db_session.flush()

    job = ProcessingJobModel(
        job_key="assign_99_disc",
        assignment_id=assign.id,
        stage=JobStage.DISCOVERED.value,
        status=JobStatus.PENDING.value,
        correlation_id="corr_99",
    )
    db_session.add(job)
    db_session.commit()

    client = AsyncMock()
    processor = JobProcessor(client=client, session=db_session, settings=settings)

    # Run processing
    res = await processor.process_job(job.id)
    assert res is True

    db_session.refresh(job)
    # Because auto_approve is False, it should halt at AWAITING_APPROVAL with AWAITING_MANUAL_ACTION
    assert job.stage == JobStage.AWAITING_APPROVAL.value
    assert job.status == JobStatus.AWAITING_MANUAL_ACTION.value

    # Verify that artifacts were created
    assert len(job.artifacts) >= 4  # Code, Execution Output, Code Screenshot, Output Screenshot, PDF


@pytest.mark.asyncio
async def test_scheduler_crash_recovery(db_session, monkeypatch):
    course = CourseModel(moodle_course_id=1, short_name="CS", full_name="CS")
    db_session.add(course)
    db_session.flush()

    assign = AssignmentModel(course_id=course.id, moodle_assignment_id=1, name="A1", assignment_fingerprint="f1")
    db_session.add(assign)
    db_session.flush()

    # Simulate an interrupted job that was RUNNING when process died
    job = ProcessingJobModel(
        job_key="k1",
        assignment_id=assign.id,
        stage=JobStage.EXECUTING.value,
        status=JobStatus.RUNNING.value,
        correlation_id="c1",
    )
    db_session.add(job)
    db_session.commit()

    scheduler = AssignmentScheduler()

    from contextlib import contextmanager

    @contextmanager
    def mock_get_db_session():
        yield db_session

    monkeypatch.setattr("app.jobs.scheduler.get_db_session", mock_get_db_session)

    recovered = await scheduler.recover_from_crash()
    assert recovered == 1

    db_session.refresh(job)
    assert job.status == JobStatus.PENDING.value

