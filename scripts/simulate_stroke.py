"""Dev/test helper: synthesizes a fake IMU (accel + gyro) letter recording and
POSTs it to a running server as a single /stroke call — matching the real
firmware's actual contract (esp32/ on the `firmware` branch): one HTTP POST
per letter, covering every stroke from first pen-down to the submit button
press, with each sample tagged `pen` (mid-stroke vs. a gap between strokes).
There is no separate /submit endpoint — the submit button just triggers
sending this one packet.

Usage:
    python scripts/simulate_stroke.py T [--base-url http://localhost:8000]
    python scripts/simulate_stroke.py G --single-shot   # drawn without lifting
    python scripts/simulate_stroke.py S --no-gyro       # exercise the accel-only fallback
"""

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "web" / "server"))
import strokes  # noqa: E402

SAMPLE_RATE_HZ = 50  # matches esp32/include/config.example.h's SAMPLE_INTERVAL_MS=20
STROKE_DURATION_S = 0.8
GAP_DURATION_S = 0.3
GRAVITY = 9.81
ANGLE_SPAN_DEG = 40.0  # how far the wand swings across a letter (real data: ~40-70)
ACCEL_NOISE = 0.05  # m/s^2
GYRO_NOISE_DPS = 0.5


def _chain_strokes(stroke_defs) -> list[tuple[float, float]]:
    """Concatenate canonical strokes into one continuous path for the
    "drew it in one go" test, reversing each subsequent stroke if that
    orientation starts closer to where the previous one ended — a naive
    concatenation can leave a big teleport jump (e.g. G's circle ends near
    its own top, but its descender starts at the bottom), which doesn't
    look anything like how someone would actually draw it without lifting
    the pen, and confuses the CNN fallback for reasons that have nothing to
    do with the actual model or reconstruction quality."""
    combined = list(stroke_defs[0].control_points)
    for stroke in stroke_defs[1:]:
        pts = stroke.control_points
        last = combined[-1]
        dist_to_start = math.hypot(pts[0][0] - last[0], pts[0][1] - last[1])
        dist_to_end = math.hypot(pts[-1][0] - last[0], pts[-1][1] - last[1])
        if dist_to_end < dist_to_start:
            pts = list(reversed(pts))
        combined.extend(pts)
    return combined


def _smooth(series: np.ndarray, window: int) -> np.ndarray:
    kernel = np.ones(window) / window
    padded = np.pad(series, window, mode="edge")
    return np.convolve(padded, kernel, mode="same")[window:-window]


