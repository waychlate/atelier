# CLAUDE.md — Air-Writing Language Game (Web/Server Side)

This file gives Claude Code context for working on the **server and frontend** for this
hackathon project. Hardware/firmware is being built separately by a teammate — this repo
only needs to consume the data contract described below, not the ESP32 code itself.

## What this project is

A 2-player language-learning game. Each player has an ESP32 with an accelerometer, LEDs, a
buzzer, and a button. Players draw a letter in the air; the device buffers motion data and
sends it here. This server scores accuracy, drives a versus-style HP/points system, and
displays both players' reconstructed drawings live on a website.

## Division of responsibility

- **Teammate (hardware/firmware):** ESP32 sensor sampling, button-triggered buffering,
  sending the data packet, receiving score feedback and driving LEDs/buzzer.
- **This repo (you):** everything from "packet arrives" onward — scoring, game state,
  WebSocket/API server, and the frontend.

Do not assume you need to touch or emulate firmware behavior beyond the data contract
below. If the contract needs to change, flag it rather than guessing at ESP32 behavior.

## Architecture

```
ESP32 (player A) --\
                     -- HTTP POST (batch) --> Server --> WebSocket --> Frontend (browser)
ESP32 (player B) --/
```

- ESP32s send **one batch per stroke** (buffered while button held, sent on release) —
  not a live stream. Don't build for low-latency per-sample streaming; it's unnecessary
  and adds complexity neither side needs.
- Server pushes round results and live path data to the frontend over WebSocket.
- Server pushes a short result (score, feedback code) back to each ESP32 over HTTP so it
  can drive its LEDs/buzzer.

## Incoming data contract (from ESP32, subject to confirmation with teammate)

Expected JSON POST body per stroke:

```json
{
  "player_id": "A",
  "letter": "M",
  "sample_rate_hz": 100,
  "samples": [
    {
      "t": 0,
      "ax": 0.12,
      "ay": -0.03,
      "az": 9.81,
      "gx": 0.0,
      "gy": 0.0,
      "gz": 0.0
    }
  ]
}
```

- `ax/ay/az`: raw accelerometer (m/s^2 or g — confirm units with teammate, don't assume).
- `gx/gy/gz`: gyro, optional — include if available, code should degrade gracefully
  without it (accel-only complementary filter fallback).
- Treat this schema as provisional — put it behind a small parsing/validation layer
  (e.g. a pydantic model) so a contract change is a one-file fix.

## Core algorithms (server-side only — nothing computed on the ESP32)

**1. Scoring — Dynamic Time Warping (DTW), not raw trajectory comparison**

- Maintain a small set of reference samples per letter (recorded ahead of time, same
  format as above).
- Score a live stroke by running DTW (`fastdtw` or similar) between its signal and each
  template for the target letter, take best/median match, normalize to a 0-100 score.
- This is more robust than reconstructing exact 2D paths and comparing shapes — accel
  double-integration drifts badly, so grade on the time-series signal itself.

**2. Path reconstruction — for display only, not for scoring**

- Double-integrate acceleration to get a rough 2D path.
- Apply drift correction: since the button marks stroke start/end, assume velocity ~= 0
  at both endpoints. Fit and subtract a linear (or quadratic) drift term per axis after
  integration so the path starts and ends at rest.
- This won't be metrically exact — that's fine, it only needs to be recognizable on
  screen. Don't over-invest in perfecting this; time is better spent on scoring accuracy
  and frontend polish.

**3. Game logic**

- Each round: server broadcasts a target letter to both players (roughly simultaneously).
- Collect both strokes, score both, convert relative score into HP delta:
  `hp_loss = k * (opponent_score - your_score)`, clamped at 0.
- Track running HP/score per player, broadcast round results + reconstructed paths to
  frontend.

## Suggested stack

- **Server:** Python, FastAPI (or Flask + Flask-SocketIO) for HTTP ingest + WebSocket
  broadcast to frontend.
- **Scoring:** `fastdtw`, `numpy`.
- **Frontend:** plain HTML/Canvas or a lightweight framework — prioritize a working
  live-drawing + HP bar view over framework sophistication. This is a demo; keep it simple
  and reliable over ambitious.

## Suggested structure

```
server/
  main.py            # FastAPI app, HTTP ingest + WebSocket endpoints
  models.py           # pydantic models for incoming stroke packets
  scoring.py          # DTW scoring against templates
  trajectory.py       # double integration + drift correction for display
  game_state.py       # round/HP/score tracking
  templates/          # recorded reference strokes per letter
frontend/
  index.html
  app.js              # WebSocket client, canvas rendering, HP bars
```

## Conventions / priorities for this hackathon

- Favor a working end-to-end slice (5-6 letters, full pipeline) over broad letter
  coverage. Get capture -> score -> HP update -> display working first, expand after.
- Don't rely on venue WiFi assumptions in code (e.g. hardcoded IPs) — read server
  host/port from config/env so it's easy to repoint on a hotspot at the venue.
- Keep the data contract and scoring logic decoupled — the contract will likely change
  once as the teammate iterates on firmware; isolate it so that's a small diff.
- No need for auth/security hardening — this is a local-network demo, not a deployed
  service.
