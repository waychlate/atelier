"""Offline training script for Japanese Kanji CNN — NOT run by the server.

Trains a small CNN on an augmented dataset of 10 foundational, high-semantic-value
Kanji characters ("日", "月", "火", "水", "木", "山", "川", "人", "口", "土").
Training data combines multiple system CJK font families and weights
(/usr/share/fonts/noto-cjk/*.ttc) with the Wikimedia Commons reference stroke-order
glyphs, subjected to extensive affine deformations, rotations, scale variations,
and morphological stroke-width adjustments matching rasterize.py conventions.

Saves weights to model/kanji_cnn.pt.

Run:
    python -m model.train_kanji_model
"""

import glob
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from torch.utils.data import DataLoader, Dataset

from model.cnn import EmnistCNN, KANJI_LETTERS

TRAIN_SAMPLES_PER_CLASS = 2500
TEST_SAMPLES_PER_CLASS = 500
TARGET_SIZE = 28
BATCH_SIZE = 128
EPOCHS = 8
LR = 1e-3

OUT_WEIGHTS = Path(__file__).parent / "kanji_cnn.pt"
GIF_DIR = Path(__file__).parent.parent.parent / "frontend" / "reference"


def find_system_fonts() -> list[str]:
    fonts = glob.glob("/usr/share/fonts/noto-cjk/*.ttc")
    if not fonts:
        fonts = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    return fonts


def load_gif_templates() -> dict[str, Image.Image]:
    """Extract and invert the completed glyph from each character's reference GIF."""
    templates = {}
    for char in KANJI_LETTERS:
        gif_path = GIF_DIR / f"{char}.gif"
        if not gif_path.exists():
            continue
        try:
            im = Image.open(gif_path)
            im.seek(getattr(im, "n_frames", 1) - 1)
            frame = im.convert("L")
            # Invert: reference GIFs have black strokes (0) on white (255).
            # Convert to white strokes (255) on black (0).
            inv = Image.eval(frame, lambda p: 255 if p < 128 else 0)
            templates[char] = inv
        except Exception as e:
            print(f"Warning: could not load GIF template for {char}: {e}")
    return templates


def augment_image(im_256: Image.Image) -> Image.Image:
    """Apply random affine, scale, rotation, and morphological stroke perturbations."""
    # Random rotation
    angle = random.uniform(-18, 18)
    work = im_256.rotate(angle, resample=Image.BILINEAR)

    # Random shear
    shear_x = random.uniform(-0.16, 0.16)
    shear_y = random.uniform(-0.16, 0.16)
    m = (1, shear_x, 0, shear_y, 1, 0)
    work = work.transform((256, 256), Image.AFFINE, m, resample=Image.BILINEAR)

    # Random shift
    dx = random.randint(-20, 20)
    dy = random.randint(-20, 20)
    shifted = Image.new("L", (256, 256), color=0)
    shifted.paste(work, (dx, dy))
    work = shifted

    # Stroke thickness variations (simulate varied brush/wand pressure)
    r = random.random()
    if r < 0.25:
        work = work.filter(ImageFilter.MaxFilter(random.choice([3, 5])))
    elif r < 0.40:
        work = work.filter(ImageFilter.MinFilter(3))
    elif r < 0.55:
        work = work.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.4, 1.2)))

    return work.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)


def render_font_sample(char: str, font_path: str) -> Image.Image:
    work = Image.new("L", (256, 256), color=0)
    draw = ImageDraw.Draw(work)
    font_size = random.randint(145, 195)
    font = ImageFont.truetype(font_path, font_size)
    draw.text((128, 128), char, fill=255, font=font, anchor="mm")
    return augment_image(work)


def render_gif_sample(template: Image.Image) -> Image.Image:
    # Resize template to 256x256 workspace
    work = template.resize((256, 256), Image.BILINEAR)
    return augment_image(work)


def generate_dataset(
    samples_per_class: int,
    fonts: list[str],
    gif_templates: dict[str, Image.Image],
) -> tuple[np.ndarray, np.ndarray]:
    imgs = []
    labels = []

    for label_idx, char in enumerate(KANJI_LETTERS):
        has_gif = char in gif_templates
        for _ in range(samples_per_class):
            if has_gif and random.random() < 0.35:
                im = render_gif_sample(gif_templates[char])
            elif fonts:
                font_path = random.choice(fonts)
                im = render_font_sample(char, font_path)
            elif has_gif:
                im = render_gif_sample(gif_templates[char])
            else:
                raise RuntimeError(f"No font or GIF available for {char}")

            arr = np.array(im, dtype=np.uint8)
            imgs.append(arr)
            labels.append(label_idx)

    return np.array(imgs), np.array(labels)


class KanjiTorchDataset(Dataset):
    def __init__(self, imgs: np.ndarray, labels: np.ndarray):
        self.imgs = imgs
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        arr = self.imgs[idx].astype(np.float32) / 255.0
        x = torch.from_numpy(arr).unsqueeze(0)  # (1, 28, 28)
        y = int(self.labels[idx])
        return x, y


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[float, float]:
    model.eval()
    correct = 0
    total = 0
    total_loss = 0.0
    criterion = nn.CrossEntropyLoss()
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = criterion(logits, y)
            total_loss += loss.item() * y.size(0)
            preds = logits.argmax(dim=1)
            correct += (preds == y).sum().item()
            total += y.size(0)
    return correct / total, total_loss / total


def main():
    print("=== Training Kanji 10-Class CNN Model ===")
    print(f"Target characters ({len(KANJI_LETTERS)}): {' '.join(KANJI_LETTERS)}")

    fonts = find_system_fonts()
    print(f"Discovered {len(fonts)} system CJK font weights")
    gif_templates = load_gif_templates()
    print(f"Loaded {len(gif_templates)} reference GIF glyph templates")

    print(f"Generating training data ({TRAIN_SAMPLES_PER_CLASS * len(KANJI_LETTERS)} samples)...")
    train_imgs, train_labels = generate_dataset(TRAIN_SAMPLES_PER_CLASS, fonts, gif_templates)
    print(f"Generating test data ({TEST_SAMPLES_PER_CLASS * len(KANJI_LETTERS)} samples)...")
    test_imgs, test_labels = generate_dataset(TEST_SAMPLES_PER_CLASS, fonts, gif_templates)

    train_ds = KanjiTorchDataset(train_imgs, train_labels)
    test_ds = KanjiTorchDataset(test_imgs, test_labels)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False)

    device = torch.device("cpu")
    model = EmnistCNN(num_classes=len(KANJI_LETTERS)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss()

    print(f"Training for {EPOCHS} epochs (device={device})...")
    for epoch in range(1, EPOCHS + 1):
        t0 = time.time()
        model.train()
        running_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * y.size(0)

        epoch_loss = running_loss / len(train_ds)
        test_acc, test_loss = evaluate(model, test_loader, device)
        elapsed = time.time() - t0
        print(
            f"Epoch {epoch:02d}/{EPOCHS:02d} - {elapsed:.1f}s | "
            f"Train Loss: {epoch_loss:.4f} | Test Acc: {test_acc * 100:.2f}% | Test Loss: {test_loss:.4f}"
        )

    OUT_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), OUT_WEIGHTS)
    print(f"Model saved to {OUT_WEIGHTS} ({OUT_WEIGHTS.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
