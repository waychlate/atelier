import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# SERVER_HOST, not HOST: many shells/OSes already export a HOST env var
# (usually the machine's hostname), which would silently override this
# default and could bind somewhere unreachable from another laptop.
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
ROUND_TIMEOUT_S = float(os.environ.get("ROUND_TIMEOUT_S", "15"))

# Tiger Data (TimescaleDB) service URL. Unset or unreachable -> in-memory only.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Single-player: must match PLAYER_ID in esp32/include/config.h.
PLAYER_ID = os.environ.get("PLAYER_ID", "player_1")

# ElevenLabs TTS for Blind mode (play the letter's sound instead of showing a
# stroke hint). Unset -> Blind mode stays locked in the UI, same pattern as
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "qWRrMoaOJUg6mVvRBiwM")
ELEVENLABS_JA_VOICE_ID = os.environ.get("ELEVENLABS_JA_VOICE_ID", "OrIijq7uyVaGDbu9tqly")


def voice_id_for_language(language: str) -> str:
    """Returns the appropriate ElevenLabs voice ID based on language."""
    if language in ("japanese", "kanji"):
        return ELEVENLABS_JA_VOICE_ID
    return ELEVENLABS_VOICE_ID


@dataclass
class Language:
    label: str
    letters: list[str]
    # False = plumbing only (SRS deck + stats tab exist) but not actually
    # playable yet: no stroke/CNN recognition built for this script. See
    # checkpoint.md's "Japanese: plumbing now, recognition later" note.
    enabled: bool = True
    definitions: dict[str, str] = field(default_factory=dict)


HIRAGANA_LETTERS = [
    "あ", "い", "う", "え", "お",
    "か", "き", "く", "け", "こ",
    "さ", "し", "す", "せ", "そ",
    "た", "ち", "つ", "て", "と",
    "な", "に", "ぬ", "ね", "の",
    "は", "ひ", "ふ", "へ", "ほ",
    "ま", "み", "む", "め", "も",
    "や", "ゆ", "よ",
    "ら", "り", "る", "れ", "ろ",
    "わ", "を", "ん",
]

KANJI_LETTERS = [
    "日", "月", "火", "水", "木",
    "山", "川", "人", "口", "土",
]

KANJI_DEFINITIONS: dict[str, str] = {
    "日": "Sun / Day",
    "月": "Moon / Month",
    "火": "Fire",
    "水": "Water",
    "木": "Tree / Wood",
    "山": "Mountain",
    "川": "River",
    "人": "Person",
    "口": "Mouth",
    "土": "Earth / Soil",
}

LANGUAGES: dict[str, Language] = {
    "latin": Language(label="Latin Alphabet", letters=list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
    "japanese": Language(
        label="Japanese (Hiragana)",
        letters=HIRAGANA_LETTERS,
        enabled=True,
    ),
    "kanji": Language(
        label="Japanese (Kanji)",
        letters=KANJI_LETTERS,
        enabled=True,
        definitions=KANJI_DEFINITIONS,
    ),
}
DEFAULT_LANGUAGE = "latin"

# Backward-compat alias; prefer LANGUAGES["latin"].letters in new code.
DEMO_LETTERS = LANGUAGES["latin"].letters
