"""Anki-style spaced repetition (SM-2 variant).

The clock is the player's review count, not wall time: an interval of 3 means
"due again after 3 more reviews". Day-scale intervals would make spacing
invisible during a few-minute demo; review-scale keeps SM-2's behaviour
(failed letters come back soon, well-known letters drift further apart) on a
timescale you can actually watch.
"""

import random
from dataclasses import dataclass
from typing import Literal

Grade = Literal["again", "hard", "good", "easy"]

MIN_EASE = 1.3
START_EASE = 2.5
AGAIN_INTERVAL = 2  # not 1: avoid re-asking the same letter back-to-back


@dataclass
class Card:
    letter: str
    ease: float = START_EASE
    interval: float = 0.0
    reps: int = 0  # consecutive successful reviews
    lapses: int = 0
    due: int = 0  # review count at which this card is next due

    @property
    def status(self) -> str:
        if self.reps == 0:
            return "learning"
        return "review" if self.interval >= 6 else "learning"


def grade_from_score(score: float) -> Grade:
    # Thresholds line up with scoring.feedback_code: <40 "bad", 40-75 "ok".
    if score < 40:
        return "again"
    if score < 75:
        return "hard"
    if score < 95:
        return "good"
    return "easy"


def review(card: Card, grade: Grade, clock: int) -> Card:
    """Apply one review at review-count `clock`; mutates and returns card."""
    if grade == "again":
        card.lapses += 1
        card.reps = 0
        card.ease = max(MIN_EASE, card.ease - 0.2)
        card.interval = AGAIN_INTERVAL
    elif grade == "hard":
        card.ease = max(MIN_EASE, card.ease - 0.15)
        card.interval = max(AGAIN_INTERVAL, card.interval * 1.2)
        card.reps += 1
    else:
        if card.reps == 0:
            interval = 3.0
        elif card.reps == 1:
            interval = 6.0
        else:
            interval = card.interval * card.ease
        if grade == "easy":
            interval *= 1.3
            card.ease += 0.15
        card.interval = interval
        card.reps += 1

    card.due = clock + round(card.interval)
    return card


def pick_next(
    cards: dict[str, Card], deck: list[str], clock: int, exclude: str | None = None
) -> str:
    """Most-overdue card first; if nothing is due, introduce the next new
    letter from `deck`; if the deck is exhausted, take the soonest-due card
    anyway (a demo can't sit idle waiting for something to come due)."""
    candidates = [l for l in deck if l != exclude] or deck
    seen = [cards[l] for l in candidates if l in cards]

    due = [c for c in seen if c.due <= clock]
    if due:
        return min(due, key=lambda c: (c.due, c.ease)).letter

    new = [l for l in candidates if l not in cards]
    if new:
        return new[0]

    return min(seen, key=lambda c: (c.due, c.ease)).letter


def pick_by_accuracy(
    deck: list[str], stats: dict[str, dict], exclude: str | None = None
) -> str:
    """Practice mode alternative to pick_next: weight candidates by inverse
    recent accuracy instead of the SM-2 due schedule, so weaker letters come
    up more often. A letter with no attempt history yet is treated as
    maximally weak (weight 100) so new letters still surface, not just ones
    already attempted and scored low."""
    candidates = [l for l in deck if l != exclude] or deck
    weights = [max(1.0, 100.0 - stats.get(l, {}).get("avg_score", 0.0)) for l in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]
