import asyncio
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import config
import scoring
import strokes
import trajectory
import tts
from db import TigerStore
from game_state import GameState
from models import (
    CursorMessage,
    ESP32FeedbackResponse,
    LanguageInfo,
    LanguagesResponse,
    LetterStats,
    LiveSample,
    ModeInfo,
    ModesResponse,
    RoundStartMessage,
    StatsResponse,
    StrokePacket,
    StrokeResultMessage,
    StrokeSample,
)

MODES = {
    "learn": "Shows stroke hints",
    "blind": "Sound only — no stroke hints",
}

log = logging.getLogger("uvicorn.error")


class _SkipLiveAccessLog(logging.Filter):
    """/stroke/live is hit 50 times a second, all the time - logging each
    one would bury every other request in the server terminal."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/stroke/live" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SkipLiveAccessLog())

app = FastAPI()

game_state = GameState()
model = None
latin_model = None
hiragana_model = None
db: TigerStore | None = None
ws_clients: set[WebSocket] = set()
background_tasks: set[asyncio.Task] = set()

MODEL_PATH = Path(__file__).parent / "model" / "emnist_cnn.pt"
HIRAGANA_MODEL_PATH = Path(__file__).parent / "model" / "hiragana_cnn.pt"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Tracks wand orientation between /stroke/live calls for the live cursor.
# Display only - not used for scoring, which always replays the full letter
# through trajectory.reconstruct_pointer_path once /stroke is called.
live_tracker = trajectory.LiveOrientationTracker()

# Opt-in: set RECORD_DIR to save every incoming packet as JSON, for tuning
# trajectory reconstruction against real hardware data offline.
RECORD_DIR = os.environ.get("RECORD_DIR")


def record_packet(packet: StrokePacket) -> None:
    if not RECORD_DIR:
        return
    out_dir = Path(RECORD_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{packet.letter}.json"
    path.write_text(packet.model_dump_json())
    print(f"Recorded {len(packet.samples)} samples to {path}")


@app.on_event("startup")
async def on_startup():
    global model, latin_model, hiragana_model, db
    model = scoring.load_model(MODEL_PATH)
    latin_model = model

    if HIRAGANA_MODEL_PATH.exists():
        try:
            hiragana_model = scoring.load_model(
                HIRAGANA_MODEL_PATH, num_classes=len(scoring.HIRAGANA_LETTER_TO_INDEX)
            )
            log.info("Hiragana CNN loaded: %s", HIRAGANA_MODEL_PATH)
        except Exception as e:
            hiragana_model = None
            log.warning("Hiragana CNN failed to load, Japanese unavailable: %s", e)
    else:
        log.warning("Hiragana model not found at %s; Japanese unavailable", HIRAGANA_MODEL_PATH)

    if hiragana_model is None and "japanese" in config.LANGUAGES:
        config.LANGUAGES["japanese"].enabled = False

    if config.DATABASE_URL:
        try:
            db = await TigerStore.connect(config.DATABASE_URL)
            for lang in config.LANGUAGES:
                cards, clock = await db.load(game_state.player_id, lang)
                game_state.load(lang, cards, clock)
            n = len(game_state.cards_by_language.get(config.DEFAULT_LANGUAGE, {}))
            log.info("Tiger Data connected: %d cards loaded for %s", n, config.DEFAULT_LANGUAGE)
        except Exception as e:
            db = None
            log.warning("Tiger Data unavailable, running in-memory only: %s", e)
    else:
        log.info("DATABASE_URL not set, running in-memory only")
    game_state.start_game()


@app.on_event("shutdown")
async def on_shutdown():
    if db:
        await db.close()


async def broadcast(message) -> None:
    payload = message.model_dump_json()
    dead = set()
    for client in ws_clients:
        try:
            await client.send_text(payload)
        except Exception:
            dead.add(client)
    ws_clients.difference_update(dead)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        await websocket.send_text(
            RoundStartMessage(
                round_id=game_state.round_id,
                language=game_state.language,
                target_letter=game_state.target_letter,
            ).model_dump_json()
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)


@app.get("/round/current")
def get_current_round() -> RoundStartMessage:
    return RoundStartMessage(
        round_id=game_state.round_id,
        language=game_state.language,
        target_letter=game_state.target_letter,
    )


@app.post("/round/next")
async def next_round() -> RoundStartMessage:
    msg = game_state.next_letter()
    await broadcast(msg)
    return msg


@app.post("/round/reset")
async def reset_round() -> RoundStartMessage:
    """New session (score back to 0). SRS progress and history are kept."""
    msg = game_state.start_game()
    await broadcast(msg)
    return msg


@app.get("/languages")
def get_languages() -> LanguagesResponse:
    return LanguagesResponse(
        active=game_state.language,
        languages=[
            LanguageInfo(code=code, label=lang.label, enabled=lang.enabled, letter_count=len(lang.letters))
            for code, lang in config.LANGUAGES.items()
        ],
    )


@app.post("/language/{code}")
async def set_language(code: str) -> RoundStartMessage:
    """Switch the active deck. Only enabled languages are playable — see
    config.Language.enabled."""
    lang = config.LANGUAGES.get(code)
    if lang is None:
        raise HTTPException(404, f"unknown language {code!r}")
    if not lang.enabled or (code == "japanese" and hiragana_model is None):
        raise HTTPException(400, f"{code!r} isn't playable yet")
    msg = game_state.set_language(code)
    await broadcast(msg)
    return msg


@app.get("/modes")
def get_modes() -> ModesResponse:
    return ModesResponse(
        active=game_state.mode,
        modes=[
            ModeInfo(
                code=code,
                label=code.capitalize(),
                description=description,
                enabled=tts.enabled if code == "blind" else True,
            )
            for code, description in MODES.items()
        ],
    )


@app.post("/mode/{code}")
async def set_mode(code: str) -> RoundStartMessage:
    """Switch Learn/Blind. Blind requires ElevenLabs to be configured (see
    tts.py) — same locked-until-configured pattern as an unconfirmed
    language."""
    if code not in MODES:
        raise HTTPException(404, f"unknown mode {code!r}")
    if code == "blind" and not tts.enabled:
        raise HTTPException(400, "blind mode needs ELEVENLABS_API_KEY configured")
    msg = game_state.set_mode(code)
    await broadcast(msg)
    return msg


@app.get("/tts/{language}/{letter}")
async def get_tts(language: str, letter: str) -> Response:
    audio = await tts.get_or_generate(language, letter)
    if audio is None:
        raise HTTPException(404, "tts unavailable for this prompt")
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/progress/reset")
async def reset_progress(language: str | None = None) -> RoundStartMessage:
    """Wipe SRS cards and attempt history for one language (default: the
    active one) — other languages' decks are untouched."""
    language = language or game_state.language
    if language not in config.LANGUAGES:
        raise HTTPException(404, f"unknown language {language!r}")
    game_state.reset_progress(language)
    if db:
        try:
            await db.reset_player(game_state.player_id, language)
        except Exception as e:
            log.warning("Tiger Data reset failed: %s", e)

    if language != game_state.language:
        # Reset a deck that isn't being played right now — nothing about
        # the live round changes, so there's nothing new to broadcast.
        return RoundStartMessage(
            round_id=game_state.round_id, language=game_state.language,
            target_letter=game_state.target_letter,
        )
    msg = game_state.start_game()
    await broadcast(msg)
    return msg


