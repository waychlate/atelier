"""One-time offline training script for Japanese hiragana CNN — NOT run by the server.

Trains a small CNN on the Kuzushiji-49 (K49) dataset (232,365 train / 38,547 test images,
49 classes, MNIST-format 28x28 grayscale, served by ROIS-CODH) and saves weights to
model/hiragana_cnn.pt, which the running server loads at startup via scoring.load_model().

Visual style caveat:
    Kuzushiji datasets (K49/KMNIST) are derived from classical Edo-period woodblock-printed
    books and use classical kuzushiji (cursive) hiragana glyphs. While most modern hiragana
    shapes are direct descendants of these forms and are visually very close to modern
    printed kana (such as the Noto Sans CJK reference hints), certain characters (e.g.
    'ゐ'/'ゑ' which are historical, or stylistic variants of 'せ'/'そ'/'ふ') exhibit cursive
    ligatures or older stroke conventions. Testing confirms common hiragana forms (あ, い,
    し, の, ん, etc.) align well with upright modern air-drawn shapes.

Orientation note:
    Unlike tanganke/emnist_letters, K49 images are stored upright (no 90-degree transpose
    or flip needed). Images are 0=background (black), 255=stroke (white), matching
    rasterize.py conventions.

Run:
    python -m model.train_hiragana_model
"""

import shutil
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from model.cnn import EmnistCNN, K49_LETTERS

DATA_URLS = {
    "train_imgs": "http://codh.rois.ac.jp/kmnist/dataset/k49/k49-train-imgs.npz",
    "train_labels": "http://codh.rois.ac.jp/kmnist/dataset/k49/k49-train-labels.npz",
    "test_imgs": "http://codh.rois.ac.jp/kmnist/dataset/k49/k49-test-imgs.npz",
    "test_labels": "http://codh.rois.ac.jp/kmnist/dataset/k49/k49-test-labels.npz",
}

EPOCHS = 6
BATCH_SIZE = 256
LR = 1e-3


def get_k49_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Retrieve K49 npz files, checking local cache, /tmp, or downloading if missing."""
    cache_dir = Path.home() / ".cache" / "k49"
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, url in DATA_URLS.items():
        fname = url.split("/")[-1]
        target = cache_dir / fname
        if not target.exists():
            tmp_path = Path("/tmp") / fname
            if tmp_path.exists():
                shutil.copy(tmp_path, target)
            else:
                print(f"Downloading {fname} from {url} ...")
                urllib.request.urlretrieve(url, target)
        paths[key] = target

    train_imgs = np.load(paths["train_imgs"])["arr_0"]
    train_labels = np.load(paths["train_labels"])["arr_0"]
    test_imgs = np.load(paths["test_imgs"])["arr_0"]
    test_labels = np.load(paths["test_labels"])["arr_0"]
    return train_imgs, train_labels, test_imgs, test_labels


class K49TorchDataset(Dataset):
    def __init__(self, imgs: np.ndarray, labels: np.ndarray):
        self.imgs = imgs
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        # Images are (28, 28) uint8 with 0=background, 255=stroke, stored upright.
        arr = self.imgs[idx].astype(np.float32) / 255.0
        x = torch.from_numpy(arr).unsqueeze(0)  # (1, 28, 28)
        y = int(self.labels[idx])
        return x, y


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> float:
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

    print("Loading Kuzushiji-49 (K49) dataset ...")
    train_imgs, train_labels, test_imgs, test_labels = get_k49_data()
    train_ds = K49TorchDataset(train_imgs, train_labels)
    test_ds = K49TorchDataset(test_imgs, test_labels)

    print(f"Loaded {len(train_ds):,} train and {len(test_ds):,} test samples.")

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=2)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=2)

    model = EmnistCNN(num_classes=len(K49_LETTERS)).to(device)
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

    out_path = Path(__file__).parent / "hiragana_cnn.pt"
    torch.save(model.state_dict(), out_path)
    print(f"Saved weights to {out_path}")
    print(f"Labels (index -> kana): {list(enumerate(K49_LETTERS))}")


if __name__ == "__main__":
    main()
