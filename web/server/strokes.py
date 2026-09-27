"""Canonical per-letter stroke definitions: how many strokes a letter has,
each stroke's expected shape/direction, and control points for rendering a
reference/hint image. This is the single source of truth for both:
  - validating a player's submitted strokes (order + direction, strictly)
  - rendering the stroke-pattern reference image (generate_reference_images.py)
so the hint a player sees always matches exactly what gets validated.

Two stroke shapes are supported:
  - "line": validated by net displacement direction (8-way compass).
  - "circle": validated by rotational direction (clockwise/counterclockwise)
    via the shoelace formula — net displacement is close to zero for a
    closed loop, so the line check doesn't apply.

Letters with a single natural stroke (M, S — normally drawn as one
continuous motion) skip strict per-stroke validation entirely and fall back
to the whole-path CNN (scoring.score_stroke) in main.py. A multi-stroke
letter also falls back to the CNN if the submitted stroke count doesn't
match its canonical definition (e.g. someone draws G in one go instead of
circle-then-descender) — see main.py's /submit handler.

Coordinates follow the same convention as trajectory.reconstruct_path's
output: x right, y up, unit square.
"""

import math
from dataclasses import dataclass, field
from typing import Literal

DIRECTIONS = {
    "right": (1, 0),
    "left": (-1, 0),
    "up": (0, 1),
    "down": (0, -1),
    "up_right": (1, 1),
    "up_left": (-1, 1),
    "down_right": (1, -1),
    "down_left": (-1, -1),
}
# Strict: a submitted line stroke's direction must fall within this angle of
# the expected direction to pass at all (dot product >= cos(60deg)).
DIRECTION_MATCH_THRESHOLD = math.cos(math.radians(60))

# A perfect circle's enclosed area is pi/4 (~0.785) of its bounding box's
# area; require at least half that (a generously loose, noisy loop still
# passes) before treating a stroke as a valid circle at all.
CIRCLE_AREA_RATIO_MIN = 0.35
CIRCLE_AREA_RATIO_FULL_CREDIT = 0.6


@dataclass
class Stroke:
    control_points: list[tuple[float, float]]  # start -> ... -> end, for rendering
    direction: str  # for shape="line": key into DIRECTIONS; for "circle": cw/ccw
    shape: Literal["line", "circle"] = "line"


def _circle_points(
    center: tuple[float, float],
    radius: float,
    start_angle_deg: float,
    rotation: Literal["clockwise", "counterclockwise"],
    n: int = 32,
    sweep_deg: float = 350,
) -> list[tuple[float, float]]:
    """Densely-sampled points along a (near-)circle, for both rendering (the
    generic polyline renderer in generate_reference_images.py draws a smooth
    arc through enough points with no special-casing) and as the "ideal"
    shape a circular stroke is compared against. Sweeps slightly less than a
    full 360 degrees so start and end don't land on the same point — purely
    cosmetic (leaves room for the reference image's end arrowhead to be
    visible next to the start label instead of hidden under it); the
    area/rotation-based scoring doesn't care about the small gap."""
    cx, cy = center
    sign = 1 if rotation == "counterclockwise" else -1
    points = []
    for i in range(n + 1):
        t = i / n
        angle = math.radians(start_angle_deg) + sign * t * math.radians(sweep_deg)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


