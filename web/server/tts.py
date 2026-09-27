"""ElevenLabs TTS for Blind mode: plays a letter's name aloud instead of
showing a stroke hint, so the player has to recall the shape from sound
alone. Audio is generated once per (language, letter) and cached to disk
(see CLAUDE.md's "cache one clip per prompt" rule) — the demo shouldn't
depend on live API latency or availability mid-round.

Degrades gracefully: if ELEVENLABS_API_KEY isn't set (or a generation call
fails), `enabled`/the returned bytes are falsy and main.py keeps Blind mode
locked in the UI, the same pattern config.Language.enabled uses for
Japanese.
"""

import logging
from pathlib import Path

import httpx

import config

log = logging.getLogger("uvicorn.error")

CACHE_DIR = Path(__file__).parent / "tts_cache"
enabled = bool(config.ELEVENLABS_API_KEY)


def _cache_path(language: str, letter: str) -> Path:
    # Letters can be non-ASCII (Japanese kana); hex-encode for a safe filename.
    safe = letter.encode("utf-8").hex()
    return CACHE_DIR / language / f"{safe}.mp3"


async def get_or_generate(language: str, letter: str) -> bytes | None:
    """Cached MP3 bytes for this prompt, generating+caching on first request.
    None if TTS isn't configured or the API call fails — callers should treat
    that as "no audio available" (404), not a hard error."""
    if not enabled:
        return None

    path = _cache_path(language, letter)
    if path.exists():
        return path.read_bytes()

    voice_id = config.voice_id_for_language(language)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": config.ELEVENLABS_API_KEY,
                    "Accept": "audio/mpeg",
                },
                json={"text": letter, "model_id": "eleven_turbo_v2_5"},
            )
            resp.raise_for_status()
            audio = resp.content
    except Exception as e:
        log.warning("ElevenLabs TTS failed for %r/%r: %s", language, letter, e)
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return audio
