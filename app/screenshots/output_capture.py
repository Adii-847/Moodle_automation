"""Terminal-style execution output screenshot renderer using Pillow."""

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from app.execution.validation import ExecutionResult


def render_terminal_output_to_image(
    result: ExecutionResult,
    output_path: Path,
    title: str = "Terminal - Execution Output",
    font_size: int = 14,
    line_spacing: int = 4,
) -> Path:
    """Render authentic execution command, stdout, stderr, and return status into a terminal window PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        font = ImageFont.truetype("consola.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    # Lines to render
    terminal_lines = [
        (f"$ {result.command}", (255, 255, 255)),
    ]

    if result.stdout.strip():
        for line in result.stdout.splitlines():
            terminal_lines.append((line, (220, 220, 220)))

    if result.stderr.strip():
        for line in result.stderr.splitlines():
            terminal_lines.append((f"[stderr] {line}", (255, 110, 110)))

    # Status line
    status_text = f"Process finished with exit code {result.exit_code} (took {result.duration_seconds:.2f}s)"
    status_color = (100, 220, 100) if result.is_success else (255, 80, 80)
    terminal_lines.append(("", (0, 0, 0)))  # blank line
    terminal_lines.append((status_text, status_color))

    char_width = 8.5
    max_line_len = max(len(l[0]) for l in terminal_lines) if terminal_lines else 50
    padding = 20
    title_bar_height = 36
    line_height = font_size + line_spacing

    img_width = max(800, int((max_line_len * char_width) + (padding * 2)))
    img_height = int(title_bar_height + (len(terminal_lines) * line_height) + (padding * 2))

    # Dark terminal theme
    bg_color = (18, 18, 18)
    title_bg = (32, 32, 32)

    img = Image.new("RGB", (img_width, img_height), bg_color)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([(0, 0), (img_width, title_bar_height)], fill=title_bg)
    draw.ellipse([(14, 12), (24, 22)], fill=(255, 95, 86))
    draw.ellipse([(32, 12), (42, 22)], fill=(255, 189, 46))
    draw.ellipse([(50, 12), (60, 22)], fill=(39, 201, 63))
    draw.text((80, 10), title, fill=(200, 200, 200), font=font)

    # Render lines
    y_offset = title_bar_height + padding
    for text, color in terminal_lines:
        if text:
            draw.text((padding, y_offset), text, fill=color, font=font)
        y_offset += line_height

    img.save(output_path, format="PNG")
    return output_path