# Multi-stroke letters: strict order + direction/rotation enforcement applies.
MULTI_STROKE_LETTERS: dict[str, list[Stroke]] = {
    "T": [
        Stroke([(0.5, 1), (0.5, 0)], "down"),    # stem, top -> bottom
        Stroke([(0, 1), (1, 1)], "right"),       # top bar, left -> right
    ],
    "H": [
        Stroke([(0, 1), (0, 0)], "down"),        # left vertical, top -> bottom
        Stroke([(1, 1), (1, 0)], "down"),        # right vertical, top -> bottom
        Stroke([(0, 0.5), (1, 0.5)], "right"),   # crossbar, left -> right
    ],
    "A": [
        Stroke([(0, 0), (0.5, 1)], "up_right"),      # left leg, bottom -> apex
        Stroke([(0.5, 1), (1, 0)], "down_right"),    # right leg, apex -> bottom
        Stroke([(0.25, 0.4), (0.75, 0.4)], "right"), # crossbar, left -> right
    ],
    "E": [
        Stroke([(0, 1), (0, 0)], "down"),        # spine, top -> bottom
        Stroke([(0, 1), (0.8, 1)], "right"),     # top arm
        Stroke([(0, 0.5), (0.6, 0.5)], "right"), # middle arm
        Stroke([(0, 0), (0.8, 0)], "right"),     # bottom arm
    ],
    "G": [
        # bowl: circle, starting at the top, swept counterclockwise (like
        # drawing a "C"/"O" and closing the loop) — matches how most people
        # naturally trace a round bowl shape.
        Stroke(
            _circle_points((0.5, 0.62), 0.3, start_angle_deg=90, rotation="counterclockwise"),
            "counterclockwise",
            shape="circle",
        ),
        # descender, straight down from the bottom of the bowl
        Stroke([(0.5, 0.32), (0.5, 0.0)], "down"),
    ],
    "B": [
        Stroke([(0, 1), (0, 0)], "down"),  # stem, top -> bottom
        Stroke(
            _circle_points((0.35, 0.72), 0.22, start_angle_deg=90, rotation="clockwise"),
            "clockwise",
            shape="circle",
        ),  # upper bump
        Stroke(
            _circle_points((0.35, 0.28), 0.22, start_angle_deg=90, rotation="clockwise"),
            "clockwise",
            shape="circle",
        ),  # lower bump
    ],
    "D": [
        Stroke([(0, 1), (0, 0)], "down"),  # stem, top -> bottom
        Stroke(
            _circle_points((0.35, 0.5), 0.4, start_angle_deg=90, rotation="clockwise"),
            "clockwise",
            shape="circle",
        ),  # bowl
    ],
    "F": [
        Stroke([(0, 1), (0, 0)], "down"),        # stem, top -> bottom
        Stroke([(0, 1), (0.8, 1)], "right"),     # top bar
        Stroke([(0, 0.5), (0.55, 0.5)], "right"),  # middle bar
    ],
    "I": [
        Stroke([(0.5, 1), (0.5, 0)], "down"),  # stem, top -> bottom
    ],
    "K": [
        Stroke([(0, 1), (0, 0)], "down"),          # stem, top -> bottom
        Stroke([(0, 0.5), (1, 1)], "up_right"),    # upper diagonal, middle -> top-right
        Stroke([(0, 0.5), (1, 0)], "down_right"),  # lower diagonal, middle -> bottom-right
    ],
    "L": [
        Stroke([(0, 1), (0, 0)], "down"),   # stem, top -> bottom
        Stroke([(0, 0), (0.8, 0)], "right"),  # bottom bar
    ],
    "N": [
        Stroke([(0, 1), (0, 0)], "down"),          # left vertical, top -> bottom
        Stroke([(0, 1), (1, 0)], "down_right"),    # diagonal, top-left -> bottom-right
        Stroke([(1, 1), (1, 0)], "down"),          # right vertical, top -> bottom
    ],
    "O": [
        Stroke(
            _circle_points((0.5, 0.5), 0.45, start_angle_deg=90, rotation="counterclockwise"),
            "counterclockwise",
            shape="circle",
        ),
    ],
    "P": [
        Stroke([(0, 1), (0, 0)], "down"),  # stem, top -> bottom
        Stroke(
            _circle_points((0.35, 0.75), 0.25, start_angle_deg=90, rotation="clockwise"),
            "clockwise",
            shape="circle",
        ),  # bowl (upper only)
    ],
    "Q": [
        Stroke(
            _circle_points((0.5, 0.55), 0.4, start_angle_deg=90, rotation="counterclockwise"),
            "counterclockwise",
            shape="circle",
        ),  # bowl
        Stroke([(0.5, 0.3), (0.8, 0.0)], "down_right"),  # tail
    ],
    "R": [
        Stroke([(0, 1), (0, 0)], "down"),  # stem, top -> bottom
        Stroke(
            _circle_points((0.35, 0.75), 0.25, start_angle_deg=90, rotation="clockwise"),
            "clockwise",
            shape="circle",
        ),  # bowl (upper only)
        Stroke([(0.3, 0.45), (0.9, 0.0)], "down_right"),  # leg
    ],
    "X": [
        Stroke([(0, 1), (1, 0)], "down_right"),  # top-left -> bottom-right
        Stroke([(1, 1), (0, 0)], "down_left"),   # top-right -> bottom-left
    ],
    "Y": [
        Stroke([(0, 1), (0.5, 0.5)], "down_right"),   # left arm -> center
        Stroke([(1, 1), (0.5, 0.5)], "down_left"),    # right arm -> center
        Stroke([(0.5, 0.5), (0.5, 0)], "down"),       # stem, center -> bottom
    ],
    "Z": [
        Stroke([(0, 1), (1, 1)], "right"),       # top bar
        Stroke([(1, 1), (0, 0)], "down_left"),   # diagonal, top-right -> bottom-left
        Stroke([(0, 0), (1, 0)], "right"),       # bottom bar
    ],
}

