"""Single-player game state. Target letters come from the SRS scheduler
(srs.py) instead of a fixed cycle. Cards and the attempt log live in memory
here, so gameplay keeps working even when Tiger Data (db.py) is unreachable;
the database is persistence + analytics, not the source of truth mid-session.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import srs
from config import DEMO_LETTERS, PLAYER_ID
from models import RoundStartMessage, StrokeResultMessage


@dataclass
class GameState:
    player_id: str = PLAYER_ID
    cards: dict[str, srs.Card] = field(default_factory=dict)
    clock: int = 0  # total reviews by this player: the SRS clock
    attempts: list[tuple[datetime, str, float]] = field(default_factory=list)
    cumulative_score: int = 0
    round_id: int = 0
    target_letter: str = DEMO_LETTERS[0]
    started_at: float = field(default_factory=time.time)

    def load(self, cards: dict[str, srs.Card], clock: int) -> None:
        self.cards = cards
        self.clock = clock

    def reset_progress(self) -> None:
        self.cards = {}
        self.clock = 0
        self.attempts = []

    def _round_start(self) -> RoundStartMessage:
        self.started_at = time.time()
        return RoundStartMessage(round_id=self.round_id, target_letter=self.target_letter)

    def start_game(self) -> RoundStartMessage:
        """Reset the session (score, round counter). SRS progress is kept."""
        self.cumulative_score = 0
        self.round_id = 0
        self.target_letter = srs.pick_next(self.cards, DEMO_LETTERS, self.clock)
        return self._round_start()

    def next_letter(self) -> RoundStartMessage:
        self.round_id += 1
        self.target_letter = srs.pick_next(
            self.cards, DEMO_LETTERS, self.clock, exclude=self.target_letter
        )
        return self._round_start()

    def submit(
        self,
        letter: str,
        accuracy: float,
        paths: list[list[tuple[float, float]]],
        per_stroke_scores: list[float] | None = None,
    ) -> tuple[StrokeResultMessage, srs.Card]:
        """Grade the attempt into the letter's SRS card, then advance."""
        letter = letter.upper()
        grade = srs.grade_from_score(accuracy)
        card = self.cards.setdefault(letter, srs.Card(letter))
        srs.review(card, grade, self.clock)
        self.clock += 1
        self.attempts.append((datetime.now(timezone.utc), letter, accuracy))

        round_id = self.round_id
        self.cumulative_score += int(accuracy)
        next_round = self.next_letter()
        result = StrokeResultMessage(
            round_id=round_id,
            letter=letter,
            accuracy=accuracy,
            grade=grade,
            next_review_in=card.due - self.clock,
            cumulative_score=self.cumulative_score,
            paths=paths,
            per_stroke_scores=per_stroke_scores,
            next_letter=next_round.target_letter,
        )
        return result, card

    def local_stats(self) -> tuple[dict[str, dict], list[dict]]:
        """Same shape as TigerStore.stats, computed from the in-memory log."""
        letters: dict[str, dict] = {}
        buckets: dict[datetime, list[float]] = {}
        for ts, letter, score in self.attempts:
            entry = letters.setdefault(
                letter, {"attempts": 0, "total": 0.0, "best_score": 0.0, "recent": []}
            )
            entry["attempts"] += 1
            entry["total"] += score
            entry["best_score"] = max(entry["best_score"], score)
            entry["recent"] = (entry["recent"] + [score])[-10:]
            buckets.setdefault(ts.replace(second=0, microsecond=0), []).append(score)

        for entry in letters.values():
            entry["avg_score"] = entry.pop("total") / entry["attempts"]

        timeline = [
            {"bucket": b, "avg_score": sum(s) / len(s), "attempts": len(s)}
            for b, s in sorted(buckets.items())
        ]
        return letters, timeline
