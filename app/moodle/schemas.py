"""Pydantic schemas for normalized Moodle data structures and operations."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SubmissionState(str, Enum):
    NEW = "new"
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REOPENED = "reopened"
    UNKNOWN = "unknown"


class GradingState(str, Enum):
    NOT_GRADED = "notgraded"
    GRADED = "graded"
    UNKNOWN = "unknown"


class MoodleSiteInfo(BaseModel):
    sitename: str
    username: str
    firstname: str
    lastname: str
    fullname: str
    userid: int
    siteurl: str
    version: Optional[str] = None
    release: Optional[str] = None


class MoodleCourse(BaseModel):
    id: int
    shortname: str
    fullname: str
    category: Optional[str] = None
    enrolled: bool = True


class MoodleFile(BaseModel):
    filename: str
    filepath: Optional[str] = None
    filesize: int
    fileurl: Optional[str] = None
    timemodified: Optional[datetime] = None


class MoodleAssignment(BaseModel):
    id: int
    course_id: int
    name: str
    intro_html: Optional[str] = None
    intro_text: Optional[str] = None
    duedate: Optional[datetime] = None
    allowsubmissionsfromdate: Optional[datetime] = None
    cutoffdate: Optional[datetime] = None
    gradingduedate: Optional[datetime] = None
    maxfiles: int = 1
    maxbytes: int = 26214400  # 25 MB default
    filetypeslist: Optional[str] = None
    requiresubmissionstatement: bool = False
    submissiondrafts: bool = True  # whether draft status exists
    attachments: List[MoodleFile] = Field(default_factory=list)


class MoodleSubmissionStatus(BaseModel):
    assignment_id: int
    status: SubmissionState = SubmissionState.NEW
    grading_status: GradingState = GradingState.NOT_GRADED
    can_submit: bool = True
    can_edit: bool = True
    locked: bool = False
    is_graded: bool = False
    submitted_files: List[MoodleFile] = Field(default_factory=list)
    time_modified: Optional[datetime] = None
    raw_response: Optional[Dict[str, Any]] = None


class MoodleUploadResult(BaseModel):
    assignment_id: int
    item_id: int
    filename: str
    file_size_bytes: int
    success: bool
    draft_saved: bool = False
    error_message: Optional[str] = None


class MoodleFinalizeResult(BaseModel):
    assignment_id: int
    success: bool
    final_status: SubmissionState
    error_message: Optional[str] = None

