"""One-time asset generation: renders a stroke-order reference image for
each demo letter directly from strokes.py's canonical definitions, so the
hint a player sees always matches exactly what the server validates against
(no external dataset to keep in sync).

Run:
    python generate_reference_images.py

Writes to ../frontend/reference/<letter>.png
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import strokes

CANVAS = 320
PADDING = 50
BG_COLOR = (28, 28, 28)
STROKE_COLOR = (79, 195, 247)
LABEL_BG = (255, 255, 255)
LABEL_FG = (17, 17, 17)
LINE_WIDTH = 6
ARROW_LEN = 18
LABEL_RADIUS = 14

OUT_DIR = Path(__file__).parent.parent / "frontend" / "reference"


def _to_canvas(pt: tuple[float, float]) -> tuple[float, float]:
    x, y = pt
    cx = PADDING + x * (CANVAS - 2 * PADDING)
    cy = CANVAS - (PADDING + y * (CANVAS - 2 * PADDING))  # flip y: up = up on screen
    return (cx, cy)


def _draw_arrowhead(draw: ImageDraw.ImageDraw, tip, direction_rad, color):
    x, y = tip
    left = (
        x - ARROW_LEN * math.cos(direction_rad - math.pi / 7),
        y - ARROW_LEN * math.sin(direction_rad - math.pi / 7),
    )
    right = (
        x - ARROW_LEN * math.cos(direction_rad + math.pi / 7),
        y - ARROW_LEN * math.sin(direction_rad + math.pi / 7),
    )
    draw.polygon([tip, left, right], fill=color)


def _draw_line_and_arrow(draw: ImageDraw.ImageDraw, control_points):
    points = [_to_canvas(p) for p in control_points]
    draw.line(points, fill=STROKE_COLOR, width=LINE_WIDTH, joint="curve")

    (x0, y0), (x1, y1) = points[-2], points[-1]
    angle = math.atan2(y1 - y0, x1 - x0)
    _draw_arrowhead(draw, points[-1], angle, STROKE_COLOR)
    return points[0]


def _draw_label(draw: ImageDraw.ImageDraw, pos, label: int):
    lx, ly = pos
    draw.ellipse(
        [lx - LABEL_RADIUS, ly - LABEL_RADIUS, lx + LABEL_RADIUS, ly + LABEL_RADIUS],
        fill=LABEL_BG,
    )
    font = ImageFont.load_default()
    draw.text((lx, ly), str(label), fill=LABEL_FG, anchor="mm", font=font)


def render_letter(letter: str) -> Image.Image:
    img = Image.new("RGB", (CANVAS, CANVAS), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    letter = letter.upper()
    if letter in strokes.MULTI_STROKE_LETTERS:
        control_point_lists = [s.control_points for s in strokes.MULTI_STROKE_LETTERS[letter]]
    else:
        control_point_lists = [strokes.SINGLE_STROKE_LETTERS[letter]]

    # Two passes: all lines/arrows first, then all labels on top — otherwise
    # a later stroke's line can be drawn over an earlier stroke's label
    # circle when they share an edge (e.g. T's top bar passes right through
    # the vertical stroke's start point).
    label_positions = [_draw_line_and_arrow(draw, cp) for cp in control_point_lists]
    for i, pos in enumerate(label_positions, start=1):
        _draw_label(draw, pos, i)

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_letters = list(strokes.MULTI_STROKE_LETTERS) + list(strokes.SINGLE_STROKE_LETTERS)
    for letter in all_letters:
        img = render_letter(letter)
        out_path = OUT_DIR / f"{letter}.png"
        img.save(out_path)
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
