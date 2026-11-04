"""Unit tests for upload workflow, verification, and reconciliation."""

from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import AppSettings
from app.database.models import (
    ArtifactModel,
    ArtifactType,
    AssignmentModel,
    Base,
    CourseModel,
    JobStage,
    JobStatus,
    ProcessingJobModel,
    UploadStatus,
)
from app.moodle.schemas import (
    MoodleFile,
    MoodleFinalizeResult,
    MoodleSubmissionStatus,
    MoodleUploadResult,
    SubmissionState,
)
from app.uploads.reconciliation import reconcile_assignment_submission
from app.uploads.uploader import AssignmentUploader
from app.uploads.verification import is_equivalent_file_already_uploaded, verify_upload_eligibility


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


def test_verify_upload_eligibility(tmp_path):
    pdf = tmp_path / "valid.pdf"
    pdf.write_bytes(b"%PDF-1.4 test content %%EOF")

    assign = AssignmentModel(
        moodle_assignment_id=1,
        course_id=1,
        name="Lab",
        assignment_fingerprint="fp1",
        max_file_size_bytes=1000000,
    )
    status = MoodleSubmissionStatus(
        assignment_id=1,
        status=SubmissionState.NEW,
        can_submit=True,
    )
    settings = AppSettings()

    ok, reason = verify_upload_eligibility(assign, status, pdf, settings)
    assert ok is True

    # Locked status
    status_locked = MoodleSubmissionStatus(assignment_id=1, status=SubmissionState.NEW, locked=True)
    ok_l, reason_l = verify_upload_eligibility(assign, status_locked, pdf, settings)
    assert ok_l is False
    assert "locked" in reason_l


def test_equivalent_file_detection(tmp_path):
    pdf = tmp_path / "test_file.pdf"
    pdf.write_bytes(b"content of 20 bytes!")

    moodle_files = [
        MoodleFile(filename="other.pdf", filesize=100),
        MoodleFile(filename="test_file.pdf", filesize=len(b"content of 20 bytes!")),
    ]

    assert is_equivalent_file_already_uploaded(moodle_files, pdf) is True

    moodle_files_different = [
        MoodleFile(filename="test_file.pdf", filesize=9999),
    ]
    assert is_equivalent_file_already_uploaded(moodle_files_different, pdf) is False


@pytest.mark.asyncio
async def test_uploader_draft_pipeline(tmp_path, db_session):
    pdf = tmp_path / "submission.pdf"
    pdf.write_bytes(b"%PDF-1.4 sample valid pdf %%EOF")

    course = CourseModel(moodle_course_id=1, short_name="CS", full_name="CS")
    db_session.add(course)
    db_session.flush()

    assign = AssignmentModel(
        course_id=course.id,
        moodle_assignment_id=77,
        name="Lab 7",
        assignment_fingerprint="fp77",
    )
    db_session.add(assign)
    db_session.flush()

    artifact = ArtifactModel(
        assignment_id=assign.id,
        artifact_type=ArtifactType.GENERATED_PDF.value,
        file_path=str(pdf),
        file_size_bytes=pdf.stat().st_size,
        sha256_checksum="abc",
        is_validated=True,
    )
    db_session.add(artifact)
    db_session.flush()

    client = AsyncMock()
    # Before upload
    client.get_submission_status = AsyncMock(
        return_value=MoodleSubmissionStatus(
            assignment_id=77,
            status=SubmissionState.NEW,
            can_submit=True,
        )
    )
    client.upload_submission_file = AsyncMock(
        return_value=MoodleUploadResult(
            assignment_id=77,
            item_id=123,
            filename="submission.pdf",
            file_size_bytes=pdf.stat().st_size,
            success=True,
            draft_saved=True,
        )
    )
    # After upload
    client.verify_submission = AsyncMock(
        return_value=MoodleSubmissionStatus(
            assignment_id=77,
            status=SubmissionState.DRAFT,
            submitted_files=[MoodleFile(filename="submission.pdf", filesize=pdf.stat().st_size)],
        )
    )

    settings = AppSettings(AUTO_FINAL_SUBMIT=False)
    uploader = AssignmentUploader(client=client, session=db_session, settings=settings)

    success, msg, status = await uploader.execute_upload_pipeline(assign.id, artifact.id)

    assert success is True
    assert status.status == SubmissionState.DRAFT
    db_session.refresh(assign)
    assert len(assign.upload_attempts) == 1
    assert assign.upload_attempts[0].upload_status == UploadStatus.UPLOADED_DRAFT.value
