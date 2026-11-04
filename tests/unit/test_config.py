"""Unit tests for configuration validation."""

import pytest
from pydantic import ValidationError

from app.config import AppSettings, IntegrationMode


def test_default_config_valid():
    # Instantiate with explicit values to isolate from any .env file on disk
    settings = AppSettings(
        MOODLE_BASE_URL="http://localhost:8080",
        MOODLE_INTEGRATION_MODE="auto",
        AUTO_UPLOAD="false",
        AUTO_FINAL_SUBMIT="false",
        TIMEZONE="Asia/Kolkata",
        _env_file=None,  # ignore .env file
    )
    assert settings.moodle_base_url == "http://localhost:8080"
    assert settings.moodle_integration_mode == IntegrationMode.AUTO
    assert settings.auto_upload is False
    assert settings.auto_final_submit is False
    assert settings.timezone == "Asia/Kolkata"


def test_invalid_moodle_url():
    with pytest.raises(ValidationError):
        AppSettings(MOODLE_BASE_URL="ftp://invalid.url")


def test_invalid_timezone():
    with pytest.raises(ValidationError):
        AppSettings(TIMEZONE="Invalid/Nonexistent_Timezone")


def test_url_trailing_slash_normalization():
    settings = AppSettings(MOODLE_BASE_URL="https://moodle.example.edu/")
    assert settings.moodle_base_url == "https://moodle.example.edu"


def test_derived_directories(tmp_path):
    settings = AppSettings(BASE_DATA_DIR=tmp_path)
    assert settings.screenshots_dir.exists()
    assert settings.generated_pdfs_dir.exists()
    assert settings.temporary_dir.exists()

