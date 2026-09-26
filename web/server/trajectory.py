"""Path reconstruction for display only — not used for scoring (see scoring.py).

We reconstruct a rough 2D path directly from the device-frame ax/ay axes, with no
orientation/gravity compensation: the device is held in a roughly fixed writing
posture for a demo, and the spec only needs the path to be "recognizable" on
screen, not metrically accurate. Full orientation estimation would add
error-prone complexity for no real payoff here.
"""

import numpy as np

from models import StrokePacket


def _dt_array(packet: StrokePacket) -> np.ndarray:
    t = np.array([s.t for s in packet.samples], dtype=float)
    if len(t) > 1 and np.any(np.diff(t) > 0):
        return np.diff(t)
    dt = 1.0 / packet.sample_rate_hz
    return np.full(len(packet.samples) - 1, dt)


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


def apply_gyro_correction(packet: StrokePacket) -> None:
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


def _split_into_strokes(
    x: np.ndarray, y: np.ndarray, pen: np.ndarray
) -> list[list[tuple[float, float]]]:
    """Groups consecutive pen-down points into separate strokes.

    Pen-up points still went into the integration above (so a stroke lands
    in the right place relative to the ones before it), but they're dropped
    here rather than drawn — otherwise every stroke in a letter renders as
    one continuous scribble through the movements between them.
    """
    strokes: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for xi, yi, is_pen in zip(x, y, pen):
        if is_pen:
            current.append((float(xi), float(yi)))
        elif current:
            strokes.append(current)
            current = []
    if current:
        strokes.append(current)
    return strokes


def reconstruct_path(packet: StrokePacket) -> list[list[tuple[float, float]]]:
    dt = _dt_array(packet)
    ax = np.array([s.ax for s in packet.samples], dtype=float)
    ay = np.array([s.ay for s in packet.samples], dtype=float)
    pen = np.array([s.pen for s in packet.samples], dtype=bool)

    x = _reconstruct_axis(ax, dt)
    y = _reconstruct_axis(ay, dt)

    # Center on the pen-down points only, so pen-up travel (e.g. reaching
    # over to the far side of a letter) doesn't skew where it sits on screen.
    if pen.any():
        x = x - np.mean(x[pen])
        y = y - np.mean(y[pen])

    return _split_into_strokes(x, y, pen)
