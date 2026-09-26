"""Path reconstruction for display only — not used for scoring (see scoring.py).

We reconstruct a rough 2D path directly from the device-frame ax/ay axes, with no
orientation/gravity compensation: the device is held in a roughly fixed writing
posture for a demo, and the spec only needs the path to be "recognizable" on
screen, not metrically accurate. Full orientation estimation would add
error-prone complexity for no real payoff here.
"""

import numpy as np

from models import StrokeSample


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


def apply_gyro_correction(samples: list[StrokeSample]) -> None:
    """Stub: rotation-drift correction using gx/gy/gz, if the raw-axis
    reconstruction below ever proves visually unusable. Not wired into the
    default pipeline — gyro remains an optional input the pipeline never
    requires, per the data contract's "degrade gracefully without gyro"."""
    return None


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
    y = _reconstruct_axis(ay, dt)

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
