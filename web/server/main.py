import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import config
import scoring
import strokes
import trajectory
from db import TigerStore
from game_state import GameState
from models import (
    ESP32FeedbackResponse,
    LetterStats,
    RoundStartMessage,
    StatsResponse,
    StrokePacket,
    StrokeResultMessage,
    StrokeSample,
)

log = logging.getLogger("uvicorn.error")

app = FastAPI()

game_state = GameState()
model = None
db: TigerStore | None = None
ws_clients: set[WebSocket] = set()
background_tasks: set[asyncio.Task] = set()

MODEL_PATH = Path(__file__).parent / "model" / "emnist_cnn.pt"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
async def on_startup():
    global model, db
    model = scoring.load_model(MODEL_PATH)
    if config.DATABASE_URL:
        try:
            db = await TigerStore.connect(config.DATABASE_URL)
            cards, clock = await db.load(game_state.player_id)
            game_state.load(cards, clock)
            log.info("Tiger Data connected: %d cards, %d past reviews", len(cards), clock)
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
                round_id=game_state.round_id, target_letter=game_state.target_letter
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
        round_id=game_state.round_id, target_letter=game_state.target_letter
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


@app.post("/progress/reset")
async def reset_progress() -> RoundStartMessage:
    """Wipe SRS cards and attempt history too — start learning from scratch."""
    game_state.reset_progress()
    if db:
        try:
            await db.reset_player(game_state.player_id)
        except Exception as e:
            log.warning("Tiger Data reset failed: %s", e)
    msg = game_state.start_game()
    await broadcast(msg)
    return msg


@app.get("/stats")
async def get_stats() -> StatsResponse:
    source = "local"
    letter_aggs, timeline = game_state.local_stats()
    if db:
        try:
            letter_aggs, timeline = await db.stats(game_state.player_id)
            source = "tiger"
        except Exception as e:
            log.warning("Tiger Data stats failed, using local: %s", e)

    letters = []
    for letter in config.DEMO_LETTERS:
        agg = letter_aggs.get(letter, {})
        card = game_state.cards.get(letter)
        letters.append(
            LetterStats(
                letter=letter,
                status=card.status if card else "new",
                attempts=agg.get("attempts", 0),
                avg_score=agg.get("avg_score"),
                best_score=agg.get("best_score"),
                recent=agg.get("recent", []),
                ease=card.ease if card else None,
                due_in=card.due - game_state.clock if card else None,
                lapses=card.lapses if card else 0,
            )
        )
    return StatsResponse(
        player_id=game_state.player_id,
        source=source,
        total_reviews=game_state.clock,
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


def _reindex(samples: list[StrokeSample], sample_rate_hz: int) -> list[StrokeSample]:
    """Re-time samples on a uniform grid. Used when concatenating multiple
    pen-down runs for the whole-path CNN fallback — the original `t` values
    jump across a dropped pen-up gap, which would otherwise read as one
    huge (wrong) dt at each stroke boundary."""
    dt_ms = 1000.0 / sample_rate_hz
    return [s.model_copy(update={"t": i * dt_ms}) for i, s in enumerate(samples)]


async def _persist_and_broadcast(
    result: StrokeResultMessage, per_stroke_scores, mode: str, card
) -> None:
    if db:
        try:
            await db.record(
                game_state.player_id, result.letter, result.accuracy, per_stroke_scores, mode, card
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
    letter = packet.letter
    stroke_runs = split_by_pen(packet)

    expected = strokes.expected_stroke_count(letter)
    per_stroke_scores = None
    mode = "cnn"

    if not stroke_runs:
        accuracy = 0.0
        display_paths = []
        mode = "empty"
    elif letter.upper() in strokes.MULTI_STROKE_LETTERS and len(stroke_runs) == expected:
        mode = "strokes"
        raw_paths = [
            trajectory.reconstruct_path(run, packet.sample_rate_hz) for run in stroke_runs
        ]
        accuracy, per_stroke_scores = strokes.validate_strokes(raw_paths, letter)
        display_paths = [
            trajectory.place_in_bbox(path, strokes.stroke_bbox(stroke))
            for path, stroke in zip(raw_paths, strokes.MULTI_STROKE_LETTERS[letter.upper()])
        ]
    else:
        merged = _reindex([s for run in stroke_runs for s in run], packet.sample_rate_hz)
        path = trajectory.reconstruct_path(merged, packet.sample_rate_hz)
        accuracy = scoring.score_stroke(path, letter, model)
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
