"""Scheduler service with bounded concurrency, scan locking, and startup crash recovery."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.database.models import JobStage, JobStatus, ProcessingJobModel
from app.database.repositories import ProcessingJobRepository
from app.database.session import get_db_session
from app.discovery.scanner import AssignmentScanner
from app.jobs.tasks import JobProcessor
from app.logging_config import get_logger
from app.moodle.client import MoodleClient, get_moodle_client

logger = get_logger(__name__)


class AssignmentScheduler:
    """Manages scheduled background scans, bounded worker concurrency, and recovery."""

    def __init__(self, settings: Optional[AppSettings] = None, client: Optional[MoodleClient] = None):
        self.settings = settings or get_settings()
        self.client = client or get_moodle_client(self.settings)
        self.semaphore = asyncio.Semaphore(self.settings.max_concurrent_jobs)
        self._is_scanning = False
        self._shutdown_event = asyncio.Event()

    async def recover_from_crash(self) -> int:
        """Inspect and recover any jobs interrupted by a previous process crash."""
        logger.info("Executing startup crash recovery check...")
        recovered_count = 0
        with get_db_session() as session:
            job_repo = ProcessingJobRepository(session)
            interrupted = job_repo.get_interrupted_jobs()

            for job in interrupted:
                logger.warning(
                    f"Recovering interrupted job {job.id} at stage {job.stage}",
                    extra={"job_id": job.id, "stage": job.stage},
                )
                # Roll back to PENDING so the worker can resume safely
                job.status = JobStatus.PENDING.value
                recovered_count += 1

            session.commit()

        # Clean abandoned temporary files if needed
        temp_dir = self.settings.temporary_dir
        if temp_dir.exists():
            for p in temp_dir.glob("assign_*"):
                if p.is_dir():
                    logger.debug(f"Preserving existing workspace: {p}")

        logger.info(f"Crash recovery complete. {recovered_count} jobs restored.")
        return recovered_count

    async def run_scan_cycle(self) -> None:
        """Execute a single assignment discovery scan with locking to prevent duplicates."""
        if self._is_scanning:
            logger.warning("Scan cycle already in progress; skipping duplicate trigger.")
            return

        self._is_scanning = True
        try:
            with get_db_session() as session:
                scanner = AssignmentScanner(self.client, session, self.settings)
                report = await scanner.scan()
                session.commit()
                logger.info(f"Scan finished: {report.total_assignments} assignments found.")
        except Exception as e:
            logger.error(f"Error during scan cycle: {e}", exc_info=True)
        finally:
            self._is_scanning = False

    async def process_pending_jobs(self) -> int:
        """Dispatch pending and due retry jobs under bounded concurrency."""
        with get_db_session() as session:
            now = datetime.now(timezone.utc)
            # Find jobs that are PENDING or ready for retry
            stmt = select(ProcessingJobModel.id).where(
                (ProcessingJobModel.status == JobStatus.PENDING.value)
                | (
                    and_(
                        ProcessingJobModel.status == JobStatus.FAILED.value,
                        ProcessingJobModel.is_permanent_failure == False,
                        ProcessingJobModel.next_retry_at <= now,
                    )
                )
            ).order_by(ProcessingJobModel.id)
            job_ids = list(session.execute(stmt).scalars().all())

        if not job_ids:
            return 0

        async def worker(jid: int):
            async with self.semaphore:
                with get_db_session() as sess:
                    processor = JobProcessor(self.client, sess, self.settings)
                    await processor.process_job(jid)
                    sess.commit()

        tasks = [asyncio.create_task(worker(jid)) for jid in job_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
        return len(job_ids)

    async def start(self) -> None:
        """Main scheduler loop."""
        await self.recover_from_crash()

        interval_seconds = self.settings.scan_interval_minutes * 60
        logger.info(f"Starting AssignmentScheduler with {interval_seconds}s scan interval.")

        while not self._shutdown_event.is_set():
            try:
                await self.run_scan_cycle()
                await self.process_pending_jobs()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)

            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=min(60.0, interval_seconds))
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        logger.info("Stopping AssignmentScheduler...")
        self._shutdown_event.set()

