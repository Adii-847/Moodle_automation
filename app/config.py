"""Application configuration module with strong validation via Pydantic Settings."""

from enum import Enum
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationMode(str, Enum):
    AUTO = "auto"
    API = "api"
    BROWSER = "browser"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Moodle settings
    moodle_base_url: str = Field(
        default="http://localhost:8080",
        alias="MOODLE_BASE_URL",
        description="Base URL of the Moodle instance (e.g. https://moodle.college.edu)",
    )
    moodle_integration_mode: IntegrationMode = Field(
        default=IntegrationMode.AUTO,
        alias="MOODLE_INTEGRATION_MODE",
        description="Integration mode: 'auto', 'api', or 'browser'",
    )
    moodle_api_token: Optional[str] = Field(
        default=None,
        alias="MOODLE_API_TOKEN",
        description="REST API token for Moodle Web Services",
    )
    moodle_username: Optional[str] = Field(
        default=None,
        alias="MOODLE_USERNAME",
        description="Moodle username for browser or token authentication",
    )
    moodle_password: Optional[str] = Field(
        default=None,
        alias="MOODLE_PASSWORD",
        description="Moodle password for browser authentication (kept securely in memory)",
    )

    # Database and Caching
    database_url: str = Field(
        default="sqlite:///./data/moodle_automation.db",
        alias="DATABASE_URL",
        description="SQLAlchemy database connection string (PostgreSQL or SQLite)",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
        description="Redis connection URL for distributed locking/queue",
    )

    # Student info for report generation
    student_name: str = Field(
        default="Student",
        alias="STUDENT_NAME",
        description="Full student name displayed on assignment covers",
    )
    student_uid: str = Field(
        default="STU-00000",
        alias="STUDENT_UID",
        description="Student Roll / Identification Number",
    )
    institution_name: str = Field(
        default="College of Engineering and Technology",
        alias="INSTITUTION_NAME",
        description="Institution or department name",
    )

    # Timezone & Scheduling
    timezone: str = Field(
        default="Asia/Kolkata",
        alias="TIMEZONE",
        description="Institutional local timezone for deadline interpretation",
    )
    scan_interval_minutes: int = Field(
        default=180,
        alias="SCAN_INTERVAL_MINUTES",
        ge=5,
        description="Interval in minutes between automated assignment scans",
    )
    max_concurrent_jobs: int = Field(
        default=2,
        alias="MAX_CONCURRENT_JOBS",
        ge=1,
        le=16,
        description="Maximum concurrent jobs to process simultaneously",
    )
    max_retries: int = Field(
        default=3,
        alias="MAX_RETRIES",
        ge=0,
        le=10,
        description="Maximum retry attempts for transient errors",
    )
    request_timeout_seconds: int = Field(
        default=30,
        alias="REQUEST_TIMEOUT_SECONDS",
        ge=5,
        le=300,
        description="HTTP client timeout in seconds",
    )
    max_file_size_mb: int = Field(
        default=25,
        alias="MAX_FILE_SIZE_MB",
        ge=1,
        le=200,
        description="Maximum permitted PDF / submission file size in MB",
    )

    # Safety Controls
    auto_upload: bool = Field(
        default=False,
        alias="AUTO_UPLOAD",
        description="If True, ready PDFs will be uploaded to Moodle as draft/files",
    )
    auto_final_submit: bool = Field(
        default=False,
        alias="AUTO_FINAL_SUBMIT",
        description="CRITICAL: If True, submissions will be finalized in Moodle. MUST be explicitly enabled.",
    )
    auto_approve: bool = Field(
        default=False,
        alias="AUTO_APPROVE",
        description="If True, tasks bypass manual review state if validation tests pass",
    )

    # Observability
    log_level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )

    # Paths
    base_data_dir: Path = Field(
        default=Path("./data"),
        alias="BASE_DATA_DIR",
        description="Base directory for persistence and artifacts",
    )
    browser_storage_state_path: Path = Field(
        default=Path("./data/browser_state.json"),
        alias="BROWSER_STORAGE_STATE_PATH",
        description="Path to stored Playwright browser authentication state",
    )
    playwright_headless: bool = Field(
        default=True,
        alias="PLAYWRIGHT_HEADLESS",
        description="Whether to run browser automation in headless mode",
    )

    # Sandbox limits
    sandbox_max_execution_time_seconds: int = Field(
        default=15,
        alias="SANDBOX_MAX_EXECUTION_TIME_SECONDS",
        ge=1,
        le=60,
    )
    sandbox_max_output_chars: int = Field(
        default=50000,
        alias="SANDBOX_MAX_OUTPUT_CHARS",
        ge=1000,
        le=500000,
    )

    @field_validator("moodle_base_url")
    @classmethod
    def validate_moodle_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(f"Moodle base URL must begin with http:// or https://, got: {v}")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, Exception):
            raise ValueError(f"Invalid timezone: {v}. Must be a valid IANA timezone string.")
        return v

    @property
    def screenshots_dir(self) -> Path:
        p = self.base_data_dir / "screenshots"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def generated_pdfs_dir(self) -> Path:
        p = self.base_data_dir / "generated_pdfs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def temporary_dir(self) -> Path:
        p = self.base_data_dir / "temporary"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


_settings: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    """Retrieve cached application settings instance."""
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings


def reset_settings(new_settings: Optional[AppSettings] = None) -> AppSettings:
    """Reset cached settings, used primarily in tests."""
    global _settings
    _settings = new_settings
    return get_settings()

