"""Reconstructed 2D path (see trajectory.py) -> 28x28 grayscale image matching
the EMNIST training data's convention: white stroke (255) on black background
(0), upright orientation (confirmed against tanganke/emnist_letters samples).
"""

from PIL import Image, ImageDraw

WORK_SIZE = 256
STROKE_WIDTH = 18
TARGET_SIZE = 28
PADDING = 30


def path_to_image(
    path: list[tuple[float, float]] | list[list[tuple[float, float]]],
    size: int = TARGET_SIZE,
) -> Image.Image:
    img = Image.new("L", (WORK_SIZE, WORK_SIZE), color=0)

    if not path:
        return img.resize((size, size), Image.LANCZOS)

    # Distinguish single path [(x, y), ...] from list of paths [[(x, y), ...], ...]
    if (
        isinstance(path[0], (list, tuple))
        and len(path[0]) > 0
        and isinstance(path[0][0], (list, tuple))
    ):
        stroke_list: list[list[tuple[float, float]]] = [s for s in path if len(s) > 0]  # type: ignore
    else:
        stroke_list = [path]  # type: ignore

    all_points = [p for stroke in stroke_list for p in stroke]
    if len(all_points) < 2:
        return img.resize((size, size), Image.LANCZOS)

    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
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

    draw = ImageDraw.Draw(img)
    for stroke in stroke_list:
        if len(stroke) < 2:
            if len(stroke) == 1:
                px, py = to_canvas(stroke[0])
                r = STROKE_WIDTH / 2
                draw.ellipse([px - r, py - r, px + r, py + r], fill=255)
            continue
        points = [to_canvas(p) for p in stroke]
        draw.line(points, fill=255, width=STROKE_WIDTH, joint="curve")
        for p in points:
            r = STROKE_WIDTH / 2
            draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=255)

    return img.resize((size, size), Image.LANCZOS)
