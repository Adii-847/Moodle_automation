"""Authentication helper and session lifecycle management."""

import json
from pathlib import Path
from typing import Optional

from app.config import AppSettings
from app.logging_config import get_logger
from app.moodle.client import MoodleAuthenticationError, MoodleClient, get_moodle_client

logger = get_logger(__name__)


class AuthenticationManager:
    """Manages credentials, session verification, and reauthentication states."""

    def __init__(self, settings: AppSettings, client: Optional[MoodleClient] = None):
        self.settings = settings
        self.client = client or get_moodle_client(settings)

    async def verify_authentication(self) -> bool:
        """Validate whether current token or browser session is active."""
        try:
            site_info = await self.client.check_connection()
            logger.info("Moodle connection verified", extra={"username": site_info.username, "site": site_info.sitename})
            return True
        except MoodleAuthenticationError as e:
            logger.warning(f"Moodle authentication check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking Moodle authentication: {e}")
            return False

    def check_browser_storage_exists(self) -> bool:
        return self.settings.browser_storage_state_path.exists()

    def clear_stored_browser_session(self) -> None:
        if self.settings.browser_storage_state_path.exists():
            try:
                self.settings.browser_storage_state_path.unlink()
                logger.info("Cleared browser session state file")
            except OSError as e:
                logger.error(f"Failed to remove browser session state file: {e}")

