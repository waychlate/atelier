from typing import Literal, Optional

from pydantic import BaseModel


class StrokeSample(BaseModel):
    t: float
    ax: float
    ay: float
    az: float
    gx: Optional[float] = None
    gy: Optional[float] = None
    gz: Optional[float] = None


class StrokePacket(BaseModel):
    player_id: str = "player"
    letter: str
    sample_rate_hz: int
    samples: list[StrokeSample]


class RoundStartMessage(BaseModel):
    type: Literal["round_start"] = "round_start"
    round_id: int
    target_letter: str


class StrokeResultMessage(BaseModel):
    type: Literal["stroke_result"] = "stroke_result"
    round_id: int
    accuracy: float
    cumulative_score: int
    paths: list[list[tuple[float, float]]]  # one per submitted stroke, positioned for display
    per_stroke_scores: Optional[list[float]] = None  # only for strict multi-stroke letters
    next_letter: str


class StrokeReceivedMessage(BaseModel):
    type: Literal["stroke_received"] = "stroke_received"
    stroke_index: int
    expected_total: int


class StrokeAckResponse(BaseModel):
    """Lightweight response to POST /stroke (button 1: hold-to-draw,
    release-to-send) — just an ack for the ESP32 to flash a "received"
    LED. Scoring only happens on POST /submit (button 2)."""

    received: bool = True
    stroke_index: int
    expected_total: int


class ESP32FeedbackResponse(BaseModel):
    score: float
    feedback_code: Literal["good", "ok", "bad"]
    round_id: int
    cumulative_score: int
