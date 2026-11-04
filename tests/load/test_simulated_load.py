"""Load and stress test simulating 100 assignments."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import AppSettings
from app.database.models import AssignmentClassification, Base, ProcessingJobModel
from app.database.repositories import AssignmentRepository, ProcessingJobRepository
from app.discovery.scanner import AssignmentScanner
from app.moodle.schemas import (
    MoodleAssignment,
    MoodleCourse,
    MoodleSubmissionStatus,
    SubmissionState,
)


@pytest.fixture
def load_environment(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    settings = AppSettings(
        BASE_DATA_DIR=tmp_path,
        MAX_CONCURRENT_JOBS=4,
    )
    try:
        yield session, settings
    finally:
        session.close()


@pytest.mark.asyncio
async def test_simulated_workload_100_assignments(load_environment):
    session, settings = load_environment

    total_assignments_count = 100
    now = datetime.now(timezone.utc)

    # 1. Generate 100 mocked Moodle assignments across 10 courses
    courses = [
        MoodleCourse(id=cid, shortname=f"CS{100+cid}", fullname=f"Computer Science {cid}", enrolled=True)
        for cid in range(1, 11)
    ]

    assignments = []
    for i in range(1, total_assignments_count + 1):
        cid = (i % 10) + 1
        due = now - timedelta(days=(i % 5 + 1))  # All overdue
        assignments.append(
            MoodleAssignment(
                id=1000 + i,
                course_id=cid,
                name=f"Assignment #{i}: Algorithmic Problem Solving",
                intro_text=f"Solve problem number {i} in Python.",
                duedate=due,
            )
        )

    client = AsyncMock()
    client.get_courses = AsyncMock(return_value=courses)
    client.get_assignments = AsyncMock(return_value=assignments)

    # Default status: NEW
    client.get_submission_status = AsyncMock(
        return_value=MoodleSubmissionStatus(
            assignment_id=0,
            status=SubmissionState.NEW,
            can_submit=True,
        )
    )

    scanner = AssignmentScanner(client=client, session=session, settings=settings)
    report = await scanner.scan()

    assert report.total_courses == 10
    assert report.total_assignments == 100
    assert report.overdue_assignments == 100

    # Verify 100 jobs created
    jobs = session.query(ProcessingJobModel).all()
    assert len(jobs) == 100

    # Run scan a second time immediately to ensure absolute idempotency
    report2 = await scanner.scan()
    assert report2.new_or_updated_assignments == 0

    jobs_after = session.query(ProcessingJobModel).all()
    assert len(jobs_after) == 100  # Zero duplicate jobs!

