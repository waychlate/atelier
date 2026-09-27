"""One-time asset generation: renders reference glyph images for Japanese
hiragana into web/frontend/reference/<char>.png using Noto Sans CJK.

Run:
    python generate_hiragana_reference_images.py
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import config

CANVAS = 320
BG_COLOR = (28, 28, 28)
STROKE_COLOR = (79, 195, 247)
FONT_PATH = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
FONT_SIZE = 190

OUT_DIR = Path(__file__).parent.parent / "frontend" / "reference"


def render_hiragana(char: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    img = Image.new("RGB", (CANVAS, CANVAS), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.text((CANVAS // 2, CANVAS // 2), char, fill=STROKE_COLOR, font=font, anchor="mm")
    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    letters = config.LANGUAGES["japanese"].letters
    for char in letters:
        img = render_hiragana(char, font)
        out_path = OUT_DIR / f"{char}.png"
        img.save(out_path)
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
