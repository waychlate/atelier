"""Reconstructed 2D path (see trajectory.py) -> 28x28 grayscale image matching
the EMNIST training data's convention: white stroke (255) on black background
(0), upright orientation (confirmed against tanganke/emnist_letters samples).
"""

from PIL import Image, ImageDraw

WORK_SIZE = 256
STROKE_WIDTH = 18
TARGET_SIZE = 28
PADDING = 30


def path_to_image(path: list[tuple[float, float]], size: int = TARGET_SIZE) -> Image.Image:
    img = Image.new("L", (WORK_SIZE, WORK_SIZE), color=0)

    if len(path) < 2:
        return img.resize((size, size), Image.LANCZOS)

    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y, 1e-6)
    scale = (WORK_SIZE - 2 * PADDING) / span
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2

    def to_canvas(pt):
        x, y = pt
        px = WORK_SIZE / 2 + (x - cx) * scale
        py = WORK_SIZE / 2 - (y - cy) * scale  # flip y: path "up" -> image up
        return (px, py)

    points = [to_canvas(p) for p in path]
    draw = ImageDraw.Draw(img)
    draw.line(points, fill=255, width=STROKE_WIDTH, joint="curve")
    for p in points:
        r = STROKE_WIDTH / 2
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=255)

    return img.resize((size, size), Image.LANCZOS)
