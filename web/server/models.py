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


class LiveSample(StrokeSample):
    """One sample from the wand's continuous stream (idle included), over
    scripts/serial_bridge.py -> POST /stroke/live, for the live cursor.
    Unlike StrokeSample, `t` is the wand's millis() clock, not
    letter-relative. `letter_start` marks the first sample of a new letter
    so the frontend can clear the previous trail. `player_id` keeps two
    wands' streams apart (versus mode); older firmware omits it."""

    player_id: str = "player"
    letter_start: bool = False


class StrokePacket(BaseModel):
    """One HTTP POST covers a whole letter, not a single stroke — the
    firmware buffers from first pen-down to the submit button press and
    sends everything in one shot, pen-up gaps between strokes included.
    Individual strokes are recovered server-side by splitting on `pen`
    (see main.py's split_by_pen).

    `letter` is usually empty: the firmware no longer fetches the target
    letter (it has no network connection at all - see
    scripts/serial_bridge.py), so main.py falls back to the server's own
    game_state.target_letter. A non-empty value is still honored, which
    scripts/simulate_stroke.py relies on to test a specific letter."""

    player_id: str = "player"
    letter: str = ""
    sample_rate_hz: int
    samples: list[StrokeSample]


class RoundStartMessage(BaseModel):
    type: Literal["round_start"] = "round_start"
    round_id: int
    language: str
    target_letter: str
    mode: str = "learn"


class StrokeResultMessage(BaseModel):
    type: Literal["stroke_result"] = "stroke_result"
    round_id: int
    language: str
    mode: str
    letter: str
    accuracy: float
    grade: Literal["again", "hard", "good", "easy"]
    next_review_in: int  # reviews until this letter is due again
    cumulative_score: int
    paths: list[list[tuple[float, float]]]  # one per submitted stroke, positioned for display
    per_stroke_scores: Optional[list[float]] = None  # only for strict multi-stroke letters
    next_letter: str


class CursorMessage(BaseModel):
    """Live wand-pointing position, broadcast over /ws for every streamed
    sample - display only, never graded (see main.py's /stroke/live). x/y
    are absolute azimuth/elevation in radians; the frontend chooses where
    on screen (0, 0) sits."""

    type: Literal["cursor"] = "cursor"
    player_id: str
    x: float
    y: float
    pen: bool
    letter_start: bool


class ESP32FeedbackResponse(BaseModel):
    score: float
    feedback_code: Literal["good", "ok", "bad"]
    round_id: int
    cumulative_score: int
    # Versus only: what happened to this submission, and the player's HP.
    versus_status: Optional[str] = None
    hp: Optional[int] = None


class VersusPlayer(BaseModel):
    player_id: str
    hp: int


class VersusStateMessage(BaseModel):
    """Full versus snapshot, broadcast when a match starts, a player joins,
    or a round is won. `opens_in_ms` > 0 means the letter is shown but
    drawing it doesn't count yet (the between-rounds intermission)."""

    type: Literal["versus_state"] = "versus_state"
    round_id: int
    language: str
    letter: str
    opens_in_ms: int
    players: list[VersusPlayer]
    max_hp: int
    winner: Optional[str] = None


class VersusAttemptMessage(BaseModel):
    """One graded versus submission. status "won" is followed by a fresh
    versus_state (new letter, updated HP); "failed" locks that player out
    for retry_in_ms."""

    type: Literal["versus_attempt"] = "versus_attempt"
    player_id: str
    status: Literal["won", "failed", "locked", "stale", "waiting", "full", "over"]
    accuracy: float
    letter: str
    paths: list[list[tuple[float, float]]]
    retry_in_ms: int = 0


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
    language: str
    source: Literal["tiger", "local"]
    total_reviews: int
    letters: list[LetterStats]
    timeline: list[TimelinePoint]


class LanguageInfo(BaseModel):
    code: str
    label: str
    enabled: bool
    letter_count: int


class LanguagesResponse(BaseModel):
    active: str
    languages: list[LanguageInfo]


class ModeInfo(BaseModel):
    code: str
    label: str
    description: str
    enabled: bool


class ModesResponse(BaseModel):
    active: str
    modes: list[ModeInfo]
