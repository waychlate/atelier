"""One-time offline training script — NOT run by the server.

Trains a small CNN on the tanganke/emnist_letters Hugging Face dataset
(124,800 train / 20,800 test images, labels 'A'-'Z', ~59MB, served off HF's
CDN) and saves weights to model/emnist_cnn.pt, which the running server
loads at startup via scoring.load_model().

One-off setup (not needed at server runtime, only to (re)train):
    pip install --extra-index-url https://download.pytorch.org/whl/cpu torch datasets pillow

Run:
    python -m model.train_model
"""

import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from datasets import load_dataset
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from model.cnn import EmnistCNN, LETTERS


def fix_orientation(img: Image.Image) -> Image.Image:
    """tanganke/emnist_letters images are stored transposed (the classic
    EMNIST byte-format bug, inherited by this re-upload) — confirmed by
    inspecting simple directional letters (I, T) which come out sideways
    without this fix. Must mirror whatever rasterize.py produces upright."""
    return img.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)

EPOCHS = 6
BATCH_SIZE = 256
LR = 1e-3


class EmnistTorchDataset(Dataset):
    def __init__(self, hf_split):
        self.hf_split = hf_split

    def __len__(self):
        return len(self.hf_split)

    def __getitem__(self, idx):
        row = self.hf_split[idx]
        img = fix_orientation(row["image"])
        arr = np.array(img, dtype=np.float32) / 255.0
        x = torch.from_numpy(arr).unsqueeze(0)  # (1, 28, 28)
        y = row["label"]
        return x, y


def evaluate(model, loader, device):
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            preds = model(x).argmax(dim=1)
            correct += (preds == y).sum().item()
            total += y.size(0)
    return correct / total


def main():
    device = torch.device("cpu")

    print("Loading tanganke/emnist_letters ...")
    ds = load_dataset("tanganke/emnist_letters")
    train_ds = EmnistTorchDataset(ds["train"])
    test_ds = EmnistTorchDataset(ds["test"])

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=2)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=2)

    model = EmnistCNN().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        start = time.time()
        total_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * x.size(0)

        train_loss = total_loss / len(train_ds)
        test_acc = evaluate(model, test_loader, device)
        elapsed = time.time() - start
        print(
            f"epoch {epoch}/{EPOCHS}  loss={train_loss:.4f}  "
            f"test_acc={test_acc:.4f}  ({elapsed:.1f}s)"
        )

    out_path = Path(__file__).parent / "emnist_cnn.pt"
    torch.save(model.state_dict(), out_path)
    print(f"Saved weights to {out_path}")
    print(f"Labels (index -> letter): {list(enumerate(LETTERS))}")


if __name__ == "__main__":
    main()
