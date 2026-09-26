from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import config
import scoring
import trajectory
from game_state import GameState
from models import ESP32FeedbackResponse, RoundStartMessage, StrokePacket

app = FastAPI()

game_state = GameState()
templates: dict = {}
ws_clients: set[WebSocket] = set()

TEMPLATES_DIR = Path(__file__).parent / "templates"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.on_event("startup")
def on_startup():
    global templates
    templates = scoring.load_templates(TEMPLATES_DIR)
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
async def post_stroke(packet: StrokePacket) -> ESP32FeedbackResponse:
    accuracy = scoring.score_stroke(packet, templates)
    path = trajectory.reconstruct_path(packet)
    result = game_state.submit_stroke(packet, accuracy, path)

    await broadcast(result)

    return ESP32FeedbackResponse(
        score=accuracy,
        feedback_code=scoring.feedback_code(accuracy),
        round_id=result.round_id,
        cumulative_score=game_state.cumulative_score,
    )


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
