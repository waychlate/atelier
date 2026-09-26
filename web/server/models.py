from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class StrokeSample(BaseModel):
    t: float  # milliseconds since the letter started (firmware: uint32_t)
    ax: float
    ay: float
    az: float
    gx: Optional[float] = None
    gy: Optional[float] = None
    gz: Optional[float] = None
    pen: bool = True  # was the pen button held at this sample (mid-stroke vs. gap)


class StrokePacket(BaseModel):
    """One HTTP POST covers a whole letter, not a single stroke — the
    firmware buffers from first pen-down to the submit button press and
    sends everything in one shot, pen-up gaps between strokes included.
    Individual strokes are recovered server-side by splitting on `pen`
    (see main.py's split_by_pen)."""

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
    letter: str
    accuracy: float
    grade: Literal["again", "hard", "good", "easy"]
    next_review_in: int  # reviews until this letter is due again
    cumulative_score: int
    paths: list[list[tuple[float, float]]]  # one per submitted stroke, positioned for display
    per_stroke_scores: Optional[list[float]] = None  # only for strict multi-stroke letters
    next_letter: str


class ESP32FeedbackResponse(BaseModel):
    score: float
    feedback_code: Literal["good", "ok", "bad"]
    round_id: int
    cumulative_score: int


class LetterStats(BaseModel):
    letter: str
    status: Literal["new", "learning", "review"]
    attempts: int = 0
    avg_score: Optional[float] = None
    best_score: Optional[float] = None
    recent: list[float] = []  # last 10 scores, oldest first
    ease: Optional[float] = None
    due_in: Optional[int] = None  # reviews until due; <= 0 means due now
    lapses: int = 0


class TimelinePoint(BaseModel):
    bucket: datetime
    avg_score: float
    attempts: int


class StatsResponse(BaseModel):
    player_id: str
    source: Literal["tiger", "local"]
    total_reviews: int
    letters: list[LetterStats]
    timeline: list[TimelinePoint]
