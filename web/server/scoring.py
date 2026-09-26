"""DTW-based scoring of a live stroke against per-letter reference templates.

Grades on the raw accel time-series signal rather than a reconstructed 2D
path — double-integration drifts too much to compare shapes reliably, so we
let DTW handle timing/speed differences directly on ax/ay/az.
"""

import json
import math
from pathlib import Path

import numpy as np
from fastdtw import fastdtw

from models import StrokePacket, StrokeSample

DTW_SCALE = 50.0


def _euclidean(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


def _signal_from_samples(samples: list[dict] | list[StrokeSample]) -> np.ndarray:
    def get(s, key):
        return s[key] if isinstance(s, dict) else getattr(s, key)

    arr = np.array(
        [[get(s, "ax"), get(s, "ay"), get(s, "az")] for s in samples], dtype=float
    )
    mean = arr.mean(axis=0)
    std = arr.std(axis=0)
    std[std == 0] = 1.0
    return (arr - mean) / std


def load_templates(templates_dir: Path) -> dict[str, list[np.ndarray]]:
    templates: dict[str, list[np.ndarray]] = {}
    for path in sorted(templates_dir.glob("*.json")):
        letter = path.stem
        with open(path) as f:
            recordings = json.load(f)
        templates[letter] = [_signal_from_samples(rec) for rec in recordings]
    return templates


def score_stroke(packet: StrokePacket, templates: dict[str, list[np.ndarray]]) -> float:
    letter_templates = templates.get(packet.letter)
    if not letter_templates:
        return 0.0

    live_signal = _signal_from_samples(packet.samples)

    distances = []
    for template in letter_templates:
        dist, _ = fastdtw(live_signal, template, dist=_euclidean)
        distances.append(dist)

    # Best (nearest) match among the recorded template variants: a stroke
    # only needs to resemble one acceptable rendition of the letter, not
    # be equidistant from all of them.
    best = float(np.min(distances))
    normalized = 100.0 * math.exp(-best / DTW_SCALE)
    return max(0.0, min(100.0, normalized))


def feedback_code(accuracy: float) -> str:
    if accuracy >= 75:
        return "good"
    if accuracy >= 40:
        return "ok"
    return "bad"
