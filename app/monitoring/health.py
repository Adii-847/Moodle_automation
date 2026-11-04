"""System health check and diagnostic inspection."""

import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.moodle.client import MoodleClient, get_moodle_client


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class HealthCheckReport:
    overall_status: HealthStatus
    database_ok: bool
    storage_ok: bool
    free_disk_space_mb: float
    moodle_connection_ok: bool
    errors: list[str] = field(default_factory=list)


class HealthChecker:
    """Verifies operational readiness of database, local storage, and Moodle integration."""

    def __init__(self, session: Session, settings: Optional[AppSettings] = None, client: Optional[MoodleClient] = None):
        self.session = session
        self.settings = settings or get_settings()
        self.client = client or get_moodle_client(self.settings)

    async def check(self) -> HealthCheckReport:
        errors = []
        db_ok = False
        storage_ok = False
        free_mb = 0.0
        moodle_ok = False

        # 1. Database check
        try:
            self.session.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            errors.append(f"Database error: {e}")

        # 2. Storage and Disk space
        try:
            test_file = self.settings.temporary_dir / ".health_test"
            test_file.write_text("health_ok", encoding="utf-8")
            test_file.unlink()
            storage_ok = True

            total, used, free = shutil.disk_usage(self.settings.base_data_dir)
            free_mb = round(free / (1024 * 1024), 2)
            if free_mb < 100:  # less than 100MB
                errors.append(f"Low disk space warning: {free_mb} MB available")
        except Exception as e:
            errors.append(f"Storage error: {e}")

        # 3. Moodle check
        try:
            await self.client.check_connection()
            moodle_ok = True
        except Exception as e:
            errors.append(f"Moodle connectivity check: {e}")

        overall = HealthStatus.HEALTHY
        if not db_ok or not storage_ok:
            overall = HealthStatus.UNHEALTHY
        elif not moodle_ok or free_mb < 100:
            overall = HealthStatus.DEGRADED

        return HealthCheckReport(
            overall_status=overall,
            database_ok=db_ok,
            storage_ok=storage_ok,
            free_disk_space_mb=free_mb,
            moodle_connection_ok=moodle_ok,
            errors=errors,
        )

