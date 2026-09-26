"""Dev/test helper: synthesizes fake accelerometer stroke(s) for one of the
demo letters and POSTs them to a running server, simulating the two-button
flow (POST /stroke per stroke, then POST /submit) — for end-to-end smoke
testing without real ESP32 hardware.

Usage:
    python scripts/simulate_stroke.py T [--base-url http://localhost:8000]
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

SAMPLE_RATE_HZ = 100
STROKE_DURATION_S = 0.8
GRAVITY = 9.81


def _smooth(series: np.ndarray, window: int) -> np.ndarray:
    kernel = np.ones(window) / window
    padded = np.pad(series, window, mode="edge")
    return np.convolve(padded, kernel, mode="same")[window:-window]


def _edge_taper(n_samples: int, edge_frac: float = 0.08) -> np.ndarray:
    taper = np.ones(n_samples)
    edge = max(2, int(n_samples * edge_frac))
    ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, edge)))
    taper[:edge] = ramp
    taper[-edge:] = ramp[::-1]
    return taper


def _path_to_xy(control_points, n_samples):
    control_points = np.array(control_points, dtype=float)
    t_control = np.linspace(0, 1, len(control_points))
    t_samples = np.linspace(0, 1, n_samples)
    x = np.interp(t_samples, t_control, control_points[:, 0])
    y = np.interp(t_samples, t_control, control_points[:, 1])
    window = max(3, n_samples // 12)
    return _smooth(x, window), _smooth(y, window)


def _xy_to_accel(x, y, dt, n_samples):
    vx = np.gradient(x, dt)
    vy = np.gradient(y, dt)
    taper = _edge_taper(n_samples)
    vx *= taper
    vy *= taper
    ax = np.gradient(vx, dt)
    ay = np.gradient(vy, dt)
    return ax, ay


def make_packet(control_points, letter: str, seed: int = 0, duration_s: float = STROKE_DURATION_S) -> dict:
    n_samples = int(SAMPLE_RATE_HZ * duration_s)
    rng = np.random.default_rng(seed)
    dt = 1.0 / SAMPLE_RATE_HZ
    x, y = _path_to_xy(control_points, n_samples)
    ax, ay = _xy_to_accel(x, y, dt, n_samples)

    ax = ax + rng.normal(0, 0.05, size=n_samples)
    ay = ay + rng.normal(0, 0.05, size=n_samples)
    az = GRAVITY + rng.normal(0, 0.05, size=n_samples)

    samples = [
        {
            "t": round(i * dt, 4),
            "ax": round(float(ax[i]), 5),
            "ay": round(float(ay[i]), 5),
            "az": round(float(az[i]), 5),
            "gx": 0.0,
            "gy": 0.0,
            "gz": 0.0,
        }
        for i in range(n_samples)
    ]
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


def simulate_letter(letter: str, base_url: str, seed: int = 0, single_shot: bool = False):
    letter = letter.upper()

    if letter in strokes.MULTI_STROKE_LETTERS and not single_shot:
        for i, stroke in enumerate(strokes.MULTI_STROKE_LETTERS[letter]):
            payload = make_packet(stroke.control_points, letter, seed=seed + i)
            ack = _post(f"{base_url}/stroke", payload)
            print("stroke ack:", ack)
    elif letter in strokes.MULTI_STROKE_LETTERS and single_shot:
        # simulate "drew it in one go" — chain all canonical strokes into
        # one continuous path (nearest-endpoint order), send as one stroke.
        combined = _chain_strokes(strokes.MULTI_STROKE_LETTERS[letter])
        payload = make_packet(combined, letter, seed=seed, duration_s=1.5)
        ack = _post(f"{base_url}/stroke", payload)
        print("stroke ack:", ack)
    else:
        payload = make_packet(
            strokes.SINGLE_STROKE_LETTERS[letter], letter, seed=seed, duration_s=1.5
        )
        ack = _post(f"{base_url}/stroke", payload)
        print("stroke ack:", ack)

    result = _post(f"{base_url}/submit", {})
    print("submit result:", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("letter", choices=list(strokes.MULTI_STROKE_LETTERS) + list(strokes.SINGLE_STROKE_LETTERS))
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--single-shot",
        action="store_true",
        help="for multi-stroke letters, simulate drawing it all in one continuous stroke",
    )
    args = parser.parse_args()

    simulate_letter(args.letter, args.base_url, single_shot=args.single_shot)


if __name__ == "__main__":
    main()
