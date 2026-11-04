"""Image validation, metadata extraction, and checksum computation."""

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from app.logging_config import get_logger

logger = get_logger(__name__)


def compute_file_sha256(path: Path) -> str:
    """Calculate SHA-256 digest of file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def validate_image_file(
    image_path: Path,
    min_width: int = 200,
    min_height: int = 100,
    max_width: int = 5000,
    max_height: int = 10000,
) -> tuple[bool, Optional[str]]:
    """Verify that an image artifact exists, is not corrupt, and meets dimensional constraints."""
    if not image_path.exists():
        return False, f"Image file not found: {image_path}"

    if image_path.stat().st_size == 0:
        return False, "Image file is empty (0 bytes)."

    try:
        with Image.open(image_path) as img:
            img.verify()

        # Reopen to read dimensions after verify()
        with Image.open(image_path) as img:
            width, height = img.size

        if width < min_width or height < min_height:
            return False, f"Image dimensions too small: {width}x{height} (min: {min_width}x{min_height})"

        if width > max_width or height > max_height:
            return False, f"Image dimensions exceed maximum: {width}x{height}"

        return True, None

    except Exception as e:
        logger.error(f"Image validation exception for {image_path}: {e}")
        return False, f"Corrupted or invalid image: {e}"


def get_image_metadata(image_path: Path) -> Dict[str, Any]:
    """Extract format, dimensions, size, and checksum."""
    with Image.open(image_path) as img:
        width, height = img.size
        img_format = img.format

    return {
        "width": width,
        "height": height,
        "format": img_format,
        "size_bytes": image_path.stat().st_size,
        "sha256": compute_file_sha256(image_path),
    }

