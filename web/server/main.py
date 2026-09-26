from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import config
import scoring
import strokes
import trajectory
from game_state import GameState
from models import (
    ESP32FeedbackResponse,
    RoundStartMessage,
    StrokeAckResponse,
    StrokePacket,
    StrokeReceivedMessage,
)

app = FastAPI()

game_state = GameState()
model = None
ws_clients: set[WebSocket] = set()

MODEL_PATH = Path(__file__).parent / "model" / "emnist_cnn.pt"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


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


@app.post("/stroke")
async def post_stroke(packet: StrokePacket) -> StrokeAckResponse:
    """Button 1: hold-to-draw, release-to-send. Buffers the stroke — does
    NOT score or advance the round. Scoring happens on POST /submit."""
    index = game_state.add_stroke(packet)
    expected_total = strokes.expected_stroke_count(game_state.target_letter)
    await broadcast(StrokeReceivedMessage(stroke_index=index, expected_total=expected_total))
    return StrokeAckResponse(stroke_index=index, expected_total=expected_total)


def _merge_packets(packets: list[StrokePacket]) -> StrokePacket:
    """Concatenate buffered strokes into one packet for the whole-path CNN
    fallback. Re-indexes `t` off the first packet's sample rate rather than
    trusting each packet's own `t` (which restarts near 0 per stroke) —
    otherwise trajectory._dt_array sees non-monotonic timestamps at the
    stroke boundary."""
    rate = packets[0].sample_rate_hz
    dt = 1.0 / rate
    samples = []
    i = 0
    for packet in packets:
        for s in packet.samples:
            samples.append(s.model_copy(update={"t": i * dt}))
            i += 1
    return StrokePacket(
        player_id=packets[0].player_id,
        letter=packets[0].letter,
        sample_rate_hz=rate,
        samples=samples,
    )


@app.post("/submit")
async def submit() -> ESP32FeedbackResponse:
    """Button 2: finalize the round using whatever strokes were buffered.

    Strict per-stroke order+direction validation (strokes.py) is used when
    the letter has a canonical multi-stroke definition AND the submitted
    stroke count matches it. Otherwise (single-stroke letters like M/S, or
    a mismatched stroke count) falls back to the whole-path CNN
    (scoring.py) on the concatenated strokes."""
    letter = game_state.target_letter
    pending = game_state.pending_strokes

    if not pending:
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

    if letter.upper() in strokes.MULTI_STROKE_LETTERS and len(pending) == expected:
        raw_paths = [trajectory.reconstruct_path(p) for p in pending]
        accuracy, per_stroke_scores = strokes.validate_strokes(raw_paths, letter)
        display_paths = [
            trajectory.place_in_bbox(path, strokes.stroke_bbox(stroke))
            for path, stroke in zip(raw_paths, strokes.MULTI_STROKE_LETTERS[letter.upper()])
        ]
    else:
        merged = _merge_packets(pending)
        path = trajectory.reconstruct_path(merged)
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
