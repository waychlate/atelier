import os
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import config
import scoring
import strokes
import trajectory
from game_state import GameState
from models import ESP32FeedbackResponse, RoundStartMessage, StrokePacket, StrokeSample

app = FastAPI()

game_state = GameState()
model = None
ws_clients: set[WebSocket] = set()

MODEL_PATH = Path(__file__).parent / "model" / "emnist_cnn.pt"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

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
def on_startup():
    global model
    model = scoring.load_model(MODEL_PATH)
    game_state.start_game()


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
    msg = game_state.start_game()
    await broadcast(msg)
    return msg


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
    letter = packet.letter
    stroke_runs = split_by_pen(packet)

    if not stroke_runs:
        result = game_state.submit(accuracy=0.0, paths=[])
        await broadcast(result)
        return ESP32FeedbackResponse(
            score=0.0,
            feedback_code=scoring.feedback_code(0.0),
            round_id=result.round_id,
            cumulative_score=game_state.cumulative_score,
        )

    expected = strokes.expected_stroke_count(letter)
    per_stroke_scores = None

    if letter.upper() in strokes.MULTI_STROKE_LETTERS and len(stroke_runs) == expected:
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

    result = game_state.submit(accuracy, display_paths, per_stroke_scores)
    await broadcast(result)

    return ESP32FeedbackResponse(
        score=accuracy,
        feedback_code=scoring.feedback_code(accuracy),
        round_id=result.round_id,
        cumulative_score=game_state.cumulative_score,
    )


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
