import os

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
ROUND_TIMEOUT_S = float(os.environ.get("ROUND_TIMEOUT_S", "15"))

DEMO_LETTERS = ["M", "A", "T", "H", "S", "E"]
