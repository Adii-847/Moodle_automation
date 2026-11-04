"""ReportLab canvas, layout dimensions, and two-pass page numbering."""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas

# A4 dimensions in points: 595.27 x 841.89
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 54  # 0.75 in
MARGIN_RIGHT = 54
MARGIN_TOP = 54
MARGIN_BOTTOM = 54

USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
USABLE_HEIGHT = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for dynamic 'Page X of Y' footer generation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#718096"))

        # Footer divider line
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(MARGIN_LEFT, MARGIN_BOTTOM - 15, PAGE_WIDTH - MARGIN_RIGHT, MARGIN_BOTTOM - 15)

        # Footer text
        footer_left = "Moodle Assignment Submission - System Verified"
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawString(MARGIN_LEFT, MARGIN_BOTTOM - 30, footer_left)
        self.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, MARGIN_BOTTOM - 30, page_str)

        self.restoreState()


def get_document_styles():
    """Build consistent typography stylesheet."""
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            "DocInstitution",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=22,
            alignment=1,  # Center
            textColor=colors.HexColor("#1A365D"),
            spaceAfter=8,
        )
    )

    styles.add(
        ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            alignment=1,  # Center
            textColor=colors.HexColor("#2B6CB0"),
            spaceAfter=20,
        )
    )

    styles.add(
        ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#2D3748"),
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        )
    )

    styles.add(
        ParagraphStyle(
            "BodyContent",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#2D3748"),
            spaceAfter=10,
        )
    )

    return styles