# Single-stroke letters: drawn as one continuous motion, no natural pen-lift
# point to enforce — always scored by the whole-path CNN instead.
SINGLE_STROKE_LETTERS: dict[str, list[tuple[float, float]]] = {
    "M": [(0, 0), (0, 1), (0.5, 0.4), (1, 1), (1, 0)],
    "S": [(1, 1), (0, 0.85), (0, 0.55), (1, 0.45), (1, 0.15), (0, 0)],
    "C": [(0.9, 0.85), (0.6, 1), (0.2, 0.85), (0, 0.5), (0.2, 0.15), (0.6, 0), (0.9, 0.15)],
    "J": [(0.6, 1), (0.6, 0.3), (0.55, 0.1), (0.35, 0), (0.15, 0.05), (0.05, 0.25)],
    "U": [(0, 1), (0, 0.25), (0.15, 0.05), (0.5, 0), (0.85, 0.05), (1, 0.25), (1, 1)],
    "V": [(0, 1), (0.5, 0), (1, 1)],
    "W": [(0, 1), (0.25, 0), (0.5, 0.5), (0.75, 0), (1, 1)],
}


def stroke_bbox(stroke: Stroke) -> tuple[tuple[float, float], tuple[float, float]]:
    xs = [p[0] for p in stroke.control_points]
    ys = [p[1] for p in stroke.control_points]
    return (min(xs), min(ys)), (max(xs), max(ys))


def expected_stroke_count(letter: str) -> int:
    letter = letter.upper()
    if letter in MULTI_STROKE_LETTERS:
        return len(MULTI_STROKE_LETTERS[letter])
    return 1


def _unit(vx: float, vy: float) -> tuple[float, float]:
    norm = math.hypot(vx, vy)
    if norm < 1e-9:
        return (0.0, 0.0)
    return (vx / norm, vy / norm)


def _signed_area(path: list[tuple[float, float]]) -> float:
    """Shoelace formula, treating the path as a closed loop (wraps last
    point back to first) — positive means counterclockwise, negative means
    clockwise, in standard math (x right, y up) convention."""
    n = len(path)
    area = 0.0
    for i in range(n):
        x0, y0 = path[i]
        x1, y1 = path[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area / 2.0


def classify_line_stroke(path: list[tuple[float, float]], expected_direction: str) -> float:
    """Score one submitted line stroke against its expected direction. Uses
    net displacement (first point -> last point) rather than the full path
    shape — a stroke only needs to go the right way, not be a perfectly
    straight line. Returns 0-100; strictly 0 if outside tolerance."""
    if len(path) < 2:
        return 0.0

    dx = path[-1][0] - path[0][0]
    dy = path[-1][1] - path[0][1]
    ux, uy = _unit(dx, dy)
    if (ux, uy) == (0.0, 0.0):
        return 0.0

    ex, ey = _unit(*DIRECTIONS[expected_direction])
    dot = ux * ex + uy * ey

    if dot < DIRECTION_MATCH_THRESHOLD:
        return 0.0
    return max(0.0, min(1.0, dot)) * 100.0


def classify_circular_stroke(path: list[tuple[float, float]], expected_rotation: str) -> float:
    """Score one submitted circular stroke against its expected rotational
    direction. A loop's start/end points are close together, so net
    displacement (used for line strokes) doesn't apply — instead uses the
    shoelace formula's signed area, whose sign gives rotation and whose
    magnitude (relative to the stroke's own bounding box) gives a rough
    "how much of a loop was this really" confidence. Strictly 0 if rotation
    doesn't match or the stroke isn't loop-like enough."""
    if len(path) < 3:
        return 0.0

    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    bbox_area = max(max(xs) - min(xs), 1e-6) * max(max(ys) - min(ys), 1e-6)

    area = _signed_area(path)
    actual_rotation = "counterclockwise" if area > 0 else "clockwise"
    if actual_rotation != expected_rotation:
        return 0.0

    area_ratio = abs(area) / bbox_area
    if area_ratio < CIRCLE_AREA_RATIO_MIN:
        return 0.0

    confidence = min(1.0, area_ratio / CIRCLE_AREA_RATIO_FULL_CREDIT)
    return confidence * 100.0


def classify_stroke(path: list[tuple[float, float]], stroke: Stroke) -> float:
    if stroke.shape == "circle":
        return classify_circular_stroke(path, stroke.direction)
    return classify_line_stroke(path, stroke.direction)


def validate_strokes(
    paths: list[list[tuple[float, float]]], letter: str
) -> tuple[float, list[float]]:
    """Score submitted strokes against a multi-stroke letter's canonical
    order: submitted stroke i is checked against expected stroke i
    (position-wise, not best-permutation-matched) — this is what enforces
    order, since a stroke drawn out of sequence will usually fail its
    slot's check too. Returns (overall_score, per_stroke_scores)."""
    expected = MULTI_STROKE_LETTERS[letter.upper()]
    per_stroke = [
        classify_stroke(path, stroke) for path, stroke in zip(paths, expected)
    ]
    overall = sum(per_stroke) / len(per_stroke) if per_stroke else 0.0
    return overall, per_stroke
