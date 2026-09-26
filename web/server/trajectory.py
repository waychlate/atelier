"""2D path reconstruction from IMU samples.

Two methods:

- reconstruct_pointer_path (used whenever gyro data is present): treats the
  wand as a laser pointer. Recorded hardware data shows players draw almost
  entirely by rotating the wand — total acceleration stays within ~1 m/s^2
  of gravity during a stroke — so the drawing is where the wand points, not
  where the hand moves. Orientation comes from integrating the gyro, pulled
  toward the accelerometer's gravity reading to cancel gyro drift (a
  Mahony-style complementary filter); the path is the pointing axis's
  azimuth/elevation.
- reconstruct_path (fallback without gyro): double-integrates device-frame
  ax/ay with no orientation compensation. On real recordings this mostly
  picks up gravity shifting between axes as the wand tilts, which works for
  straight strokes but badly distorts curvy ones (S, M).
"""

import math

import numpy as np

from models import StrokeSample

# The IMU axis that points along the wand, in the chip's own frame. Measured
# on the current wand (board flat, z up, wand along +y) by drawing a
# horizontal and a vertical calibration line. A wand with the chip mounted
# differently needs this changed.
POINTING_AXIS = np.array([0.0, 1.0, 0.0])

# How hard the filter pulls the gyro-integrated orientation toward the
# accelerometer's gravity direction (rad/s per unit error). Higher trusts
# the accelerometer more: less drift, more jitter from hand acceleration.
FILTER_GAIN = 1.0


def _dt_array(samples: list[StrokeSample], sample_rate_hz: int) -> np.ndarray:
    # t is milliseconds since the letter started (firmware: uint32_t) — the
    # rest of this module works in seconds, so convert.
    t = np.array([s.t for s in samples], dtype=float)
    if len(t) > 1 and np.any(np.diff(t) > 0):
        return np.diff(t) / 1000.0
    dt = 1.0 / sample_rate_hz
    return np.full(len(samples) - 1, dt)


