"""PLACEHOLDER template generator — synthetic reference strokes for the demo
letter set (M, A, T, H, S, E), so the full pipeline runs end-to-end before
real recorded samples exist.

Replace templates/<letter>.json with real recordings once available;
scoring.load_templates() reads whatever JSON files are present in this
directory, so swapping these out needs no code changes elsewhere.

Run manually: python generate_templates.py
"""

import json
from pathlib import Path

import numpy as np

SAMPLE_RATE_HZ = 100
DURATION_S = 1.5
N_SAMPLES = int(SAMPLE_RATE_HZ * DURATION_S)
N_VARIANTS = 3
NOISE_STD = 0.05
GRAVITY = 9.81

# Rough control-point paths tracing each letter's shape (unit square).
LETTER_PATHS = {
    "M": [(0, 0), (0, 1), (0.5, 0.4), (1, 1), (1, 0)],
    "A": [(0, 0), (0.5, 1), (1, 0), (0.75, 0.4), (0.25, 0.4)],
    "T": [(0, 1), (1, 1), (0.5, 1), (0.5, 0)],
    "H": [(0, 0), (0, 1), (0, 0.5), (1, 0.5), (1, 1), (1, 0)],
    "S": [(1, 1), (0, 0.85), (0, 0.55), (1, 0.45), (1, 0.15), (0, 0)],
    "E": [(1, 1), (0, 1), (0, 0.5), (0.7, 0.5), (0, 0.5), (0, 0), (1, 0)],
}


def _path_to_xy(control_points, n_samples):
    control_points = np.array(control_points, dtype=float)
    t_control = np.linspace(0, 1, len(control_points))
    t_samples = np.linspace(0, 1, n_samples)
    x = np.interp(t_samples, t_control, control_points[:, 0])
    y = np.interp(t_samples, t_control, control_points[:, 1])
    return x, y


def _xy_to_accel(x, y, dt):
    vx = np.gradient(x, dt)
    vy = np.gradient(y, dt)
    ax = np.gradient(vx, dt)
    ay = np.gradient(vy, dt)
    return ax, ay


def generate_recording(letter: str, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    dt = 1.0 / SAMPLE_RATE_HZ
    x, y = _path_to_xy(LETTER_PATHS[letter], N_SAMPLES)
    ax, ay = _xy_to_accel(x, y, dt)

    ax = ax + rng.normal(0, NOISE_STD, size=N_SAMPLES)
    ay = ay + rng.normal(0, NOISE_STD, size=N_SAMPLES)
    az = GRAVITY + rng.normal(0, NOISE_STD, size=N_SAMPLES)

    return [
        {
            "t": round(i * dt, 4),
            "ax": round(float(ax[i]), 5),
            "ay": round(float(ay[i]), 5),
            "az": round(float(az[i]), 5),
            "gx": 0.0,
            "gy": 0.0,
            "gz": 0.0,
        }
        for i in range(N_SAMPLES)
    ]


def main():
    out_dir = Path(__file__).parent
    for letter in LETTER_PATHS:
        recordings = [generate_recording(letter, seed=i) for i in range(N_VARIANTS)]
        out_path = out_dir / f"{letter}.json"
        with open(out_path, "w") as f:
            json.dump(recordings, f, indent=2)
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
