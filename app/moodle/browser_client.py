"""Playwright-based browser client for interactive, SSO, or Web-Services-restricted Moodle instances.

This module implements a robust browser-driven Moodle client that:
- Performs automated form login using username/password from settings.
- Restores and persists browser session state (cookies/localStorage) between runs.
- Discovers enrolled courses via the Moodle course overview page.
- Discovers assignments by navigating each course and scraping the activity list.
- Fetches per-assignment details including due dates, instructions, and submission state.
- Uploads files via the browser file-picker and saves draft submissions.
- Verifies submission status authoritatively by re-scraping the assignment page.

Design constraints:
- Does NOT bypass CAPTCHA, MFA, or institutional access controls.
- Does NOT automate the SSO redirect flow; if SSO is encountered after credentials
  fail, a MoodleAuthenticationError is raised so the user can handle it manually.
- Credentials are never written to logs.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

from app.config import AppSettings
from app.logging_config import get_logger
from app.moodle.client import (
    MoodleAuthenticationError,
    MoodleClient,
    MoodleError,
    MoodleNotFoundError,
    MoodleSessionExpiredError,
)
from app.moodle.schemas import (
    GradingState,
    MoodleAssignment,
    MoodleCourse,
    MoodleFile,
    MoodleFinalizeResult,
    MoodleSiteInfo,
    MoodleSubmissionStatus,
    MoodleUploadResult,
    SubmissionState,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Login page detection
# ---------------------------------------------------------------------------

_LOGIN_PATH_FRAGMENTS = ("/login/", "/login.php", "login/index.php", "login/index")
_LOGGED_OUT_TEXTS = ("log in", "forgotten your username or password", "username", "password")


def _looks_like_login_page(url: str, page_title: str) -> bool:
    """Return True if the current URL or title indicates a login / session-expired page."""
    url_lower = url.lower()
    if any(frag in url_lower for frag in _LOGIN_PATH_FRAGMENTS):
        return True
    title_lower = page_title.lower()
    if any(kw in title_lower for kw in ("log in", "login", "sign in")):
        return True
    return False


def _extract_id_from_href(href: str, param: str = "id") -> Optional[int]:
    """Parse ?id=<int> from a URL fragment, returning None on failure."""
    try:
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        values = params.get(param, [])
        if values:
            return int(values[0])
    except (ValueError, TypeError):
        pass
    return None


def _parse_moodle_timestamp(text: str) -> Optional[datetime]:
    """
    Attempt to parse human-readable Moodle due-date strings such as:
      "Tuesday, 5 November 2024, 11:59 PM"
      "5 November 2024, 11:59 PM"
    Returns a timezone-aware UTC datetime or None.
    """
    text = text.strip()
    formats = [
        "%A, %d %B %Y, %I:%M %p",
        "%d %B %Y, %I:%M %p",
        "%A, %d %B %Y, %H:%M",
        "%d %B %Y, %H:%M",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class MoodleBrowserClient(MoodleClient):
    """Playwright-driven client implementing browser fallback for Moodle automation."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.base_url = settings.moodle_base_url.rstrip("/")
        self.storage_state_path = settings.browser_storage_state_path
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._authenticated = False

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        """Initialize Playwright, restore session state, and ensure authentication."""
        if self._page is not None and self._authenticated:
            return

        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        if self._browser is None:
            self._browser = await self._playwright.chromium.launch(
                headless=self.settings.playwright_headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )

        if self._context is None:
            storage_state = str(self.storage_state_path) if self.storage_state_path.exists() else None
            self._context = await self._browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                accept_downloads=True,
            )
            self._page = await self._context.new_page()

        await self._ensure_authenticated()

    async def _ensure_authenticated(self) -> None:
        """Navigate to the dashboard; if redirected to login, perform form login."""
        dashboard_url = f"{self.base_url}/my/"
        timeout_ms = self.settings.request_timeout_seconds * 1000

        await self._page.goto(dashboard_url, wait_until="domcontentloaded", timeout=timeout_ms)
        current_url = self._page.url
        page_title = await self._page.title()

        if not _looks_like_login_page(current_url, page_title):
            # Already authenticated (restored from saved state)
            self._authenticated = True
            logger.info("Browser session restored from saved state", extra={"url": current_url})
            return

        # --- Attempt automated form login ---
        if not (self.settings.moodle_username and self.settings.moodle_password):
            raise MoodleSessionExpiredError(
                "Browser session expired. Set MOODLE_USERNAME and MOODLE_PASSWORD "
                "in .env to enable automated login, or log in manually."
            )

        logger.info("Redirected to login page — attempting automated form login")
        await self._perform_login(timeout_ms)

    async def _perform_login(self, timeout_ms: int) -> None:
        """Fill and submit the standard Moodle login form."""
        page = self._page
        login_url = f"{self.base_url}/login/index.php"

        # Navigate directly to the login page to avoid SSO redirect loops
        await page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)

        # Wait for username field
        try:
            await page.wait_for_selector("input#username", timeout=10000)
        except Exception:
            raise MoodleAuthenticationError(
                "Login form not found — the site may require SSO, MFA, or CAPTCHA. "
                "Complete login manually and save session state."
            )

        # Fill credentials — values never logged
        await page.fill("input#username", self.settings.moodle_username)
        await page.fill("input#password", self.settings.moodle_password)

        # Click the login button (Moodle 3.x and 4.x selectors)
        login_btn = await page.query_selector(
            "#loginbtn, button#loginbtn, input#loginbtn, button[type='submit']"
        )
        if login_btn:
            await login_btn.click()
        else:
            await page.keyboard.press("Enter")

        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        # Verify we escaped the login page
        post_url = page.url
        post_title = await page.title()
        if _looks_like_login_page(post_url, post_title):
            # Check for visible error message
            error_el = await page.query_selector(".loginerrors, .alert-danger, #loginerrormessage")
            err_msg = (await error_el.text_content() or "").strip() if error_el else "unknown error"
            raise MoodleAuthenticationError(
                f"Moodle login failed: {err_msg}. "
                "This may be due to invalid credentials, MFA, CAPTCHA, or SSO redirect."
            )

        self._authenticated = True
        await self.save_session_state()
        logger.info("Automated login succeeded; session state saved")

    async def save_session_state(self) -> None:
        """Persist authenticated cookies and local storage securely."""
        if self._context:
            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self.storage_state_path))
            logger.info("Saved browser session state", extra={"path": str(self.storage_state_path)})

    # ------------------------------------------------------------------
    # Session check helper — called before every navigation
    # ------------------------------------------------------------------

    async def _navigate_and_check(self, url: str) -> None:
        """Navigate to a URL and detect session expiry mid-session."""
        await self._ensure_browser()
        timeout_ms = self.settings.request_timeout_seconds * 1000
        await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        current_url = self._page.url
        page_title = await self._page.title()
        if _looks_like_login_page(current_url, page_title):
            # Session expired during a scan — try to re-login once
            self._authenticated = False
            logger.warning("Session expired during navigation — attempting re-login")
            await self._ensure_authenticated()
            # Retry the original URL
            await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    # ------------------------------------------------------------------
    # MoodleClient interface
    # ------------------------------------------------------------------

    async def check_connection(self) -> MoodleSiteInfo:
        """Validate browser session and extract basic site / user information."""
        await self._ensure_browser()

        # Try to get the user's full name from the nav bar
        fullname = "Student User"
        try:
            # Moodle 4.x: .usermenu .usertext; Moodle 3.x: .usertext, span.usertext
            user_el = await self._page.query_selector(
                ".usermenu .usertext, span.usertext, .user-name, [data-key='myprofile'] .menu-action-text"
            )
            if user_el:
                fullname = (await user_el.text_content() or "Student User").strip()
        except Exception:
            pass

        # Try to get the site name from the page title or logo alt text
        sitename = "Moodle"
        try:
            title = await self._page.title()
            if ": " in title:
                sitename = title.split(": ")[-1].strip()
            elif title:
                sitename = title.strip()
        except Exception:
            pass

        parts = fullname.split(maxsplit=1)
        return MoodleSiteInfo(
            sitename=sitename,
            username=self.settings.moodle_username or "student",
            firstname=parts[0] if parts else "Student",
            lastname=parts[1] if len(parts) > 1 else "",
            fullname=fullname,
            userid=0,
            siteurl=self.base_url,
        )

    async def get_courses(self) -> List[MoodleCourse]:
        """Discover enrolled courses from the Moodle course overview page."""
        await self._navigate_and_check(f"{self.base_url}/my/courses.php")

        courses: List[MoodleCourse] = []
        seen_ids: set = set()

        # Moodle 4.x uses data-region="course-content"; Moodle 3.x uses a simpler list
        # We scrape all links to /course/view.php?id= as the universal fallback
        course_links = await self._page.query_selector_all("a[href*='/course/view.php?id=']")

        for link in course_links:
            href = await link.get_attribute("href") or ""
            course_id = _extract_id_from_href(href)
            if course_id is None or course_id in seen_ids:
                continue
            text = (await link.text_content() or "").strip()
            if not text:
                continue
            seen_ids.add(course_id)
            courses.append(
                MoodleCourse(
                    id=course_id,
                    shortname=text,
                    fullname=text,
                    enrolled=True,
                )
            )
            logger.debug("Discovered course", extra={"id": course_id, "name": text})

        # Fallback: try the dashboard if courses.php returned nothing
        if not courses:
            await self._navigate_and_check(f"{self.base_url}/my/")
            course_links = await self._page.query_selector_all("a[href*='/course/view.php?id=']")
            for link in course_links:
                href = await link.get_attribute("href") or ""
                course_id = _extract_id_from_href(href)
                if course_id is None or course_id in seen_ids:
                    continue
                text = (await link.text_content() or "").strip()
                if not text:
                    continue
                seen_ids.add(course_id)
                courses.append(
                    MoodleCourse(id=course_id, shortname=text, fullname=text, enrolled=True)
                )

        logger.info("Discovered enrolled courses", extra={"count": len(courses)})
        return courses

    async def get_assignments(self, course_ids: Optional[List[int]] = None) -> List[MoodleAssignment]:
        """Discover all assignments across the specified courses (or all enrolled courses)."""
        if not course_ids:
            courses = await self.get_courses()
            course_ids = [c.id for c in courses]

        assignments: List[MoodleAssignment] = []

        for cid in course_ids:
            try:
                course_assigns = await self._get_course_assignments(cid)
                assignments.extend(course_assigns)
            except Exception as e:
                logger.warning("Failed to fetch assignments for course", extra={"course_id": cid, "error": str(e)})

        logger.info("Discovered assignments", extra={"total": len(assignments)})
        return assignments

    async def _get_course_assignments(self, course_id: int) -> List[MoodleAssignment]:
        """Navigate to a course page and collect all assignment links."""
        await self._navigate_and_check(f"{self.base_url}/course/view.php?id={course_id}")

        # Find links matching mod/assign/view.php?id=
        assign_links = await self._page.query_selector_all("a[href*='/mod/assign/view.php?id=']")

        assignments: List[MoodleAssignment] = []
        seen_ids: set = set()

        for alink in assign_links:
            href = await alink.get_attribute("href") or ""
            assign_id = _extract_id_from_href(href)
            if assign_id is None or assign_id in seen_ids:
                continue
            name = (await alink.text_content() or "").strip()
            if not name:
                continue
            seen_ids.add(assign_id)

            # Get due date if shown inline on the course page
            due_date: Optional[datetime] = None
            try:
                parent = await alink.evaluate_handle("el => el.closest('li, div.activity, div.activityinstance')")
                if parent:
                    parent_text = (await parent.as_element().text_content() or "") if parent.as_element() else ""
                    due_match = re.search(r"Due[:\s]+(.+?)(?:\n|$)", parent_text, re.IGNORECASE)
                    if due_match:
                        due_date = _parse_moodle_timestamp(due_match.group(1))
            except Exception:
                pass

            assignments.append(
                MoodleAssignment(
                    id=assign_id,
                    course_id=course_id,
                    name=name,
                    intro_text=f"Assignment: {name}",
                    due_date=due_date,
                )
            )
            logger.debug("Found assignment", extra={"id": assign_id, "name": name, "course_id": course_id})

        return assignments

    async def get_assignment_details(self, assignment_id: int) -> MoodleAssignment:
        """Navigate to the assignment view page and extract full details."""
        url = f"{self.base_url}/mod/assign/view.php?id={assignment_id}"
        await self._navigate_and_check(url)
        page = self._page

        # --- Title ---
        title = f"Assignment {assignment_id}"
        for sel in [".page-header-headings h1", "h1.h2", "h2", ".page-header h1"]:
            el = await page.query_selector(sel)
            if el:
                t = (await el.text_content() or "").strip()
                if t:
                    title = t
                    break

        # --- Introduction / instructions ---
        intro_html: Optional[str] = None
        intro_text: Optional[str] = None
        for sel in ["#intro", ".activity-description", "div.intro", ".box.generalbox.intro"]:
            el = await page.query_selector(sel)
            if el:
                intro_html = await el.inner_html()
                intro_text = (await el.text_content() or "").strip()
                break

        # --- Due date ---
        due_date: Optional[datetime] = None
        for sel in [
            ".submissionstatustable tr",
            ".generaltable tr",
            "table.generaltable tr",
        ]:
            rows = await page.query_selector_all(sel)
            for row in rows:
                row_text = (await row.text_content() or "").lower()
                if "due date" in row_text or "due:" in row_text:
                    cells = await row.query_selector_all("td")
                    if len(cells) >= 2:
                        raw = (await cells[1].text_content() or "").strip()
                        due_date = _parse_moodle_timestamp(raw)
                    break
            if due_date:
                break

        # --- Course ID from breadcrumb or page URL ---
        course_id = 0
        try:
            breadcrumbs = await page.query_selector_all(".breadcrumb a[href*='/course/view.php']")
            for bc in breadcrumbs:
                href = await bc.get_attribute("href") or ""
                cid = _extract_id_from_href(href)
                if cid:
                    course_id = cid
                    break
        except Exception:
            pass

        return MoodleAssignment(
            id=assignment_id,
            course_id=course_id,
            name=title,
            intro_html=intro_html,
            intro_text=intro_text,
            due_date=due_date,
        )

    async def get_submission_status(self, assignment_id: int) -> MoodleSubmissionStatus:
        """Scrape the assignment page to determine the current submission state."""
        url = f"{self.base_url}/mod/assign/view.php?id={assignment_id}"
        await self._navigate_and_check(url)
        page = self._page

        body_text = (await page.text_content("body") or "").lower()

        # Submission state
        state = SubmissionState.NEW
        if "submitted for grading" in body_text:
            state = SubmissionState.SUBMITTED
        elif "draft (not submitted)" in body_text or "draft saved" in body_text:
            state = SubmissionState.DRAFT

        # Grading state
        grading_state = GradingState.NOT_GRADED
        if "graded" in body_text and "not graded" not in body_text:
            grading_state = GradingState.GRADED

        can_submit = (
            "add submission" in body_text
            or "edit submission" in body_text
            or "submit assignment" in body_text
        )
        locked = "locked" in body_text and "reopened" not in body_text

        return MoodleSubmissionStatus(
            assignment_id=assignment_id,
            status=state,
            grading_status=grading_state,
            can_submit=can_submit,
            can_edit=can_submit,
            locked=locked,
            is_graded=(grading_state == GradingState.GRADED),
        )

    async def upload_submission_file(self, assignment_id: int, file_path: Path) -> MoodleUploadResult:
        """Upload a file to an assignment's submission draft area via the browser."""
        if not file_path.exists():
            raise FileNotFoundError(f"Submission file not found: {file_path}")

        url = f"{self.base_url}/mod/assign/view.php?id={assignment_id}"
        await self._navigate_and_check(url)
        page = self._page
        timeout_ms = self.settings.request_timeout_seconds * 1000

        # Click the "Add submission" or "Edit submission" button
        add_btn = await page.query_selector(
            "button:has-text('Add submission'), "
            "a:has-text('Add submission'), "
            "button:has-text('Edit submission'), "
            "a:has-text('Edit submission')"
        )
        if not add_btn:
            raise MoodleError(
                "Could not find 'Add submission' or 'Edit submission' button on the assignment page. "
                "The submission window may be closed or the assignment type may not support file uploads."
            )
        await add_btn.click()
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        # Wait for file input to appear (Moodle uses a Filepicker; there may be a hidden input)
        file_input = await page.query_selector("input[type='file']")
        if not file_input:
            raise MoodleError(
                "File upload input element not found on the submission form. "
                "The assignment may not support file submissions."
            )

        await file_input.set_input_files(str(file_path))
        await page.wait_for_timeout(1000)  # Allow the Filepicker to register the file

        # Save changes
        save_btn = await page.query_selector(
            "#id_submitbutton, input#id_submitbutton, button#id_submitbutton, "
            "input[value='Save changes'], button:has-text('Save changes')"
        )
        if not save_btn:
            raise MoodleError("Could not find 'Save changes' button on the submission form.")

        await save_btn.click()
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        logger.info(
            "File uploaded to submission draft",
            extra={"assignment_id": assignment_id, "file": file_path.name},
        )
        return MoodleUploadResult(
            assignment_id=assignment_id,
            item_id=1,
            filename=file_path.name,
            file_size_bytes=file_path.stat().st_size,
            success=True,
            draft_saved=True,
        )

    async def finalize_submission(self, assignment_id: int) -> MoodleFinalizeResult:
        """Click 'Submit assignment' to finalise an uploaded draft (if AUTO_FINAL_SUBMIT is True)."""
        url = f"{self.base_url}/mod/assign/view.php?id={assignment_id}"
        await self._navigate_and_check(url)
        page = self._page
        timeout_ms = self.settings.request_timeout_seconds * 1000

        submit_btn = await page.query_selector(
            "button:has-text('Submit assignment'), a:has-text('Submit assignment')"
        )
        if not submit_btn:
            # Already in submitted state or no finalize button available
            status = await self.get_submission_status(assignment_id)
            return MoodleFinalizeResult(
                assignment_id=assignment_id,
                success=(status.status == SubmissionState.SUBMITTED),
                final_status=status.status,
            )

        await submit_btn.click()
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        # Handle confirmation modal / page
        confirm_btn = await page.query_selector(
            "#id_submitbutton, input[value='Continue'], button:has-text('Continue'), "
            "button:has-text('Yes'), input[value='Yes']"
        )
        if confirm_btn:
            await confirm_btn.click()
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        status = await self.get_submission_status(assignment_id)
        success = status.status == SubmissionState.SUBMITTED
        logger.info(
            "Submission finalized",
            extra={"assignment_id": assignment_id, "success": success, "status": status.status.value},
        )
        return MoodleFinalizeResult(
            assignment_id=assignment_id,
            success=success,
            final_status=status.status,
        )

    async def verify_submission(self, assignment_id: int) -> MoodleSubmissionStatus:
        """Authoritatively re-check submission status from Moodle."""
        return await self.get_submission_status(assignment_id)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close browser resources cleanly, saving session state first."""
        try:
            if self._context and self._authenticated:
                await self.save_session_state()
        except Exception as e:
            logger.warning(f"Failed to save session before close: {e}")
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing Playwright browser: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._authenticated = False
