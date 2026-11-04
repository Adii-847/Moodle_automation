"""Moodle REST Web Services API client implementation."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.config import AppSettings
from app.logging_config import get_logger
from app.moodle.client import (
    MoodleAuthenticationError,
    MoodleClient,
    MoodleError,
    MoodleNotFoundError,
    MoodlePermissionError,
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


def strip_html_tags(html_content: Optional[str]) -> str:
    """Safely strip HTML markup to plain text while retaining line breaks."""
    if not html_content:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Decode basic HTML entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class MoodleApiClient(MoodleClient):
    """Client implementing the official Moodle Web Services REST protocol."""

    def __init__(self, settings: AppSettings, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings
        self.base_url = settings.moodle_base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/webservice/rest/server.php"
        self.upload_endpoint = f"{self.base_url}/webservice/upload.php"
        self.token = settings.moodle_api_token
        self._http = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        self._cached_site_info: Optional[MoodleSiteInfo] = None

    async def _post(self, function_name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a Moodle REST API function with error inspection."""
        if not self.token:
            raise MoodleAuthenticationError("Moodle API token is missing in configuration.")

        data: Dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": function_name,
            "moodlewsrestformat": "json",
        }
        if params:
            data.update(params)

        try:
            response = await self._http.post(self.endpoint, data=data)
            response.raise_for_status()
            res_json = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise MoodleAuthenticationError(f"HTTP {e.response.status_code} during {function_name}")
            raise MoodleError(f"HTTP request failed during {function_name}: {e}")
        except Exception as e:
            raise MoodleError(f"Network error communicating with Moodle: {e}")

        # Check for Moodle API exceptions returned in JSON
        if isinstance(res_json, dict) and "exception" in res_json:
            error_code = res_json.get("errorcode", "")
            msg = res_json.get("message", "Unknown Moodle error")
            if error_code in ("invalidtoken", "accessexception", "usernotfullysetup"):
                raise MoodleAuthenticationError(f"Moodle auth error: {error_code}")
            elif error_code in ("nopermissions", "servicenotavailable"):
                raise MoodlePermissionError(f"Moodle permission error: {error_code} - {msg}")
            elif error_code in ("courseerror", "invalidrecord"):
                raise MoodleNotFoundError(f"Moodle resource not found: {msg}")
            raise MoodleError(f"Moodle error ({error_code}): {msg}", error_code=error_code)

        return res_json

    async def check_connection(self) -> MoodleSiteInfo:
        res = await self._post("core_webservice_get_site_info")
        site_info = MoodleSiteInfo(
            sitename=res.get("sitename", "Moodle"),
            username=res.get("username", ""),
            firstname=res.get("firstname", ""),
            lastname=res.get("lastname", ""),
            fullname=res.get("fullname", ""),
            userid=res.get("userid", 0),
            siteurl=res.get("siteurl", self.base_url),
            version=res.get("version"),
            release=res.get("release"),
        )
        self._cached_site_info = site_info
        return site_info

    async def get_courses(self) -> List[MoodleCourse]:
        if not self._cached_site_info:
            await self.check_connection()
        userid = self._cached_site_info.userid

        res = await self._post("core_enrol_get_users_courses", {"userid": userid})
        if not isinstance(res, list):
            raise MoodleError("Unexpected response format from core_enrol_get_users_courses")

        courses: List[MoodleCourse] = []
        for item in res:
            courses.append(
                MoodleCourse(
                    id=item["id"],
                    shortname=item.get("shortname", f"Course {item['id']}"),
                    fullname=item.get("fullname", ""),
                    category=str(item.get("category", "")),
                    enrolled=True,
                )
            )
        return courses

    async def get_assignments(self, course_ids: Optional[List[int]] = None) -> List[MoodleAssignment]:
        if not course_ids:
            courses = await self.get_courses()
            course_ids = [c.id for c in courses]

        if not course_ids:
            return []

        params: Dict[str, Any] = {}
        for idx, cid in enumerate(course_ids):
            params[f"courseids[{idx}]"] = cid

        res = await self._post("mod_assign_get_assignments", params)
        assignment_list: List[MoodleAssignment] = []

        courses_data = res.get("courses", [])
        for c in courses_data:
            c_id = c["id"]
            for a in c.get("assignments", []):
                intro_html = a.get("intro", "")
                intro_text = strip_html_tags(intro_html)
                due_epoch = a.get("duedate")
                allow_epoch = a.get("allowsubmissionsfromdate")
                cutoff_epoch = a.get("cutoffdate")
                grading_epoch = a.get("gradingduedate")

                configs = {cfg["name"]: cfg["value"] for cfg in a.get("configs", []) if "name" in cfg and "value" in cfg}
                max_files = int(configs.get("maxfilesubmissions", 1))
                max_bytes = int(configs.get("maxsubmissionsizebytes", 26214400))
                file_types = configs.get("filetypeslist", None)

                attachments: List[MoodleFile] = []
                for att in a.get("introattachments", []):
                    attachments.append(
                        MoodleFile(
                            filename=att.get("filename", "attachment"),
                            filepath=att.get("filepath", "/"),
                            filesize=att.get("filesize", 0),
                            fileurl=att.get("fileurl"),
                        )
                    )

                assignment_list.append(
                    MoodleAssignment(
                        id=a["id"],
                        course_id=c_id,
                        name=a.get("name", f"Assignment {a['id']}"),
                        intro_html=intro_html,
                        intro_text=intro_text,
                        duedate=datetime.fromtimestamp(due_epoch, tz=timezone.utc) if due_epoch else None,
                        allowsubmissionsfromdate=datetime.fromtimestamp(allow_epoch, tz=timezone.utc) if allow_epoch else None,
                        cutoffdate=datetime.fromtimestamp(cutoff_epoch, tz=timezone.utc) if cutoff_epoch else None,
                        gradingduedate=datetime.fromtimestamp(grading_epoch, tz=timezone.utc) if grading_epoch else None,
                        maxfiles=max_files,
                        maxbytes=max_bytes,
                        filetypeslist=file_types,
                        requiresubmissionstatement=bool(a.get("requiresubmissionstatement", 0)),
                        submissiondrafts=bool(a.get("submissiondrafts", 1)),
                        attachments=attachments,
                    )
                )

        return assignment_list

    async def get_assignment_details(self, assignment_id: int) -> MoodleAssignment:
        assignments = await self.get_assignments()
        for a in assignments:
            if a.id == assignment_id:
                return a
        raise MoodleNotFoundError(f"Assignment id {assignment_id} not found in user courses.")

    async def get_submission_status(self, assignment_id: int) -> MoodleSubmissionStatus:
        res = await self._post("mod_assign_get_submission_status", {"assignid": assignment_id})

        last_attempt = res.get("lastattempt", {})
        sub = last_attempt.get("submission", {})
        status_str = sub.get("status", "new").lower()

        # Map to SubmissionState
        state = SubmissionState.NEW
        if status_str == "submitted":
            state = SubmissionState.SUBMITTED
        elif status_str == "draft":
            state = SubmissionState.DRAFT
        elif status_str == "reopened":
            state = SubmissionState.REOPENED

        grading_summary = last_attempt.get("gradingstatus", "notgraded")
        grading_state = GradingState.GRADED if grading_summary == "graded" else GradingState.NOT_GRADED

        can_submit = bool(last_attempt.get("cansubmit", True))
        can_edit = bool(last_attempt.get("canedit", True))
        locked = bool(last_attempt.get("locked", False))
        is_graded = grading_state == GradingState.GRADED

        files: List[MoodleFile] = []
        for plugin in sub.get("plugins", []):
            if plugin.get("type") == "file":
                for area in plugin.get("fileareas", []):
                    for f in area.get("files", []):
                        time_mod = datetime.fromtimestamp(f["timemodified"], tz=timezone.utc) if f.get("timemodified") else None
                        files.append(
                            MoodleFile(
                                filename=f.get("filename", ""),
                                filepath=f.get("filepath", "/"),
                                filesize=f.get("filesize", 0),
                                fileurl=f.get("fileurl"),
                                timemodified=time_mod,
                            )
                        )

        time_modified = datetime.fromtimestamp(sub["timemodified"], tz=timezone.utc) if sub.get("timemodified") else None

        return MoodleSubmissionStatus(
            assignment_id=assignment_id,
            status=state,
            grading_status=grading_state,
            can_submit=can_submit,
            can_edit=can_edit,
            locked=locked,
            is_graded=is_graded,
            submitted_files=files,
            time_modified=time_modified,
            raw_response=res,
        )

    async def upload_submission_file(self, assignment_id: int, file_path: Path) -> MoodleUploadResult:
        if not file_path.exists():
            raise FileNotFoundError(f"Submission file does not exist: {file_path}")

        file_size = file_path.stat().st_size
        filename = file_path.name

        # Upload file to Moodle draft area via upload.php
        params = {"token": self.token, "filepath": "/", "itemid": 0}
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/pdf")}
            try:
                res = await self._http.post(self.upload_endpoint, params=params, files=files)
                res.raise_for_status()
                res_data = res.json()
            except Exception as e:
                raise MoodleError(f"Failed to upload file to draft area: {e}")

        if not isinstance(res_data, list) or len(res_data) == 0:
            raise MoodleError("Invalid response from Moodle file upload endpoint.")

        item_id = res_data[0].get("itemid", 0)

        # Save draft submission with mod_assign_save_submission
        save_params = {
            "assignmentid": assignment_id,
            "plugindata[files_filemanager]": item_id,
        }
        await self._post("mod_assign_save_submission", save_params)

        return MoodleUploadResult(
            assignment_id=assignment_id,
            item_id=item_id,
            filename=filename,
            file_size_bytes=file_size,
            success=True,
            draft_saved=True,
        )

    async def finalize_submission(self, assignment_id: int) -> MoodleFinalizeResult:
        """Call mod_assign_submit_for_grading to finalize submission."""
        params = {
            "assignmentid": assignment_id,
            "acceptsubmissionstatement": 1,
        }
        try:
            await self._post("mod_assign_submit_for_grading", params)
            # Verify status
            status = await self.get_submission_status(assignment_id)
            return MoodleFinalizeResult(
                assignment_id=assignment_id,
                success=(status.status == SubmissionState.SUBMITTED),
                final_status=status.status,
            )
        except Exception as e:
            return MoodleFinalizeResult(
                assignment_id=assignment_id,
                success=False,
                final_status=SubmissionState.DRAFT,
                error_message=str(e),
            )

    async def verify_submission(self, assignment_id: int) -> MoodleSubmissionStatus:
        return await self.get_submission_status(assignment_id)

    async def close(self) -> None:
        await self._http.aclose()

