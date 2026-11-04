"""Unit tests for database models and repositories."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    AccountModel,
    ArtifactType,
    AssignmentClassification,
    Base,
    JobStage,
    JobStatus,
    UploadStatus,
)
from app.database.repositories import (
    AccountRepository,
    ArtifactRepository,
    AssignmentRepository,
    CourseRepository,
    ProcessingJobRepository,
    UploadAttemptRepository,
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


def test_account_repository(db_session):
    repo = AccountRepository(db_session)
    acc = repo.get_or_create(
        account_uid="student_1",
        student_name="Aditya Agarwal",
        student_uid="UID12345",
        moodle_base_url="http://localhost:8080",
    )
    assert acc.id is not None
    assert acc.student_name == "Aditya Agarwal"

    # Repeated get_or_create should return existing
    acc2 = repo.get_or_create(
        account_uid="student_1",
        student_name="Aditya Agarwal",
        student_uid="UID12345",
        moodle_base_url="http://localhost:8080",
    )
    assert acc2.id == acc.id


def test_course_and_assignment_lifecycle(db_session):
    course_repo = CourseRepository(db_session)
    assign_repo = AssignmentRepository(db_session)

    course = course_repo.upsert_course(
        moodle_course_id=101,
        short_name="CS101",
        full_name="Introduction to Computer Science",
    )
    assert course.id is not None

    due = datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)
    assignment, created = assign_repo.upsert_assignment(
        course_id=course.id,
        moodle_assignment_id=501,
        name="Lab 1: Recursion",
        fingerprint="fp_abc123",
        due_date=due,
        classification=AssignmentClassification.DUE_SOON_UNSUBMITTED.value,
    )
    assert created is True
    assert assignment.moodle_assignment_id == 501

    # Fingerprint change
    assignment2, content_changed = assign_repo.upsert_assignment(
        course_id=course.id,
        moodle_assignment_id=501,
        name="Lab 1: Recursion (Updated)",
        fingerprint="fp_xyz789",
        due_date=due,
    )
    assert content_changed is True
    assert assignment2.assignment_fingerprint == "fp_xyz789"


def test_processing_job_state_transitions(db_session):
    course_repo = CourseRepository(db_session)
    assign_repo = AssignmentRepository(db_session)
    job_repo = ProcessingJobRepository(db_session)

    course = course_repo.upsert_course(1, "CS101", "CS101")
    assign, _ = assign_repo.upsert_assignment(course.id, 1, "Lab 1", "fp1")

    job, created = job_repo.create_or_get_job(
        job_key="assign_1_fp1",
        assignment_id=assign.id,
        stage=JobStage.DISCOVERED.value,
        correlation_id="corr-1",
    )
    assert created is True
    assert job.stage == JobStage.DISCOVERED.value

    # Transition to GENERATING
    updated_job = job_repo.transition_stage(
        job_id=job.id,
        new_stage=JobStage.GENERATING.value,
        new_status=JobStatus.RUNNING.value,
    )
    assert updated_job.stage == JobStage.GENERATING.value
    assert updated_job.status == JobStatus.RUNNING.value


def test_artifact_and_upload_attempt(db_session):
    course_repo = CourseRepository(db_session)
    assign_repo = AssignmentRepository(db_session)
    artifact_repo = ArtifactRepository(db_session)
    upload_repo = UploadAttemptRepository(db_session)

    course = course_repo.upsert_course(1, "CS101", "CS101")
    assign, _ = assign_repo.upsert_assignment(course.id, 1, "Lab 1", "fp1")

    art = artifact_repo.save_artifact(
        assignment_id=assign.id,
        artifact_type=ArtifactType.GENERATED_PDF.value,
        file_path="/tmp/solution.pdf",
        file_size_bytes=1024,
        sha256_checksum="abcde12345",
    )
    assert art.id is not None
    assert art.is_validated is False

    artifact_repo.mark_validated(art.id, "PDF syntax valid")
    assert art.is_validated is True

    attempt = upload_repo.record_attempt(
        assignment_id=assign.id,
        artifact_id=art.id,
        attempt_number=1,
    )
    assert attempt.id is not None
    upload_repo.update_verification(attempt.id, verified=True, status=UploadStatus.UPLOADED_DRAFT.value)
    assert attempt.verified_by_moodle is True

