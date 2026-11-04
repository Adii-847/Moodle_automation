"""Unit tests for PDF generation layout, styling, and validation."""

from pathlib import Path
from PIL import Image
import pytest

from app.documents.pdf_generator import (
    PdfGenerationInput,
    generate_assignment_pdf,
    sanitize_filename,
)
from app.documents.pdf_validation import get_pdf_metadata, validate_pdf_file


def test_sanitize_filename():
    raw = "Lab 1: Recursion & Trees / <Version 1>?"
    clean = sanitize_filename(raw)
    assert "/" not in clean
    assert ":" not in clean
    assert "<" not in clean
    assert ">" not in clean
    assert "Lab_1_Recursion_Trees_Version_1" in clean


def test_pdf_generation_and_validation(tmp_path):
    # Create test dummy screenshots
    code_img = tmp_path / "code.png"
    out_img = tmp_path / "output.png"

    img = Image.new("RGB", (800, 300), color=(30, 30, 30))
    img.save(code_img, format="PNG")
    img.save(out_img, format="PNG")

    pdf_out = tmp_path / "submission.pdf"

    data = PdfGenerationInput(
        assignment_id=101,
        assignment_title="Lab 1: Binary Search Trees",
        course_name="CS201: Data Structures",
        student_name="Aditya Agarwal",
        student_uid="UID-98765",
        institution_name="College of Engineering",
        objective_text="Implement binary search tree insertion and verify in-order traversal.",
        code_images=[code_img],
        output_images=[out_img],
        additional_notes="All test cases verified successfully.",
        output_pdf_path=pdf_out,
    )

    result_path = generate_assignment_pdf(data)
    assert result_path.exists()
    assert result_path.stat().st_size > 0

    # Validate PDF
    valid, err = validate_pdf_file(
        pdf_path=result_path,
        expected_student_name="Aditya Agarwal",
        expected_student_uid="UID-98765",
        expected_title="Lab 1: Binary Search Trees",
        max_size_mb=25,
    )
    assert valid is True
    assert err is None

    meta = get_pdf_metadata(result_path)
    assert meta["file_size_bytes"] > 0
    assert len(meta["sha256_checksum"]) == 64


def test_pdf_validation_invalid_files(tmp_path):
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"NOT A REAL PDF FILE")

    valid, err = validate_pdf_file(corrupt_pdf, "Name", "UID", "Title")
    assert valid is False
    assert "missing %PDF-" in err

    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")

    valid, err = validate_pdf_file(empty_pdf, "Name", "UID", "Title")
    assert valid is False
    assert "empty" in err
