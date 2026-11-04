"""Unit tests for Moodle API client with httpx MockTransport."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import AppSettings
from app.moodle.api_client import MoodleApiClient, strip_html_tags
from app.moodle.client import MoodleAuthenticationError
from app.moodle.schemas import SubmissionState


def test_strip_html_tags():
    html = "<p>Please solve <b>Exercise 1</b>.<br/>Submit code and output.</p>"
    plain = strip_html_tags(html)
    assert "Please solve Exercise 1." in plain
    assert "Submit code and output." in plain
    assert "<p>" not in plain


@pytest.mark.asyncio
async def test_api_check_connection_success():
    settings = AppSettings(
        MOODLE_BASE_URL="http://moodle.test",
        MOODLE_API_TOKEN="test_token_123",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        data = parse_qs(request.content.decode("utf-8"))
        func = data.get("wsfunction", [""])[0]
        if func == "core_webservice_get_site_info":
            return httpx.Response(
                200,
                json={
                    "sitename": "Test College Moodle",
                    "username": "student1",
                    "firstname": "Aditya",
                    "lastname": "Agarwal",
                    "fullname": "Aditya Agarwal",
                    "userid": 42,
                    "siteurl": "http://moodle.test",
                    "version": "4.1.2",
                    "release": "4.1.2 (Build: 20230313)",
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = MoodleApiClient(settings, client=mock_http)
        site_info = await client.check_connection()

    assert site_info.username == "student1"
    assert site_info.userid == 42
    assert site_info.sitename == "Test College Moodle"


@pytest.mark.asyncio
async def test_api_invalid_token_error():
    settings = AppSettings(
        MOODLE_BASE_URL="http://moodle.test",
        MOODLE_API_TOKEN="invalid_token",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "exception": "moodle_exception",
                "errorcode": "invalidtoken",
                "message": "Invalid token - token not found",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = MoodleApiClient(settings, client=mock_http)
        with pytest.raises(MoodleAuthenticationError):
            await client.check_connection()


@pytest.mark.asyncio
async def test_api_get_assignments():
    settings = AppSettings(
        MOODLE_BASE_URL="http://moodle.test",
        MOODLE_API_TOKEN="valid_token",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        data = parse_qs(request.content.decode("utf-8"))
        func = data.get("wsfunction", [""])[0]
        if func == "core_webservice_get_site_info":
            return httpx.Response(200, json={"userid": 42, "sitename": "Moodle", "username": "s1", "fullname": "S"})
        elif func == "core_enrol_get_users_courses":
            return httpx.Response(200, json=[{"id": 10, "shortname": "CS101", "fullname": "CS 101"}])
        elif func == "mod_assign_get_assignments":
            return httpx.Response(
                200,
                json={
                    "courses": [
                        {
                            "id": 10,
                            "assignments": [
                                {
                                    "id": 101,
                                    "name": "Programming Lab 1",
                                    "intro": "<p>Write a program in Python to calculate factorial.</p>",
                                    "duedate": 1735689600,
                                    "configs": [{"name": "maxfilesubmissions", "value": "1"}],
                                    "introattachments": [],
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = MoodleApiClient(settings, client=mock_http)
        assignments = await client.get_assignments([10])

    assert len(assignments) == 1
    a = assignments[0]
    assert a.id == 101
    assert a.name == "Programming Lab 1"
    assert "factorial" in a.intro_text
    assert a.duedate is not None


@pytest.mark.asyncio
async def test_api_submission_status():
    settings = AppSettings(
        MOODLE_BASE_URL="http://moodle.test",
        MOODLE_API_TOKEN="valid_token",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "lastattempt": {
                    "submission": {
                        "id": 55,
                        "status": "submitted",
                        "timemodified": 1735600000,
                        "plugins": [
                            {
                                "type": "file",
                                "name": "File submissions",
                                "fileareas": [
                                    {
                                        "area": "submission_files",
                                        "files": [
                                            {
                                                "filename": "Lab1_Solution.pdf",
                                                "filepath": "/",
                                                "filesize": 1048576,
                                                "fileurl": "http://moodle.test/files/1.pdf",
                                                "timemodified": 1735600000,
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    "gradingstatus": "notgraded",
                    "cansubmit": False,
                    "canedit": False,
                    "locked": True,
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mock_http:
        client = MoodleApiClient(settings, client=mock_http)
        status = await client.get_submission_status(101)

    assert status.status == SubmissionState.SUBMITTED
    assert status.can_submit is False
    assert status.locked is True
    assert len(status.submitted_files) == 1
    assert status.submitted_files[0].filename == "Lab1_Solution.pdf"
