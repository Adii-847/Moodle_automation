"""Secrets management and secure credential handling."""

import os
from typing import Optional

from app.config import AppSettings, get_settings


class SecretManager:
    """Provides validated and masked access to sensitive authentication credentials."""

    def __init__(self, settings: Optional[AppSettings] = None):
        self.settings = settings or get_settings()

    def get_api_token(self) -> Optional[str]:
        return self.settings.moodle_api_token

    def get_masked_token(self) -> str:
        token = self.get_api_token()
        if not token:
            return "[NOT_CONFIGURED]"
        if len(token) <= 8:
            return "***"
        return f"{token[:4]}...{token[-4:]}"

    def get_moodle_password(self) -> Optional[str]:
        return self.settings.moodle_password

