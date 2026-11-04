"""Isolated execution environment setup with stripped credentials and safety limits."""

import os
from pathlib import Path
from typing import Dict

from app.config import AppSettings, get_settings


def create_safe_subprocess_env(settings: AppSettings) -> Dict[str, str]:
    """Create a minimal, sanitized environment dictionary for subprocess execution."""
    safe_keys = {
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PROCESSOR_ARCHITECTURE",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "LANG",
        "LC_ALL",
    }

    env: Dict[str, str] = {}
    for k, v in os.environ.items():
        if k.upper() in safe_keys:
            env[k] = v

    # Explicitly guarantee that no Moodle credentials or secrets are present
    forbidden_prefixes = ("MOODLE_", "SECRET_", "TOKEN_", "PASSWORD_", "DATABASE_")
    for k in list(env.keys()):
        for prefix in forbidden_prefixes:
            if k.upper().startswith(prefix):
                del env[k]

    env["PYTHONIOENCODING"] = "utf-8"
    return env