def _path_to_xy(control_points, n_samples):
    control_points = np.array(control_points, dtype=float)
    t_control = np.linspace(0, 1, len(control_points))
    t_samples = np.linspace(0, 1, n_samples)
    x = np.interp(t_samples, t_control, control_points[:, 0])
    y = np.interp(t_samples, t_control, control_points[:, 1])
    window = max(3, n_samples // 12)
    return _smooth(x, window), _smooth(y, window)


def _letter_xy(stroke_control_point_lists):
    """Whole-letter (x, y, pen) in unit-square coordinates: each stroke's
    path, with the pen-up move from one stroke's end to the next stroke's
    start in between (the hand keeps moving while the pen is up)."""
    n_stroke = int(SAMPLE_RATE_HZ * STROKE_DURATION_S)
    n_gap = int(SAMPLE_RATE_HZ * GAP_DURATION_S)
    xs, ys, pens = [], [], []
    for i, control_points in enumerate(stroke_control_point_lists):
        x, y = _path_to_xy(control_points, n_stroke)
        xs.append(x)
        ys.append(y)
        pens.append(np.ones(n_stroke, dtype=bool))
        if i < len(stroke_control_point_lists) - 1:
            gx, gy = _path_to_xy([(x[-1], y[-1]), stroke_control_point_lists[i + 1][0]], n_gap)
            xs.append(gx)
            ys.append(gy)
            pens.append(np.zeros(n_gap, dtype=bool))
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(pens)


def _pointer_imu(x, y, rng):
    """IMU readings for a wand that *aims* at (x, y) rather than moving
    there — recorded hardware data shows players draw by rotating the wand
    (total acceleration stays within ~1 m/s^2 of gravity). Matches the real
    wand's mounting as measured by calibration: chip flat (z up), wand
    pointing along +y, so x maps to yaw and y to pitch.

    With orientation R = Rz(yaw) @ Rx(pitch), body-frame gyro rates are
    (pitch', yaw' sin(pitch), yaw' cos(pitch)) and the accelerometer sees
    gravity tilted into y/z: (0, g sin(pitch), g cos(pitch))."""
    span = math.radians(ANGLE_SPAN_DEG)
    yaw = -(x - 0.5) * span
    pitch = (y - 0.5) * span
    dt = 1.0 / SAMPLE_RATE_HZ
    yaw_rate = np.gradient(yaw, dt)
    pitch_rate = np.gradient(pitch, dt)
    n = len(x)

    gyro = np.degrees(
        np.stack([pitch_rate, yaw_rate * np.sin(pitch), yaw_rate * np.cos(pitch)], axis=1)
    ) + rng.normal(0, GYRO_NOISE_DPS, size=(n, 3))
    accel = np.stack(
        [np.zeros(n), GRAVITY * np.sin(pitch), GRAVITY * np.cos(pitch)], axis=1
    ) + rng.normal(0, ACCEL_NOISE, size=(n, 3))
    return accel, gyro


def assemble_letter_packet(
    letter: str, stroke_control_point_lists, seed: int = 0, include_gyro: bool = True
) -> dict:
    """Build one whole-letter packet: each control-point list becomes a
    pen=True run, with a pen=False gap run inserted between consecutive
    strokes (not after the last one) — mirrors the firmware's actual
    buffer, which spans every stroke plus the pauses between them.
    include_gyro=False omits gx/gy/gz to exercise the server's accel-only
    fallback."""
    rng = np.random.default_rng(seed)
    x, y, pen = _letter_xy(stroke_control_point_lists)
    accel, gyro = _pointer_imu(x, y, rng)

    dt_ms = 1000.0 / SAMPLE_RATE_HZ
    samples = []
    for i in range(len(x)):
        sample = {
            "t": round(i * dt_ms),
            "ax": round(float(accel[i, 0]), 5),
            "ay": round(float(accel[i, 1]), 5),
            "az": round(float(accel[i, 2]), 5),
            "pen": bool(pen[i]),
        }
        if include_gyro:
            sample.update(
                gx=round(float(gyro[i, 0]), 5),
                gy=round(float(gyro[i, 1]), 5),
                gz=round(float(gyro[i, 2]), 5),
            )
        samples.append(sample)
    return {
        "player_id": "player",
        "letter": letter,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "samples": samples,
    }


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def simulate_letter(
    letter: str,
    base_url: str,
    seed: int = 0,
    single_shot: bool = False,
    include_gyro: bool = True,
):
    letter = letter.upper()

    if letter in strokes.MULTI_STROKE_LETTERS and not single_shot:
        control_point_lists = [s.control_points for s in strokes.MULTI_STROKE_LETTERS[letter]]
    elif letter in strokes.MULTI_STROKE_LETTERS and single_shot:
        # drawn without lifting: one continuous pen=True run, no gaps.
        control_point_lists = [_chain_strokes(strokes.MULTI_STROKE_LETTERS[letter])]
    else:
        control_point_lists = [strokes.SINGLE_STROKE_LETTERS[letter]]

    payload = assemble_letter_packet(
        letter, control_point_lists, seed=seed, include_gyro=include_gyro
    )
    result = _post(f"{base_url}/stroke", payload)
    print("result:", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "letter", choices=list(strokes.MULTI_STROKE_LETTERS) + list(strokes.SINGLE_STROKE_LETTERS)
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--single-shot",
        action="store_true",
        help="for multi-stroke letters, simulate drawing it all in one continuous stroke",
    )
    parser.add_argument(
        "--no-gyro",
        action="store_true",
        help="omit gx/gy/gz so the server uses its accel-only fallback",
    )
    args = parser.parse_args()

    simulate_letter(
        args.letter, args.base_url, single_shot=args.single_shot, include_gyro=not args.no_gyro
    )


if __name__ == "__main__":
    main()
