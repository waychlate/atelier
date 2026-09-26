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

from model.cnn import EmnistCNN, LETTERS
from rasterize import path_to_image

LETTER_TO_INDEX = {letter: i for i, letter in enumerate(LETTERS)}


def load_model(weights_path: Path) -> torch.nn.Module:
    model = EmnistCNN()
    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    model.eval()
    return model


def score_stroke(
    path: list[tuple[float, float]], target_letter: str, model: torch.nn.Module
) -> float:
    index = LETTER_TO_INDEX.get(target_letter.upper())
    if index is None:
        return 0.0

    image = path_to_image(path)
    arr = np.array(image, dtype=np.float32) / 255.0
    x = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0)  # (1, 1, 28, 28)

    with torch.no_grad():
        probs = F.softmax(model(x), dim=1)[0]

    return float(probs[index].item()) * 100.0


def feedback_code(accuracy: float) -> str:
    if accuracy >= 75:
        return "good"
    if accuracy >= 40:
        return "ok"
    return "bad"
