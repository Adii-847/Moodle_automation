"""A4 PDF document generation using ReportLab with cover page, code, and execution captures."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.documents.layouts import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    USABLE_HEIGHT,
    USABLE_WIDTH,
    NumberedCanvas,
    get_document_styles,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent directory traversal and remove unsupported characters."""
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)
    clean = re.sub(r"_+", "_", clean).strip("._")
    return clean[:100] or "submission"


@dataclass
class PdfGenerationInput:
    assignment_id: int
    assignment_title: str
    course_name: str
    student_name: str
    student_uid: str
    institution_name: str
    objective_text: str
    code_images: List[Path] = field(default_factory=list)
    output_images: List[Path] = field(default_factory=list)
    additional_notes: Optional[str] = None
    output_pdf_path: Optional[Path] = None


def create_scaled_image_flowable(image_path: Path, max_width: float = USABLE_WIDTH, max_height: float = 450) -> Image:
    """Read image dimensions and return a properly scaled ReportLab Image flowable."""
    with PILImage.open(image_path) as img:
        orig_w, orig_h = img.size

    # Calculate scale factor to preserve aspect ratio
    scale_w = max_width / float(orig_w)
    scale_h = max_height / float(orig_h)
    scale = min(scale_w, scale_h, 1.0)  # do not upscale

    final_w = orig_w * scale
    final_h = orig_h * scale

    return Image(str(image_path), width=final_w, height=final_h)


def generate_assignment_pdf(data: PdfGenerationInput) -> Path:
    """Assemble formatted academic PDF with cover details, problem statement, and screenshots."""
    if not data.output_pdf_path:
        raise ValueError("output_pdf_path must be specified.")

    data.output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(data.output_pdf_path),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
    )

    styles = get_document_styles()
    story = []

    # ================= PAGE 1: COVER / TITLE PAGE =================
    story.append(Spacer(1, 40))
    story.append(Paragraph(data.institution_name, styles["DocInstitution"]))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="80%", thickness=2, color=colors.HexColor("#2B6CB0"), spaceAfter=30))

    story.append(Spacer(1, 20))
    story.append(Paragraph("ASSIGNMENT SUBMISSION", styles["DocTitle"]))
    story.append(Paragraph(f"<b>{data.assignment_title}</b>", styles["DocInstitution"]))
    story.append(Spacer(1, 40))

    # Student metadata table
    meta_data = [
        [Paragraph("<b>Student Name:</b>", styles["BodyContent"]), Paragraph(data.student_name, styles["BodyContent"])],
        [Paragraph("<b>Student UID:</b>", styles["BodyContent"]), Paragraph(data.student_uid, styles["BodyContent"])],
        [Paragraph("<b>Course:</b>", styles["BodyContent"]), Paragraph(data.course_name, styles["BodyContent"])],
        [Paragraph("<b>Date of Submission:</b>", styles["BodyContent"]), Paragraph(datetime.now(timezone.utc).strftime("%d %B %Y"), styles["BodyContent"])],
        [Paragraph("<b>Moodle Assignment ID:</b>", styles["BodyContent"]), Paragraph(str(data.assignment_id), styles["BodyContent"])],
    ]

    meta_table = Table(meta_data, colWidths=[160, 280])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(meta_table)

    story.append(Spacer(1, 60))
    declaration = (
        "<i>Academic Integrity Declaration:</i><br/>"
        "I hereby confirm that the solution and execution captures enclosed within this document "
        "represent genuine, verified coursework executed in accordance with institutional guidelines."
    )
    story.append(Paragraph(declaration, styles["BodyContent"]))
    story.append(PageBreak())

    # ================= PAGE 2+: OBJECTIVE & ARTIFACTS =================
    story.append(Paragraph("1. Problem Statement & Objective", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=10))

    # Replace newlines with <br/> for ReportLab paragraph
    obj_formatted = data.objective_text.replace("\n", "<br/>")
    story.append(Paragraph(obj_formatted, styles["BodyContent"]))
    story.append(Spacer(1, 15))

    # 2. Source Code Screenshots
    story.append(Paragraph("2. Source Code Implementation", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=10))

    if data.code_images:
        for idx, c_img in enumerate(data.code_images, start=1):
            if c_img.exists():
                story.append(Paragraph(f"<b>Figure 2.{idx}:</b> Verified Source Code Rendering", styles["BodyContent"]))
                story.append(create_scaled_image_flowable(c_img))
                story.append(Spacer(1, 15))
    else:
        story.append(Paragraph("<i>No source code screenshots attached.</i>", styles["BodyContent"]))

    story.append(Spacer(1, 10))

    # 3. Execution Output Screenshots
    story.append(Paragraph("3. Program Execution & Verification Output", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=10))

    if data.output_images:
        for idx, o_img in enumerate(data.output_images, start=1):
            if o_img.exists():
                story.append(Paragraph(f"<b>Figure 3.{idx}:</b> Terminal Execution and Output Verification", styles["BodyContent"]))
                story.append(create_scaled_image_flowable(o_img))
                story.append(Spacer(1, 15))
    else:
        story.append(Paragraph("<i>No program execution output attached.</i>", styles["BodyContent"]))

    if data.additional_notes:
        story.append(Spacer(1, 15))
        story.append(Paragraph("4. Additional Observations & Results", styles["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E0"), spaceAfter=10))
        story.append(Paragraph(data.additional_notes.replace("\n", "<br/>"), styles["BodyContent"]))

    # Build the document with two-pass canvas
    doc.build(story, canvasmaker=NumberedCanvas)
    logger.info("Successfully generated submission PDF", extra={"pdf_path": str(data.output_pdf_path)})

    return data.output_pdf_path
