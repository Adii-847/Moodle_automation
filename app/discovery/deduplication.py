"""Deduplication and SHA-256 fingerprinting for assignment instructions and metadata."""

import hashlib
import json
from typing import Optional

from app.moodle.schemas import MoodleAssignment


def compute_assignment_fingerprint(assignment: MoodleAssignment) -> str:
    """Compute stable SHA-256 fingerprint for assignment content and deadlines."""
    payload = {
        "id": assignment.id,
        "name": (assignment.name or "").strip(),
        "intro_text": (assignment.intro_text or "").strip(),
        "duedate": assignment.duedate.isoformat() if assignment.duedate else None,
        "maxfiles": assignment.maxfiles,
        "maxbytes": assignment.maxbytes,
        "filetypeslist": assignment.filetypeslist or "",
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_job_key(assignment_id: int, stage: str, fingerprint: str) -> str:
    """Generate unique and idempotent key for a processing job."""
    return f"assign_{assignment_id}_{stage}_{fingerprint[:16]}"


def has_assignment_changed(old_fingerprint: Optional[str], new_fingerprint: str) -> bool:
    """Return True if assignment content or deadline changed since last scan."""
    if not old_fingerprint:
        return True
    return old_fingerprint != new_fingerprint

