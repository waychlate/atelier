import os
from dataclasses import dataclass

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
ROUND_TIMEOUT_S = float(os.environ.get("ROUND_TIMEOUT_S", "15"))

# Tiger Data (TimescaleDB) service URL. Unset or unreachable -> in-memory only.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Single-player: must match PLAYER_ID in esp32/include/config.h.
PLAYER_ID = os.environ.get("PLAYER_ID", "player_1")

# ElevenLabs TTS for Blind mode (play the letter's sound instead of showing a
# stroke hint). Unset -> Blind mode stays locked in the UI, same pattern as
# config.Language.enabled — see tts.py.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


@dataclass
class Language:
    label: str
    letters: list[str]
    # False = plumbing only (SRS deck + stats tab exist) but not actually
    # playable yet: no stroke/CNN recognition built for this script. See
    # checkpoint.md's "Japanese: plumbing now, recognition later" note.
    enabled: bool = True


LANGUAGES: dict[str, Language] = {
    "latin": Language(label="Latin Alphabet", letters=list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
    "japanese": Language(
        label="Japanese (Hiragana)",
        letters=["あ", "い", "う", "え", "お"],
        enabled=False,
    ),
}
DEFAULT_LANGUAGE = "latin"

# Backward-compat alias; prefer LANGUAGES["latin"].letters in new code.
DEMO_LETTERS = LANGUAGES["latin"].letters
