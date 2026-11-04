"""High-level assignment fetching and synchronization utilities."""

from typing import List, Optional

from app.logging_config import get_logger
from app.moodle.client import MoodleClient
from app.moodle.schemas import MoodleAssignment

logger = get_logger(__name__)


async def fetch_all_assignments(
    client: MoodleClient,
    course_ids: Optional[List[int]] = None,
    batch_size: int = 10,
) -> List[MoodleAssignment]:
    """Fetch assignments across courses using chunking/pagination to prevent timeouts."""
    if not course_ids:
        courses = await client.get_courses()
        course_ids = [c.id for c in courses]

    all_assignments: List[MoodleAssignment] = []
    # Process in batches
    for i in range(0, len(course_ids), batch_size):
        chunk = course_ids[i : i + batch_size]
        try:
            chunk_assignments = await client.get_assignments(chunk)
            all_assignments.extend(chunk_assignments)
        except Exception as e:
            logger.error(f"Error fetching assignments for course chunk {chunk}: {e}")
            raise

    return all_assignments