@app.get("/stats")
async def get_stats(language: str | None = None) -> StatsResponse:
    language = language or game_state.language
    if language not in config.LANGUAGES:
        raise HTTPException(404, f"unknown language {language!r}")

    source = "local"
    letter_aggs, timeline = game_state.local_stats(language)
    if db:
        try:
            letter_aggs, timeline = await db.stats(game_state.player_id, language)
            source = "tiger"
        except Exception as e:
            log.warning("Tiger Data stats failed, using local: %s", e)

    cards = game_state.cards_by_language.get(language, {})
    clock = game_state.clock_by_language.get(language, 0)
    letters = []
    for letter in config.LANGUAGES[language].letters:
        agg = letter_aggs.get(letter, {})
        card = cards.get(letter)
        letters.append(
            LetterStats(
                letter=letter,
                status=card.status if card else "new",
                attempts=agg.get("attempts", 0),
                avg_score=agg.get("avg_score"),
                best_score=agg.get("best_score"),
                recent=agg.get("recent", []),
                ease=card.ease if card else None,
                due_in=card.due - clock if card else None,
                lapses=card.lapses if card else 0,
            )
        )
    return StatsResponse(
        player_id=game_state.player_id,
        language=language,
        source=source,
        total_reviews=clock,
        letters=letters,
        timeline=timeline,
    )


def split_by_pen(packet: StrokePacket) -> list[list[StrokeSample]]:
    """Split one letter's full sample stream into individual strokes:
    contiguous runs of pen=True samples. pen=False samples (the gaps
    between strokes, or the hand moving to press submit) are dropped —
    they aren't part of any stroke's shape."""
    runs: list[list[StrokeSample]] = []
    current: list[StrokeSample] = []
    for s in packet.samples:
        if s.pen:
            current.append(s)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def pointer_strokes(packet: StrokePacket) -> list[list[tuple[float, float]]]:
    """Per-stroke paths from the gyro-based pointer reconstruction, in the
    same order as split_by_pen's runs. The wand's orientation is tracked
    through the whole letter, pen-up gaps included, so strokes keep their
    real positions relative to each other (not re-centered per stroke)."""
    points = trajectory.reconstruct_pointer_path(packet.samples, packet.sample_rate_hz)
    paths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for point, s in zip(points, packet.samples):
        if s.pen:
            current.append(point)
        elif current:
            paths.append(current)
            current = []
    if current:
        paths.append(current)
    return paths


