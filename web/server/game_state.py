"""Single-player game state. Target letters come from the SRS scheduler
(srs.py) instead of a fixed cycle. Cards and the attempt log live in memory
here, so gameplay keeps working even when Tiger Data (db.py) is unreachable;
the database is persistence + analytics, not the source of truth mid-session.

Latin and Japanese are independent SRS decks — switching the active
language switches which deck is being played, but doesn't touch the other
one's cards/clock (see config.LANGUAGES).

There's exactly one physical wand, so "accounts" (players dict, below) are
about attribution, not real concurrency: switch_player() changes whose
attempts get recorded, it doesn't let two people play at once. No
passwords — this is a demo, login is just picking a known id (see
checkpoint.md).
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import srs
from config import DEFAULT_LANGUAGE, LANGUAGES, PLAYER_ID
from models import RoundStartMessage, StrokeResultMessage

# Reserved id, no password — this is a demo, not a real auth system (see
# checkpoint.md). New signups get sequential ids starting past this range.
_DEFAULT_PLAYERS: dict[int, dict] = {444: {"id": 444, "name": "Admin", "is_admin": True}}
_FIRST_SIGNUP_ID = 1000


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
    # None = practice the full deck; else restrict SRS/accuracy picking to
    # this subset (still filtered against the active language's real deck,
    # so a stale selection from a different language never wins outright).
    practice_letters: list[str] | None = None
    selection_mode: Literal["srs", "accuracy"] = "srs"
    # In-memory player registry — GameState is the source of truth (same
    # relationship as cards/attempts to db.py); Tiger Data is best-effort
    # persistence layered on top by main.py, not required for login to work.
    players: dict[int, dict] = field(default_factory=lambda: dict(_DEFAULT_PLAYERS))
    _next_player_id: int = field(default=_FIRST_SIGNUP_ID, repr=False)

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

    def _candidate_deck(self) -> list[str]:
        full = LANGUAGES[self.language].letters
        if self.practice_letters:
            filtered = [l for l in full if l in self.practice_letters]
            if filtered:
                return filtered
        return full

    def _pick_target(self, exclude: str | None = None) -> str:
        deck = self._candidate_deck()
        if self.selection_mode == "accuracy":
            stats, _ = self.local_stats(self.language)
            return srs.pick_by_accuracy(deck, stats, exclude=exclude)
        return srs.pick_next(self.cards, deck, self.clock, exclude=exclude)

    def set_practice_config(
        self, letters: list[str] | None, selection_mode: Literal["srs", "accuracy"]
    ) -> None:
        self.practice_letters = letters
        self.selection_mode = selection_mode

    def start_game(self) -> RoundStartMessage:
        """Reset the session (score, round counter). SRS progress is kept."""
        self.cumulative_score = 0
        self.round_id = 0
        self.target_letter = self._pick_target()
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
        self.target_letter = self._pick_target(exclude=self.target_letter)
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

    def create_player(self, name: str) -> dict:
        pid = self._next_player_id
        self._next_player_id += 1
        player = {"id": pid, "name": name, "is_admin": False}
        self.players[pid] = player
        return player

    def get_player(self, player_id: int) -> dict | None:
        return self.players.get(player_id)

    def list_players(self) -> list[dict]:
        return sorted(self.players.values(), key=lambda p: p["id"])

    def switch_player(self, player_id: int) -> bool:
        """Make player_id the active one for scoring/persistence. Callers
        (main.py) are responsible for reloading cards_by_language from Tiger
        Data for this player afterward — GameState itself has no db access,
        and cards_by_language is only ever populated for whichever single
        player is currently active (see the module docstring)."""
        if player_id not in self.players:
            return False
        self.player_id = str(player_id)
        self.cards_by_language = {}
        self.clock_by_language = {}
        self.attempts = []
        return True

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
