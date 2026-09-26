import os

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
ROUND_TIMEOUT_S = float(os.environ.get("ROUND_TIMEOUT_S", "15"))

# Tiger Data (TimescaleDB) service URL. Unset or unreachable -> in-memory only.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Single-player: must match PLAYER_ID in esp32/include/config.h.
PLAYER_ID = os.environ.get("PLAYER_ID", "player_1")

DEMO_LETTERS = ["M", "A", "T", "H", "S", "E", "G"]
