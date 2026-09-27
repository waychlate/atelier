"""Shared CNN architecture — used by both train_model.py (offline training)
and scoring.py (runtime inference), so the two never drift apart.
"""

import string

import torch.nn as nn

LETTERS = string.ascii_uppercase  # index 0-25 == 'A'-'Z', matches the dataset's ClassLabel

# Kuzushiji-49 (K49) dataset's 49 classes (index 0-48), matching k49_classmap.csv
K49_LETTERS = [
    "あ", "い", "う", "え", "お",
    "か", "き", "く", "け", "こ",
    "さ", "し", "す", "せ", "そ",
    "た", "ち", "つ", "て", "と",
    "な", "に", "ぬ", "ね", "の",
    "は", "ひ", "ふ", "へ", "ほ",
    "ま", "み", "む", "め", "も",
    "や", "ゆ", "よ",
    "ら", "り", "る", "れ", "ろ",
    "わ", "ゐ", "ゑ", "を", "ん",
    "ゝ",
]


class EmnistCNN(nn.Module):
    def __init__(self, num_classes: int = len(LETTERS)):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),  # 28 -> 14
            nn.Conv2d(16, 32, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),  # 14 -> 7
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(32 * 7 * 7, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, num_classes),
        )

    def forward(self, x):
        return self.classifier(self.features(x))
