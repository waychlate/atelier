"""Scores a live stroke by rasterizing its reconstructed path (trajectory.py)
into a 28x28 image and classifying it with a small CNN trained on EMNIST
letters (see model/train_model.py). The score is simply how much probability
mass the model assigns to the target letter's class — naturally low both when
the model is confident in the wrong letter and when it's just unsure.
"""

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from model.cnn import EmnistCNN, LETTERS, K49_LETTERS
from rasterize import path_to_image


def make_letter_to_index(letters: list[str] | str) -> dict[str, int]:
    return {letter: i for i, letter in enumerate(letters)}


LETTER_TO_INDEX = make_letter_to_index(LETTERS)
HIRAGANA_LETTER_TO_INDEX = make_letter_to_index(K49_LETTERS)

# The hiragana CNN is a 49-way classifier (vs. Latin's 26-way) trained to
# 87.93% test accuracy (vs. Latin's 92.6%), so softmax spreads probability
# mass thinner across more, harder-to-separate classes even for a genuinely
# correct drawing — this consistently scores hiragana lower than an
# equivalently "correct" Latin letter for reasons unrelated to how well the
# player actually drew it. A sqrt-like curve (gamma < 1) lifts mid-low raw
# scores substantially while leaving 0 and 100 fixed, rather than scoring
# hiragana linearly against a tougher baseline.
HIRAGANA_SCORE_BOOST_GAMMA = 0.6


def load_model(weights_path: Path, num_classes: int = len(LETTERS)) -> torch.nn.Module:
    model = EmnistCNN(num_classes=num_classes)
    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    model.eval()
    return model


def score_stroke(
    path: list[tuple[float, float]],
    target_letter: str,
    model: torch.nn.Module,
    letter_to_index: dict[str, int] = LETTER_TO_INDEX,
) -> float:
    index = letter_to_index.get(target_letter)
    if index is None and target_letter.upper() in letter_to_index:
        index = letter_to_index[target_letter.upper()]
    if index is None:
        return 0.0

    image = path_to_image(path)
    arr = np.array(image, dtype=np.float32) / 255.0
    x = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0)  # (1, 1, 28, 28)

    with torch.no_grad():
        probs = F.softmax(model(x), dim=1)[0]

    raw = float(probs[index].item())
    if letter_to_index is HIRAGANA_LETTER_TO_INDEX:
        raw = raw**HIRAGANA_SCORE_BOOST_GAMMA
    return raw * 100.0


def feedback_code(accuracy: float) -> str:
    if accuracy >= 75:
        return "good"
    if accuracy >= 40:
        return "ok"
    return "bad"
