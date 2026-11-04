"""Editor-style code screenshot generator using Pygments and Pillow."""

from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont
from pygments import lex
from pygments.lexers import get_lexer_by_name, guess_lexer_for_filename
from pygments.styles import get_style_by_name

from app.generation.planner import ProgrammingLanguage


def get_lexer_for_language(language: ProgrammingLanguage, filename: str):
    try:
        if language == ProgrammingLanguage.PYTHON:
            return get_lexer_by_name("python")
        elif language == ProgrammingLanguage.CPP:
            return get_lexer_by_name("cpp")
        elif language == ProgrammingLanguage.C:
            return get_lexer_by_name("c")
        elif language == ProgrammingLanguage.JAVA:
            return get_lexer_by_name("java")
        elif language == ProgrammingLanguage.SQL:
            return get_lexer_by_name("sql")
        else:
            return get_lexer_by_name("text")
    except Exception:
        return get_lexer_by_name("text")


def render_code_to_image(
    source_code: str,
    output_path: Path,
    language: ProgrammingLanguage = ProgrammingLanguage.PYTHON,
    title: str = "solution.py",
    font_size: int = 14,
    line_spacing: int = 4,
    max_lines_per_image: int = 60,
) -> List[Path]:
    """Render syntax-highlighted code inside a clean dark-theme editor window."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lexer = get_lexer_for_language(language, title)
    style = get_style_by_name("monokai")

    # Font handling with fallback to default PIL font
    try:
        font = ImageFont.truetype("consola.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    lines = source_code.splitlines() or [""]
    # Chunk lines into pages if source is lengthy
    pages: List[List[tuple[int, str]]] = []
    current_page: List[tuple[int, str]] = []

    for idx, line in enumerate(lines, start=1):
        current_page.append((idx, line))
        if len(current_page) >= max_lines_per_image:
            pages.append(current_page)
            current_page = []
    if current_page:
        pages.append(current_page)

    saved_images: List[Path] = []

    for page_idx, page_lines in enumerate(pages):
        page_num = f"_{page_idx + 1}" if len(pages) > 1 else ""
        current_out_path = output_path.with_name(f"{output_path.stem}{page_num}{output_path.suffix}")

        char_width = 8.5
        max_line_len = max(len(l[1]) for l in page_lines) if page_lines else 40
        gutter_width = 55
        window_padding = 20
        title_bar_height = 36
        line_height = font_size + line_spacing

        img_width = max(800, int(gutter_width + (max_line_len * char_width) + (window_padding * 2)))
        img_height = int(title_bar_height + (len(page_lines) * line_height) + (window_padding * 2))

        # Colors (Dark VS Code theme)
        bg_color = (30, 30, 30)
        gutter_bg = (37, 37, 38)
        title_bg = (45, 45, 45)
        text_color = (220, 220, 220)
        gutter_text_color = (133, 133, 133)

        img = Image.new("RGB", (img_width, img_height), bg_color)
        draw = ImageDraw.Draw(img)

        # Title bar
        draw.rectangle([(0, 0), (img_width, title_bar_height)], fill=title_bg)
        # Window control buttons (red, yellow, green)
        draw.ellipse([(14, 12), (24, 22)], fill=(255, 95, 86))
        draw.ellipse([(32, 12), (42, 22)], fill=(255, 189, 46))
        draw.ellipse([(50, 12), (60, 22)], fill=(39, 201, 63))

        # Title text
        display_title = f"{title} (Page {page_idx + 1}/{len(pages)})" if len(pages) > 1 else title
        draw.text((80, 10), display_title, fill=(200, 200, 200), font=font)

        # Gutter background
        draw.rectangle([(0, title_bar_height), (gutter_width, img_height)], fill=gutter_bg)

        # Render lines with line numbers
        y_offset = title_bar_height + window_padding
        page_code = "\n".join(l[1] for l in page_lines)
        tokens = list(lex(page_code, lexer))

        # Map tokens to lines
        curr_line_idx = 0
        x_cursor = gutter_width + window_padding
        line_no = page_lines[curr_line_idx][0]
        draw.text((12, y_offset), f"{line_no:3d}", fill=gutter_text_color, font=font)

        for ttype, tvalue in tokens:
            # Determine color from pygments style
            style_info = style.style_for_token(ttype)
            color_hex = style_info.get("color")
            if color_hex:
                token_color = (
                    int(color_hex[0:2], 16),
                    int(color_hex[2:4], 16),
                    int(color_hex[4:6], 16),
                )
            else:
                token_color = text_color

            token_lines = tvalue.split("\n")
            for sub_idx, sub_text in enumerate(token_lines):
                if sub_idx > 0:
                    # Newline
                    curr_line_idx += 1
                    y_offset += line_height
                    x_cursor = gutter_width + window_padding
                    if curr_line_idx < len(page_lines):
                        line_no = page_lines[curr_line_idx][0]
                        draw.text((12, y_offset), f"{line_no:3d}", fill=gutter_text_color, font=font)

                if sub_text:
                    draw.text((x_cursor, y_offset), sub_text, fill=token_color, font=font)
                    try:
                        bbox = draw.textbbox((x_cursor, y_offset), sub_text, font=font)
                        x_cursor = bbox[2]
                    except Exception:
                        x_cursor += len(sub_text) * int(char_width)

        img.save(current_out_path, format="PNG")
        saved_images.append(current_out_path)

    return saved_images

