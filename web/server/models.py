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
    path: list[tuple[float, float]]
    next_letter: str


class ESP32FeedbackResponse(BaseModel):
    score: float
    feedback_code: Literal["good", "ok", "bad"]
    round_id: int
    cumulative_score: int
