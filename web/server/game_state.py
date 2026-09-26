"""Single-player game state: track current target letter and cumulative score."""

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

    def start_game(self) -> RoundStartMessage:
        """Initialize or reset the game."""
        self.cumulative_score = 0
        self.round_id = 0
        self.letter_index = 0
        self.target_letter = DEMO_LETTERS[0]
        self.started_at = time.time()
        return RoundStartMessage(round_id=self.round_id, target_letter=self.target_letter)

    def next_letter(self) -> RoundStartMessage:
        """Advance to the next target letter."""
        self.round_id += 1
        self.letter_index = (self.letter_index + 1) % len(DEMO_LETTERS)
        self.target_letter = DEMO_LETTERS[self.letter_index]
        return RoundStartMessage(round_id=self.round_id, target_letter=self.target_letter)

    def submit_stroke(
        self, packet: StrokePacket, accuracy: float, path: list[tuple[float, float]]
    ) -> StrokeResultMessage:
        """Record a stroke submission, update cumulative score, advance to next letter."""
        self.cumulative_score += int(accuracy)
        next_round = self.next_letter()
        return StrokeResultMessage(
            round_id=self.round_id - 1,
            accuracy=accuracy,
            cumulative_score=self.cumulative_score,
            path=path,
            next_letter=next_round.target_letter,
        )
