"""Single-player game state: track current target letter, cumulative score,
and the strokes buffered so far this round (two-button flow — button 1 adds
a stroke via add_stroke(), button 2 finalizes via submit())."""

import time
from dataclasses import dataclass, field

from config import DEMO_LETTERS
from models import StrokePacket, RoundStartMessage, StrokeResultMessage


@dataclass
class GameState:
    cumulative_score: int = 0
    round_id: int = 0
    target_letter: str = DEMO_LETTERS[0]
    letter_index: int = 0
    started_at: float = field(default_factory=time.time)
    pending_strokes: list[StrokePacket] = field(default_factory=list)

    def start_game(self) -> RoundStartMessage:
        """Initialize or reset the game."""
        self.cumulative_score = 0
        self.round_id = 0
        self.letter_index = 0
        self.target_letter = DEMO_LETTERS[0]
        self.started_at = time.time()
        self.pending_strokes = []
        return RoundStartMessage(round_id=self.round_id, target_letter=self.target_letter)

    def next_letter(self) -> RoundStartMessage:
        """Advance to the next target letter, clearing any buffered strokes."""
        self.round_id += 1
        self.letter_index = (self.letter_index + 1) % len(DEMO_LETTERS)
        self.target_letter = DEMO_LETTERS[self.letter_index]
        self.pending_strokes = []
        self.started_at = time.time()
        return RoundStartMessage(round_id=self.round_id, target_letter=self.target_letter)

    def add_stroke(self, packet: StrokePacket) -> int:
        """Buffer a stroke for the current round (button 1). Returns the
        stroke's 1-based index within this round."""
        self.pending_strokes.append(packet)
        return len(self.pending_strokes)

    def submit(
        self,
        accuracy: float,
        paths: list[list[tuple[float, float]]],
        per_stroke_scores: list[float] | None = None,
    ) -> StrokeResultMessage:
        """Finalize the round (button 2): score the buffered strokes,
        update cumulative score, advance to the next letter."""
        round_id = self.round_id
        self.cumulative_score += int(accuracy)
        next_round = self.next_letter()
        return StrokeResultMessage(
            round_id=round_id,
            accuracy=accuracy,
            cumulative_score=self.cumulative_score,
            paths=paths,
            per_stroke_scores=per_stroke_scores,
            next_letter=next_round.target_letter,
        )
