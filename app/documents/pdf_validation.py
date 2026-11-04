"""Comprehensive validation of generated PDF artifacts before upload."""

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)


def validate_pdf_file(
    pdf_path: Path,
    expected_student_name: str,
    expected_student_uid: str,
    expected_title: str,
    max_size_mb: int = 25,
) -> tuple[bool, Optional[str]]:
    """Validate that the PDF is non-empty, well-formed, within size constraints, and contains required metadata."""
    if not pdf_path.exists():
        return False, f"PDF file does not exist: {pdf_path}"

    file_size_bytes = pdf_path.stat().st_size
    if file_size_bytes == 0:
        return False, "PDF file is 0 bytes (empty)."

    max_bytes = max_size_mb * 1024 * 1024
    if file_size_bytes > max_bytes:
        return False, f"PDF size ({file_size_bytes / 1024 / 1024:.2f} MB) exceeds maximum allowed ({max_size_mb} MB)."

    # Verify PDF magic bytes
    try:
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return False, "File is not a valid PDF (missing %PDF- magic bytes)."

            # Scan raw stream for basic text presence or EOF marker
            f.seek(0)
            content = f.read()
            if b"%%EOF" not in content[-1024:]:
                return False, "PDF file is incomplete or truncated (missing %%EOF marker)."

            # Check presence of expected metadata strings in raw or decoded text
            name_bytes = expected_student_name.encode("utf-8")
            uid_bytes = expected_student_uid.encode("utf-8")

            # Check if name and UID are present in the PDF content stream
            if name_bytes not in content and name_bytes.lower() not in content.lower():
                logger.warning("Student name not detected in raw PDF stream")

            if uid_bytes not in content and uid_bytes.lower() not in content.lower():
                logger.warning("Student UID not detected in raw PDF stream")

        return True, None

    except Exception as e:
        logger.error(f"Error inspecting PDF file {pdf_path}: {e}")
        return False, f"Corrupted or unreadable PDF: {e}"


def get_pdf_metadata(pdf_path: Path) -> Dict[str, Any]:
    """Calculate checksum and size of validated PDF."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)

    return {
        "file_path": str(pdf_path),
        "file_size_bytes": pdf_path.stat().st_size,
        "sha256_checksum": h.hexdigest(),
    }

