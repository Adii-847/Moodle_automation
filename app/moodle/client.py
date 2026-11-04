"""Abstract Moodle Client interface and factory definition."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from app.config import AppSettings, IntegrationMode, get_settings
from app.moodle.schemas import (
    MoodleAssignment,
    MoodleCourse,
    MoodleFinalizeResult,
    MoodleSiteInfo,
    MoodleSubmissionStatus,
    MoodleUploadResult,
)


class MoodleError(Exception):
    """Base exception for Moodle operations."""
    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code or "MOODLE_ERROR"


class MoodleAuthenticationError(MoodleError):
    """Raised when token or session credentials are invalid or expired."""
    def __init__(self, message: str = "Moodle authentication failed"):
        super().__init__(message, error_code="AUTH_FAILED")


class MoodleSessionExpiredError(MoodleAuthenticationError):
    """Raised when an active session has expired."""
    def __init__(self, message: str = "Moodle session expired, re-authentication required"):
        super().__init__(message)
        self.error_code = "SESSION_EXPIRED"


class MoodlePermissionError(MoodleError):
    """Raised when an operation lacks necessary permissions."""
    def __init__(self, message: str = "Permission denied for Moodle operation"):
        super().__init__(message, error_code="PERMISSION_DENIED")


class MoodleNotFoundError(MoodleError):
    """Raised when course, assignment, or submission is not found."""
    def __init__(self, message: str = "Requested resource not found"):
        super().__init__(message, error_code="NOT_FOUND")


class MoodleClient(ABC):
    """Unified interface covering both Web Services API and Browser fallback."""

    @abstractmethod
    async def check_connection(self) -> MoodleSiteInfo:
        """Verify connectivity and authentication with Moodle instance."""
        pass

    @abstractmethod
    async def get_courses(self) -> List[MoodleCourse]:
        """Fetch all courses the authenticated student is enrolled in."""
        pass

    @abstractmethod
    async def get_assignments(self, course_ids: Optional[List[int]] = None) -> List[MoodleAssignment]:
        """Fetch all assignments for the specified course IDs (or all courses)."""
        pass

    @abstractmethod
    async def get_assignment_details(self, assignment_id: int) -> MoodleAssignment:
        """Fetch details for a single assignment."""
        pass

    @abstractmethod
    async def get_submission_status(self, assignment_id: int) -> MoodleSubmissionStatus:
        """Fetch submission status, existing files, and permissions for an assignment."""
        pass

    @abstractmethod
    async def upload_submission_file(self, assignment_id: int, file_path: Path) -> MoodleUploadResult:
        """Upload file as draft submission for assignment."""
        pass

    @abstractmethod
    async def finalize_submission(self, assignment_id: int) -> MoodleFinalizeResult:
        """Confirm/finalize assignment submission for grading."""
        pass

    @abstractmethod
    async def verify_submission(self, assignment_id: int) -> MoodleSubmissionStatus:
        """Authoritatively query Moodle to verify submitted state."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Cleanly close underlying sessions, connections, or browser contexts."""
        pass


def get_moodle_client(settings: Optional[AppSettings] = None) -> MoodleClient:
    """Factory creating appropriate client based on integration mode settings."""
    cfg = settings or get_settings()
    from app.moodle.api_client import MoodleApiClient
    from app.moodle.browser_client import MoodleBrowserClient

    if cfg.moodle_integration_mode == IntegrationMode.API:
        return MoodleApiClient(cfg)
    elif cfg.moodle_integration_mode == IntegrationMode.BROWSER:
        return MoodleBrowserClient(cfg)
    else:  # AUTO
        if cfg.moodle_api_token:
            return MoodleApiClient(cfg)
        return MoodleBrowserClient(cfg)