def _cumulative_trapz(series: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """Cumulative trapezoidal integration of a per-sample series over dt."""
    avg = (series[:-1] + series[1:]) / 2.0
    return np.concatenate(([0.0], np.cumsum(avg * dt)))


def integrate_axis(accel: np.ndarray, dt: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Double cumulative trapezoidal integration: accel -> velocity -> position."""
    velocity = _cumulative_trapz(accel, dt)
    position = _cumulative_trapz(velocity, dt)
    return velocity, position


def remove_drift(velocity: np.ndarray) -> np.ndarray:
    """Anchor velocity to ~0 at both stroke endpoints (button marks start/end).

    Subtracts the linear interpolation between velocity[0] and velocity[-1]
    from the whole series, per the spec's "fit and subtract a linear drift
    term... so the path starts and ends at rest."
    """
    n = len(velocity)
    if n < 2:
        return velocity
    ramp = np.linspace(velocity[0], velocity[-1], n)
    return velocity - ramp


def has_gyro(samples: list[StrokeSample]) -> bool:
    return bool(samples) and all(
        s.gx is not None and s.gy is not None and s.gz is not None for s in samples
    )


def _skew(v: np.ndarray) -> np.ndarray:
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def _rotation_step(omega: np.ndarray, dt: float) -> np.ndarray:
    """Rotation matrix for turning at body rate `omega` (rad/s) for `dt` s."""
    rate = float(np.linalg.norm(omega))
    if rate * dt < 1e-12:
        return np.eye(3)
    k = _skew(omega / rate)
    angle = rate * dt
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def _initial_attitude(accel: np.ndarray) -> np.ndarray:
    """Body->world rotation that puts measured gravity on world +z (heading
    is arbitrary: the path is re-centered, so only relative azimuth matters)."""
    g = accel / np.linalg.norm(accel)
    up = np.array([0.0, 0.0, 1.0])
    axis = np.cross(g, up)
    cos = float(g @ up)
    if np.linalg.norm(axis) < 1e-9:
        return np.eye(3) if cos > 0 else np.diag([1.0, -1.0, -1.0])
    k = _skew(axis)
    return np.eye(3) + k + (k @ k) / (1 + cos)


def reconstruct_pointer_path(
    samples: list[StrokeSample], sample_rate_hz: int
) -> list[tuple[float, float]]:
    """One (azimuth, elevation) point in radians per sample, pen-up samples
    included, so strokes keep their real positions relative to each other.
    x grows to the right and y grows up, like reconstruct_path. Not centered."""
    dt = _dt_array(samples, sample_rate_hz)
    accel = np.array([[s.ax, s.ay, s.az] for s in samples], dtype=float)
    gyro = np.radians(np.array([[s.gx, s.gy, s.gz] for s in samples], dtype=float))
    up = np.array([0.0, 0.0, 1.0])

    # Assumes the wand is roughly still at first pen-down; a small error here
    # is corrected by the filter within a second or so.
    rotation = _initial_attitude(accel[: min(5, len(accel))].mean(axis=0))

    points = []
    for i in range(len(samples)):
        if i > 0:
            omega = (gyro[i - 1] + gyro[i]) / 2.0
            norm = np.linalg.norm(accel[i])
            if norm > 0:
                expected_gravity = rotation.T @ up
                omega = omega + FILTER_GAIN * np.cross(accel[i] / norm, expected_gravity)
            rotation = rotation @ _rotation_step(omega, dt[i - 1])
        pointing = rotation @ POINTING_AXIS
        azimuth = math.atan2(pointing[0], pointing[1])
        elevation = math.asin(max(-1.0, min(1.0, float(pointing[2]))))
        points.append((azimuth, elevation))

    # Keep azimuth continuous if the wand swings past +-180 degrees.
    azimuths = np.unwrap([p[0] for p in points])
    return [(float(a), p[1]) for a, p in zip(azimuths, points)]


def center(path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not path:
        return path
    mx = sum(p[0] for p in path) / len(path)
    my = sum(p[1] for p in path) / len(path)
    return [(x - mx, y - my) for x, y in path]


def _reconstruct_axis(accel: np.ndarray, dt: np.ndarray) -> np.ndarray:
    velocity = _cumulative_trapz(accel, dt)
    velocity = remove_drift(velocity)
    position = _cumulative_trapz(velocity, dt)
    return position


def reconstruct_path(
    samples: list[StrokeSample], sample_rate_hz: int
) -> list[tuple[float, float]]:
    dt = _dt_array(samples, sample_rate_hz)
    ax = np.array([s.ax for s in samples], dtype=float)
    ay = np.array([s.ay for s in samples], dtype=float)

    x = _reconstruct_axis(ax, dt)
    # Sign flip confirmed against real hardware: with the wand held for
    # writing, +ay corresponds to physical downward motion, but the rest of
    # the pipeline (rasterize.py, app.js) treats +y as up. Without this the
    # whole reconstructed path renders vertically mirrored.
    y = -_reconstruct_axis(ay, dt)

    x = x - np.mean(x)
    y = y - np.mean(y)

    return list(zip(x.tolist(), y.tolist()))


def place_in_bbox(
    path: list[tuple[float, float]],
    target_bbox: tuple[tuple[float, float], tuple[float, float]],
) -> list[tuple[float, float]]:
    """Rescale/reposition an independently-reconstructed (mean-centered)
    stroke path to fit a target bounding box. Used to lay out multi-stroke
    submissions into their canonical slot for display — separate
    accelerometer recordings (one per button press) have no shared absolute
    position reference, so true relative placement can't be recovered from
    the IMU data alone; this shows each stroke's *shape* in its *expected*
    position instead."""
    if not path:
        return path
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)

    (tx0, ty0), (tx1, ty1) = target_bbox
    target_span = max(tx1 - tx0, ty1 - ty0, 1e-6)
    scale = target_span / span
    tcx, tcy = (tx0 + tx1) / 2, (ty0 + ty1) / 2

    return [(tcx + x * scale, tcy + y * scale) for x, y in path]
