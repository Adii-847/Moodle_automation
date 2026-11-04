"""End-to-End Vertical Slice Integration Test.

Demonstrates the complete sequence:
1. Discover an authorized test assignment from Moodle.
2. Read and analyze instructions.
3. Generate the solution code.
4. Execute in isolated sandbox.
5. Capture genuine code and terminal output screenshots.
6. Build professional A4 PDF.
7. Validate PDF structure, metadata, and dimensions.
8. Safely upload to Moodle.
9. Verify authoritative Moodle submission status.
10. Confirm restarts/subsequent runs are idempotent and avoid duplicate submissions.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import AppSettings
from app.database.models import (
    ArtifactType,
    AssignmentClassification,
    Base,
    JobStage,
    JobStatus,
    ProcessingJobModel,
    UploadStatus,
)
from app.database.repositories import (
    ArtifactRepository,
    AssignmentRepository,
    CourseRepository,
    ProcessingJobRepository,
)
from app.discovery.scanner import AssignmentScanner
from app.jobs.tasks import JobProcessor
from app.moodle.schemas import (
    GradingState,
    MoodleAssignment,
    MoodleCourse,
    MoodleFile,
    MoodleFinalizeResult,
    MoodleSiteInfo,
    MoodleSubmissionStatus,
    MoodleUploadResult,
    SubmissionState,
)


@pytest.fixture
def test_environment(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    settings = AppSettings(
        MOODLE_BASE_URL="http://moodle.college.edu",
        MOODLE_API_TOKEN="valid_mock_token_12345",
        STUDENT_NAME="Aditya Agarwal",
        STUDENT_UID="UID-2026-ENG",
        BASE_DATA_DIR=tmp_path,
        AUTO_UPLOAD=True,
        AUTO_FINAL_SUBMIT=False,  # Draft mode verification
        AUTO_APPROVE=True,        # Automatic progression through pipeline for vertical slice
    )

    try:
        yield session, settings
    finally:
        session.close()


@pytest.mark.asyncio
async def test_complete_vertical_slice_pipeline(test_environment):
    session, settings = test_environment

    # 1. Mock Moodle Client representing authoritative college Moodle instance
    moodle_client = AsyncMock()

    moodle_client.check_connection = AsyncMock(
        return_value=MoodleSiteInfo(
            sitename="Institute of Engineering Moodle",
            username="student_aditya",
            firstname="Aditya",
            lastname="Agarwal",
            fullname="Aditya Agarwal",
            userid=789,
            siteurl="http://moodle.college.edu",
            version="4.3",
            release="4.3.1",
        )
    )

    course = MoodleCourse(id=101, shortname="CS301", fullname="Algorithm Design", enrolled=True)
    moodle_client.get_courses = AsyncMock(return_value=[course])

    past_deadline = datetime(2026, 10, 25, 23, 59, tzinfo=timezone.utc)
    assignment = MoodleAssignment(
        id=888,
        course_id=101,
        name="Lab 1: Quicksort Algorithm Implementation",
        intro_text="Write a Python program to implement Quicksort on an array of numbers and print the sorted output.",
        duedate=past_deadline,
        maxfiles=1,
        maxbytes=26214400,
    )
    moodle_client.get_assignments = AsyncMock(return_value=[assignment])

    # Initial state: unsubmitted
    initial_status = MoodleSubmissionStatus(
        assignment_id=888,
        status=SubmissionState.NEW,
        can_submit=True,
    )
    moodle_client.get_submission_status = AsyncMock(return_value=initial_status)

    # File upload mock
    def mock_upload(aid, fpath):
        return MoodleUploadResult(
            assignment_id=aid,
            item_id=5555,
            filename=fpath.name,
            file_size_bytes=fpath.stat().st_size,
            success=True,
            draft_saved=True,
        )

    moodle_client.upload_submission_file = AsyncMock(side_effect=mock_upload)

    # Post-upload verification mock
    verified_status = MoodleSubmissionStatus(
        assignment_id=888,
        status=SubmissionState.DRAFT,
        grading_status=GradingState.NOT_GRADED,
        can_submit=True,
        can_edit=True,
        submitted_files=[
            MoodleFile(
                filename="Lab_1_Quicksort_Algorithm_Implementation_888.pdf",
                filesize=15000,
                timemodified=datetime.now(timezone.utc),
            )
        ],
    )
    moodle_client.verify_submission = AsyncMock(return_value=verified_status)

    # ================= STEP 1: SCAN & DISCOVERY =================
    scanner = AssignmentScanner(moodle_client, session, settings)
    scan_report = await scanner.scan()

    assert scan_report.total_courses == 1
    assert scan_report.total_assignments == 1
    assert scan_report.overdue_assignments == 1
    assert scan_report.new_or_updated_assignments == 1

    assign_repo = AssignmentRepository(session)
    job_repo = ProcessingJobRepository(session)

    db_assign = assign_repo.get_by_moodle_id(888)
    assert db_assign is not None
    assert db_assign.classification == AssignmentClassification.OVERDUE_UNSUBMITTED.value

    # ================= STEP 2: VERIFY JOB CREATION =================
    jobs = session.query(ProcessingJobModel).filter_by(assignment_id=db_assign.id).all()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.stage == JobStage.DISCOVERED.value

    # ================= STEP 3: RUN PIPELINE =================
    processor = JobProcessor(moodle_client, session, settings)
    completed = await processor.process_job(job.id)
    assert completed is True

    # Check resulting job stage
    session.refresh(job)
    assert job.stage in (JobStage.UPLOADING.value, JobStage.VERIFYING.value, JobStage.SUBMITTED.value)

    # Check generated artifacts in DB and on disk
    art_repo = ArtifactRepository(session)
    code_art = art_repo.get_latest_artifact(db_assign.id, ArtifactType.SOLUTION_CODE.value)
    exec_art = art_repo.get_latest_artifact(db_assign.id, ArtifactType.EXECUTION_OUTPUT.value)
    shot_art = art_repo.get_latest_artifact(db_assign.id, ArtifactType.CODE_SCREENSHOT.value)
    out_shot_art = art_repo.get_latest_artifact(db_assign.id, ArtifactType.OUTPUT_SCREENSHOT.value)
    pdf_art = art_repo.get_latest_artifact(db_assign.id, ArtifactType.GENERATED_PDF.value)

    assert code_art is not None and Path(code_art.file_path).exists()
    assert exec_art is not None and Path(exec_art.file_path).exists()
    assert shot_art is not None and Path(shot_art.file_path).exists()
    assert out_shot_art is not None and Path(out_shot_art.file_path).exists()
    assert pdf_art is not None and Path(pdf_art.file_path).exists()
    assert pdf_art.is_validated is True

    # ================= STEP 4: VERIFY UPLOAD RECORD =================
    session.refresh(db_assign)
    assert len(db_assign.upload_attempts) == 1
    attempt = db_assign.upload_attempts[0]
    assert attempt.verified_by_moodle is True
    assert attempt.upload_status == UploadStatus.UPLOADED_DRAFT.value

    # ================= STEP 5: IDEMPOTENCY / RE-RUN TEST =================
    # Running the scan again must NOT re-create jobs or duplicate artifacts
    moodle_client.get_submission_status = AsyncMock(return_value=verified_status)
    scan_report2 = await scanner.scan()
    assert scan_report2.new_or_updated_assignments == 0

    all_jobs = session.query(ProcessingJobModel).filter_by(assignment_id=db_assign.id).all()
    assert len(all_jobs) == 1  # No duplicate job created!

