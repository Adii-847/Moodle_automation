"""Command-line interface (CLI) for Moodle Assignment Automation System."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

# Reconfigure console streams to UTF-8 on Windows to prevent UnicodeEncodeError in terminal output
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config import get_settings
from app.database.models import (
    ArtifactType,
    AssignmentClassification,
    JobStage,
    JobStatus,
    ProcessingJobModel,
)
from app.database.repositories import (
    ArtifactRepository,
    AssignmentRepository,
    ProcessingJobRepository,
)
from app.database.session import get_db_session, init_db
from app.discovery.scanner import AssignmentScanner
from app.jobs.scheduler import AssignmentScheduler
from app.jobs.tasks import JobProcessor
from app.logging_config import configure_logging
from app.monitoring.health import HealthChecker
from app.monitoring.metrics import MetricsCollector
from app.moodle.client import get_moodle_client

app = typer.Typer(
    name="moodle-auto",
    help="Production-quality Moodle Assignment Automation System CLI",
    add_completion=False,
)
console = Console()


@app.callback()
def main(
    log_level: str = typer.Option("INFO", "--log-level", "-l", help="Logging level"),
    json_logs: bool = typer.Option(False, "--json-logs", help="Enable structured JSON log output"),
):
    configure_logging(log_level=log_level, json_format=json_logs)
    init_db()


@app.command()
def connect():
    """Verify connectivity and authentication with the configured Moodle instance."""
    async def _run():
        settings = get_settings()
        mode = settings.moodle_integration_mode.value
        console.print(f"[bold cyan]Connecting to Moodle at:[/] {settings.moodle_base_url}  [dim](mode: {mode})[/dim]")
        if mode == "browser":
            if settings.moodle_username:
                console.print(f"[dim]Browser login will use username:[/dim] {settings.moodle_username}")
            else:
                console.print("[yellow]Warning:[/] MOODLE_USERNAME not set. If session is expired, automatic login will fail.")
        client = get_moodle_client(settings)
        try:
            site_info = await client.check_connection()
            table = Table(title="Moodle Connection Verified")
            table.add_column("Property", style="bold")
            table.add_column("Value", style="green")
            table.add_row("Site Name", site_info.sitename)
            table.add_row("Username", site_info.username)
            table.add_row("Student Name", site_info.fullname)
            table.add_row("User ID", str(site_info.userid))
            table.add_row("Integration Mode", mode)
            console.print(table)
        except Exception as e:
            console.print(f"[bold red]Authentication / Connection Failed:[/] {e}")
            if mode == "browser":
                console.print(
                    "[yellow]Tip:[/] Run [bold]moodle-auto login[/] for an interactive browser login "
                    "session where you can complete SSO or MFA manually."
                )
            raise typer.Exit(code=1)
        finally:
            await client.close()

    asyncio.run(_run())


@app.command()
def login(
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode (default: visible)"),
):
    """Open an interactive browser window to log in to Moodle manually (handles SSO/MFA).

    After you complete login, the session is saved to disk so subsequent commands
    can run without re-entering credentials. Use this when automated form login
    fails due to SSO redirect, MFA, or CAPTCHA.
    """
    async def _run():
        from playwright.async_api import async_playwright

        settings = get_settings()
        console.print(f"[bold cyan]Opening browser for manual login:[/] {settings.moodle_base_url}")
        console.print("[yellow]Complete the login in the browser window, then press ENTER here to save the session.[/]")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            storage_state = str(settings.browser_storage_state_path) if settings.browser_storage_state_path.exists() else None
            context = await browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            await page.goto(f"{settings.moodle_base_url}/login/index.php")

            console.print("[dim]Browser is open. Log in, then press ENTER in this terminal to save session.[/dim]")
            await asyncio.get_event_loop().run_in_executor(None, input, "")

            # Save session state
            settings.browser_storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(settings.browser_storage_state_path))
            console.print(f"[green]Session saved to:[/] {settings.browser_storage_state_path}")

            await page.close()
            await context.close()
            await browser.close()

        console.print("[bold green]Login complete.[/] Run [bold]moodle-auto connect[/] to verify.")

    asyncio.run(_run())


@app.command()
def scan():
    """Scan enrolled courses and discover overdue and upcoming assignments."""
    async def _run():
        settings = get_settings()
        client = get_moodle_client(settings)
        try:
            with get_db_session() as session:
                scanner = AssignmentScanner(client, session, settings)
                report = await scanner.scan()
                session.commit()

            table = Table(title="Assignment Scan Results")
            table.add_column("Metric", style="bold")
            table.add_column("Count", style="cyan")
            table.add_row("Enrolled Courses", str(report.total_courses))
            table.add_row("Total Assignments", str(report.total_assignments))
            table.add_row("New / Updated", str(report.new_or_updated_assignments))
            table.add_row("Overdue (Unsubmitted)", f"[bold red]{report.overdue_assignments}[/]")
            table.add_row("Due Soon", f"[bold yellow]{report.due_soon_assignments}[/]")
            table.add_row("Submitted / Graded", f"[bold green]{report.submitted_assignments}[/]")
            table.add_row("Review Required", f"[bold magenta]{report.review_required_assignments}[/]")
            console.print(table)
        except Exception as e:
            console.print(f"[bold red]Scan failed:[/] {e}")
            raise typer.Exit(code=1)
        finally:
            await client.close()

    asyncio.run(_run())


@app.command(name="list")
def list_assignments(
    classification: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter by classification"),
):
    """List discovered assignments and their current status."""
    with get_db_session() as session:
        repo = AssignmentRepository(session)
        if classification:
            assignments = repo.get_by_classification(classification.upper())
        else:
            assignments = repo.get_all()

        if not assignments:
            console.print("[yellow]No assignments found matching criteria.[/]")
            return

        table = Table(title="Discovered Assignments")
        table.add_column("ID", style="bold")
        table.add_column("Moodle ID")
        table.add_column("Course")
        table.add_column("Assignment Name")
        table.add_column("Due Date (UTC)")
        table.add_column("Classification")
        table.add_column("Moodle Status")
        table.add_column("Review Required?")

        for a in assignments:
            due_str = a.due_date.strftime("%Y-%m-%d %H:%M") if a.due_date else "None"
            cls_color = "red" if "OVERDUE" in a.classification else ("yellow" if "DUE_SOON" in a.classification else "green")
            table.add_row(
                str(a.id),
                str(a.moodle_assignment_id),
                a.course.short_name if a.course else "N/A",
                a.name[:35],
                due_str,
                f"[{cls_color}]{a.classification}[/]",
                a.submission_status_moodle,
                "[bold red]YES[/]" if a.needs_manual_review else "No",
            )
        console.print(table)


@app.command()
def view(assignment_id: int):
    """View detailed instructions, metadata, and artifacts for an assignment."""
    with get_db_session() as session:
        repo = AssignmentRepository(session)
        assign = repo.get_by_id(assignment_id)
        if not assign:
            console.print(f"[bold red]Assignment ID {assignment_id} not found.[/]")
            raise typer.Exit(code=1)

        console.print(Panel(
            f"[bold cyan]Course:[/] {assign.course.full_name if assign.course else 'N/A'}\n"
            f"[bold cyan]Due Date:[/] {assign.due_date}\n"
            f"[bold cyan]Classification:[/] {assign.classification}\n"
            f"[bold cyan]Submission Status:[/] {assign.submission_status_moodle}\n"
            f"[bold cyan]Needs Review:[/] {assign.needs_manual_review} ({assign.review_reason or 'None'})\n\n"
            f"[bold]Instructions:[/]\n{assign.description_text or assign.description_html or 'No instructions provided.'}",
            title=f"Assignment #{assign.id}: {assign.name}",
        ))

        if assign.artifacts:
            art_table = Table(title="Attached Artifacts")
            art_table.add_column("Type")
            art_table.add_column("File Path")
            art_table.add_column("Size (Bytes)")
            art_table.add_column("Validated?")
            for art in assign.artifacts:
                art_table.add_row(art.artifact_type, art.file_path, str(art.file_size_bytes), "Yes" if art.is_validated else "No")
            console.print(art_table)


@app.command()
def process(assignment_id: int):
    """Advance an assignment through the generation, execution, screenshot, and PDF pipeline."""
    async def _run():
        settings = get_settings()
        client = get_moodle_client(settings)
        try:
            with get_db_session() as session:
                assign_repo = AssignmentRepository(session)
                job_repo = ProcessingJobRepository(session)

                assign = assign_repo.get_by_id(assignment_id)
                if not assign:
                    console.print(f"[bold red]Assignment ID {assignment_id} not found.[/]")
                    raise typer.Exit(code=1)

                job_key = f"cli_process_assign_{assign.id}_{assign.assignment_fingerprint[:12]}"
                job, _ = job_repo.create_or_get_job(
                    job_key=job_key,
                    assignment_id=assign.id,
                    stage=JobStage.DISCOVERED.value,
                    correlation_id=f"cli_{assign.id}",
                )
                session.commit()

                processor = JobProcessor(client, session, settings)
                console.print(f"[bold cyan]Processing assignment #{assignment_id}...[/]")
                await processor.process_job(job.id)
                session.commit()

                session.refresh(job)
                console.print(f"[bold green]Processing concluded at stage:[/] {job.stage} ([cyan]{job.status}[/])")
        finally:
            await client.close()

    asyncio.run(_run())


@app.command()
def preview(assignment_id: int):
    """Display information about generated PDF artifacts for an assignment."""
    with get_db_session() as session:
        art_repo = ArtifactRepository(session)
        pdf_art = art_repo.get_latest_artifact(assignment_id, ArtifactType.GENERATED_PDF.value)
        if not pdf_art:
            console.print(f"[yellow]No generated PDF found for assignment ID {assignment_id}. Run 'process {assignment_id}' first.[/]")
            return

        console.print(Panel(
            f"[bold green]PDF File Path:[/] {pdf_art.file_path}\n"
            f"[bold]Size:[/] {pdf_art.file_size_bytes / 1024:.1f} KB\n"
            f"[bold]SHA-256 Checksum:[/] {pdf_art.sha256_checksum}\n"
            f"[bold]Validation Status:[/] {'PASSED' if pdf_art.is_validated else 'PENDING'}\n"
            f"[bold]Notes:[/] {pdf_art.validation_notes or 'None'}",
            title=f"Preview PDF Artifact: Assignment #{assignment_id}",
        ))


@app.command()
def approve(assignment_id: int):
    """Approve an assignment that is awaiting manual approval, unlocking the upload stage."""
    with get_db_session() as session:
        assign_repo = AssignmentRepository(session)
        assign = assign_repo.get_by_id(assignment_id)
        if not assign:
            console.print(f"[bold red]Assignment ID {assignment_id} not found.[/]")
            raise typer.Exit(code=1)

        # Find job in AWAITING_APPROVAL
        for job in assign.jobs:
            if job.stage == JobStage.AWAITING_APPROVAL.value:
                job.stage = JobStage.UPLOADING.value
                job.status = JobStatus.PENDING.value
                session.commit()
                console.print(f"[bold green]Assignment #{assignment_id} approved. Transitioned to UPLOADING stage.[/]")
                return

        console.print(f"[yellow]No job currently in AWAITING_APPROVAL stage for assignment #{assignment_id}.[/]")


@app.command()
def upload(assignment_id: int):
    """Safely upload the validated PDF submission to Moodle."""
    async def _run():
        settings = get_settings()
        client = get_moodle_client(settings)
        try:
            with get_db_session() as session:
                assign_repo = AssignmentRepository(session)
                art_repo = ArtifactRepository(session)

                assign = assign_repo.get_by_id(assignment_id)
                if not assign:
                    console.print(f"[bold red]Assignment ID {assignment_id} not found.[/]")
                    raise typer.Exit(code=1)

                pdf_art = art_repo.get_latest_artifact(assignment_id, ArtifactType.GENERATED_PDF.value)
                if not pdf_art:
                    console.print(f"[bold red]No validated PDF artifact found for assignment #{assignment_id}. Run process first.[/]")
                    raise typer.Exit(code=1)

                from app.uploads.uploader import AssignmentUploader
                uploader = AssignmentUploader(client, session, settings)
                console.print(f"[bold cyan]Uploading submission for assignment #{assignment_id}...[/]")
                ok, msg, status = await uploader.execute_upload_pipeline(assign.id, pdf_art.id)
                session.commit()

                if ok:
                    console.print(f"[bold green]Upload verified successfully![/] Moodle Status: [cyan]{status.status.value}[/]")
                else:
                    console.print(f"[bold red]Upload was not confirmed:[/] {msg}")
        finally:
            await client.close()

    asyncio.run(_run())


@app.command()
def verify(assignment_id: int):
    """Authoritatively query Moodle to verify submission status."""
    async def _run():
        settings = get_settings()
        client = get_moodle_client(settings)
        try:
            with get_db_session() as session:
                assign_repo = AssignmentRepository(session)
                assign = assign_repo.get_by_id(assignment_id)
                if not assign:
                    console.print(f"[bold red]Assignment ID {assignment_id} not found.[/]")
                    raise typer.Exit(code=1)

                status = await client.verify_submission(assign.moodle_assignment_id)
                table = Table(title=f"Moodle Verification: {assign.name}")
                table.add_column("Property", style="bold")
                table.add_column("Value")
                table.add_row("Status", f"[bold green]{status.status.value}[/]")
                table.add_row("Grading Status", status.grading_status.value)
                table.add_row("Can Submit More?", "Yes" if status.can_submit else "No")
                table.add_row("Can Edit?", "Yes" if status.can_edit else "No")
                table.add_row("Locked?", "[red]YES[/]" if status.locked else "No")
                table.add_row("Submitted Files", ", ".join(f.filename for f in status.submitted_files) or "None")
                console.print(table)
        finally:
            await client.close()

    asyncio.run(_run())


@app.command()
def status():
    """Display overall system health and aggregated operational metrics."""
    async def _run():
        with get_db_session() as session:
            checker = HealthChecker(session)
            report = await checker.check()

            health_color = "green" if report.overall_status.value == "HEALTHY" else ("yellow" if report.overall_status.value == "DEGRADED" else "red")
            console.print(Panel(
                f"[bold]Overall Status:[/] [{health_color}]{report.overall_status.value}[/]\n"
                f"Database: {'[green]OK[/]' if report.database_ok else '[red]FAIL[/]'}\n"
                f"Storage: {'[green]OK[/]' if report.storage_ok else '[red]FAIL[/]'} ({report.free_disk_space_mb:.1f} MB Free)\n"
                f"Moodle Connectivity: {'[green]OK[/]' if report.moodle_connection_ok else '[red]FAIL[/]'}\n"
                + (f"Errors: {', '.join(report.errors)}" if report.errors else "No diagnostic errors detected."),
                title="System Health Report",
            ))

            collector = MetricsCollector(session)
            metrics = collector.collect()

            table = Table(title="Queue and Processing Metrics")
            table.add_column("Metric", style="bold")
            table.add_column("Value", style="cyan")
            table.add_row("Total Assignments", str(metrics.total_assignments))
            table.add_row("Overdue Assignments", str(metrics.overdue_assignments))
            table.add_row("Due Soon Assignments", str(metrics.due_soon_assignments))
            table.add_row("Requires Review", str(metrics.review_required_assignments))
            table.add_row("Total Jobs", str(metrics.total_jobs))
            table.add_row("Pending Jobs", str(metrics.pending_jobs))
            table.add_row("Running Jobs", str(metrics.running_jobs))
            table.add_row("Completed Jobs", str(metrics.completed_jobs))
            table.add_row("Failed Jobs", str(metrics.failed_jobs))
            table.add_row("Generated PDFs", str(metrics.generated_pdfs))
            table.add_row("Verified Submissions", f"[bold green]{metrics.verified_submissions}[/]")
            table.add_row("Unconfirmed Uploads", f"[bold yellow]{metrics.unconfirmed_uploads}[/]")
            console.print(table)

    asyncio.run(_run())


@app.command()
def scheduler():
    """Run the continuous background assignment scanner and worker queue."""
    scheduler_service = AssignmentScheduler()
    try:
        asyncio.run(scheduler_service.start())
    except (KeyboardInterrupt, SystemExit):
        scheduler_service.stop()
        console.print("[yellow]Scheduler service gracefully stopped.[/]")


if __name__ == "__main__":
    app()