def _reindex(samples: list[StrokeSample], sample_rate_hz: int) -> list[StrokeSample]:
    """Re-time samples on a uniform grid. Used when concatenating multiple
    pen-down runs for the whole-path CNN fallback — the original `t` values
    jump across a dropped pen-up gap, which would otherwise read as one
    huge (wrong) dt at each stroke boundary."""
    dt_ms = 1000.0 / sample_rate_hz
    return [s.model_copy(update={"t": i * dt_ms}) for i, s in enumerate(samples)]


@app.post("/stroke/live")
async def post_stroke_live(sample: LiveSample) -> dict:
    """One sample of the wand's continuous stream (see
    scripts/serial_bridge.py) - updates the live cursor tracker and
    broadcasts its new position over /ws. Display only, never scored:
    the graded result always comes from replaying the whole letter through
    /stroke once submit is pressed. Silently does nothing without gyro data
    - the pointer model needs it, and there's no accel-only fallback for a
    live cursor (unlike the final reconstruction)."""
    if sample.gx is None or sample.gy is None or sample.gz is None:
        return {}
    x, y = live_tracker.update(sample)
    await broadcast(CursorMessage(x=x, y=y, pen=sample.pen, letter_start=sample.letter_start))
    return {}


async def _persist_and_broadcast(
    result: StrokeResultMessage, per_stroke_scores, mode: str, card
) -> None:
    if db:
        try:
            await db.record(
                game_state.player_id, result.language, result.letter, result.accuracy,
                per_stroke_scores, mode, card,
            )
        except Exception as e:
            log.warning("Tiger Data write failed (attempt kept in memory): %s", e)
    await broadcast(result)


@app.post("/stroke")
async def post_stroke(packet: StrokePacket) -> ESP32FeedbackResponse:
    """The whole letter (all strokes, from first pen-down to the submit
    button press) arrives in this one call. Strict per-stroke order+
    direction validation (strokes.py) is used when the letter has a
    canonical multi-stroke definition AND the pen-down run count matches
    it. Otherwise (single-stroke letters like M/S, or a mismatched stroke
    count) falls back to the whole-path CNN (scoring.py) on the
    concatenated pen-down samples."""
    record_packet(packet)
    # The firmware no longer knows the target letter (no network to fetch it
    # over) - fall back to the round the server itself is running. A
    # non-empty value is still honored (scripts/simulate_stroke.py uses this
    # to test a specific letter regardless of the live round).
    letter = packet.letter or game_state.target_letter
    stroke_runs = split_by_pen(packet)

    expected = strokes.expected_stroke_count(letter)
    per_stroke_scores = None
    mode = "cnn"
    # Reconstruction: pointer model (gyro + accel) whenever gyro data is
    # present - see trajectory.py's docstring for why (real hardware draws
    # by rotating the wand, not moving the hand). Falls back to the older
    # accel-only double integration for packets without gyro.
    gyro_paths = pointer_strokes(packet) if trajectory.has_gyro(packet.samples) else None

    if game_state.language == "japanese":
        active_model = hiragana_model
        letter_to_index = scoring.HIRAGANA_LETTER_TO_INDEX
    else:
        active_model = latin_model or model
        letter_to_index = scoring.LETTER_TO_INDEX

    if not stroke_runs:
        accuracy = 0.0
        display_paths = []
        mode = "empty"
    elif letter.upper() in strokes.MULTI_STROKE_LETTERS and len(stroke_runs) == expected:
        mode = "strokes"
        if gyro_paths is not None:
            raw_paths = [trajectory.center(path) for path in gyro_paths]
        else:
            raw_paths = [
                trajectory.reconstruct_path(run, packet.sample_rate_hz) for run in stroke_runs
            ]
        accuracy, per_stroke_scores = strokes.validate_strokes(raw_paths, letter)
        display_paths = [
            trajectory.place_in_bbox(path, strokes.stroke_bbox(stroke))
            for path, stroke in zip(raw_paths, strokes.MULTI_STROKE_LETTERS[letter.upper()])
        ]
    elif active_model is None:
        accuracy = 0.0
        display_paths = gyro_paths if gyro_paths is not None else []
    elif gyro_paths is not None:
        accuracy = scoring.score_stroke(
            [point for path in gyro_paths for point in path],
            letter,
            active_model,
            letter_to_index=letter_to_index,
        )
        display_paths = gyro_paths
    else:
        merged = _reindex([s for run in stroke_runs for s in run], packet.sample_rate_hz)
        path = trajectory.reconstruct_path(merged, packet.sample_rate_hz)
        accuracy = scoring.score_stroke(
            path, letter, active_model, letter_to_index=letter_to_index
        )
        display_paths = [path]

    result, card = game_state.submit(letter, accuracy, display_paths, per_stroke_scores)

    # Persist then broadcast off the request path: the ESP32 gets its response
    # immediately, and the frontend's follow-up /stats fetch sees this attempt.
    task = asyncio.create_task(_persist_and_broadcast(result, per_stroke_scores, mode, card))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    return ESP32FeedbackResponse(
        score=accuracy,
        feedback_code=scoring.feedback_code(accuracy),
        round_id=result.round_id,
        cumulative_score=game_state.cumulative_score,
    )


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
