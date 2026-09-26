"""Single-player game state. Target letters come from the SRS scheduler
(srs.py) instead of a fixed cycle. Cards and the attempt log live in memory
here, so gameplay keeps working even when Tiger Data (db.py) is unreachable;
the database is persistence + analytics, not the source of truth mid-session.

Latin and Japanese are independent SRS decks — switching the active
language switches which deck is being played, but doesn't touch the other
one's cards/clock (see config.LANGUAGES).
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import srs
from config import DEFAULT_LANGUAGE, LANGUAGES, PLAYER_ID
from models import RoundStartMessage, StrokeResultMessage


@dataclass
class GameState:
    player_id: str = PLAYER_ID
    language: str = DEFAULT_LANGUAGE
    mode: str = "learn"  # "learn" (stroke hints) or "blind" (audio prompt only)
    cards_by_language: dict[str, dict[str, srs.Card]] = field(default_factory=dict)
    clock_by_language: dict[str, int] = field(default_factory=dict)
    # (ts, language, letter, score) — one row per graded attempt, all languages.
    attempts: list[tuple[datetime, str, str, float]] = field(default_factory=list)
    cumulative_score: int = 0
    round_id: int = 0
    target_letter: str = ""
    started_at: float = field(default_factory=time.time)

    @property
    def cards(self) -> dict[str, srs.Card]:
        return self.cards_by_language.setdefault(self.language, {})

    @property
    def clock(self) -> int:
        return self.clock_by_language.get(self.language, 0)

    def load(self, language: str, cards: dict[str, srs.Card], clock: int) -> None:
        self.cards_by_language[language] = cards
        self.clock_by_language[language] = clock

    def reset_progress(self, language: str | None = None) -> None:
        """Wipe SRS cards + attempt history for one language (default: the
        active one), leaving other languages' decks untouched."""
        language = language or self.language
        self.cards_by_language[language] = {}
        self.clock_by_language[language] = 0
        self.attempts = [a for a in self.attempts if a[1] != language]

    def _round_start(self) -> RoundStartMessage:
        self.started_at = time.time()
        return RoundStartMessage(
            round_id=self.round_id,
            language=self.language,
            target_letter=self.target_letter,
            mode=self.mode,
        )

    def start_game(self) -> RoundStartMessage:
        """Reset the session (score, round counter). SRS progress is kept."""
        self.cumulative_score = 0
        self.round_id = 0
        letters = LANGUAGES[self.language].letters
        self.target_letter = srs.pick_next(self.cards, letters, self.clock)
        return self._round_start()

    def set_language(self, language: str) -> RoundStartMessage:
        self.language = language
        return self.start_game()

    def set_mode(self, mode: str) -> RoundStartMessage:
        """Switch Learn/Blind. Doesn't touch score/round/SRS state — it only
        changes what hint the (already-picked) target letter gets."""
        self.mode = mode
        return self._round_start()

    def next_letter(self) -> RoundStartMessage:
        self.round_id += 1
        letters = LANGUAGES[self.language].letters
        self.target_letter = srs.pick_next(
            self.cards, letters, self.clock, exclude=self.target_letter
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
        letter = letter.upper() if letter.isascii() else letter
        language = self.language
        grade = srs.grade_from_score(accuracy)
        card = self.cards.setdefault(letter, srs.Card(letter))
        srs.review(card, grade, self.clock)
        self.clock_by_language[language] = self.clock + 1
        self.attempts.append((datetime.now(timezone.utc), language, letter, accuracy))

        round_id = self.round_id
        self.cumulative_score += int(accuracy)
        next_round = self.next_letter()
        result = StrokeResultMessage(
            round_id=round_id,
            language=language,
            mode=self.mode,
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

    def local_stats(self, language: str | None = None) -> tuple[dict[str, dict], list[dict]]:
        """Same shape as TigerStore.stats, computed from the in-memory log."""
        language = language or self.language
        letters: dict[str, dict] = {}
        buckets: dict[datetime, list[float]] = {}
        for ts, lang, letter, score in self.attempts:
            if lang != language:
                continue
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
