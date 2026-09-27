"""Versus mode: two wands race to draw the same letter.

The first submission scoring at least PASS_ACCURACY wins the round and the
other player loses DAMAGE HP. A submission below that locks its player out
for RETRY_COOLDOWN_S (no HP lost), then they can try again. First to 0 HP
loses the match.

Players join by player_id (each wand's PLAYER_ID in esp32/include/config.h)
the first time the server hears from them - both wands stream live samples
constantly, so both join within moments of a match starting.

Separate from game_state.GameState on purpose: versus picks letters at
random rather than from the SRS scheduler, and doesn't touch anyone's SRS
cards or stats.
"""

import random
import time
from dataclasses import dataclass, field
from typing import Literal

from config import LANGUAGES
from models import VersusAttemptMessage, VersusPlayer, VersusStateMessage

START_HP = 101
DAMAGE = 20
PASS_ACCURACY = 80.0
RETRY_COOLDOWN_S = 1.0
# Gap between a round being won and the next letter going live. Matches
# RESULT_DISPLAY_MS in web/frontend/app.js, so nobody can start the next
# letter before it's on screen.
INTERMISSION_S = 2.2
MAX_PLAYERS = 2

Status = Literal["won", "failed", "locked", "stale", "waiting", "full", "over"]


@dataclass
class Player:
    player_id: str
    hp: int = START_HP
    locked_until: float = 0.0
    # When this player's in-progress letter began, from the live stream's
    # letter_start flag. None if unknown (e.g. firmware too old to tag live
    # samples with player_id) - then the stale check is skipped.
    letter_started_at: float | None = None


@dataclass
class VersusGame:
    language: str
    players: dict[str, Player] = field(default_factory=dict)
    round_id: int = 0
    letter: str = ""
    round_opens_at: float = 0.0
    winner: str | None = None

    def __post_init__(self) -> None:
        self.letter = random.choice(LANGUAGES[self.language].letters)
        self.round_opens_at = time.time()

    def join(self, player_id: str) -> Player | None:
        """The player's slot, joining them if there's room. None if the
        match already has MAX_PLAYERS other players."""
        if player_id not in self.players and len(self.players) < MAX_PLAYERS:
            self.players[player_id] = Player(player_id)
        return self.players.get(player_id)

    def note_letter_start(self, player_id: str) -> None:
        player = self.join(player_id)
        if player:
            player.letter_started_at = time.time()

    def submit(self, player_id: str, accuracy: float) -> Status:
        """Apply one graded submission. Only a "won" result changes HP or
        advances the round."""
        now = time.time()
        if self.winner:
            return "over"
        player = self.join(player_id)
        if player is None:
            return "full"
        if len(self.players) < MAX_PLAYERS:
            return "waiting"
        started = player.letter_started_at
        if now < self.round_opens_at or (started is not None and started < self.round_opens_at):
            return "stale"
        if now < player.locked_until:
            return "locked"
        if accuracy < PASS_ACCURACY:
            player.locked_until = now + RETRY_COOLDOWN_S
            return "failed"

        for other in self.players.values():
            if other is not player:
                other.hp = max(0, other.hp - DAMAGE)
                if other.hp == 0:
                    self.winner = player.player_id
        if not self.winner:
            self._next_round(now)
        return "won"

    def _next_round(self, now: float) -> None:
        self.round_id += 1
        letters = LANGUAGES[self.language].letters
        self.letter = random.choice([l for l in letters if l != self.letter] or letters)
        self.round_opens_at = now + INTERMISSION_S
        for player in self.players.values():
            player.locked_until = 0.0

    def state_message(self) -> VersusStateMessage:
        return VersusStateMessage(
            round_id=self.round_id,
            language=self.language,
            letter=self.letter,
            opens_in_ms=max(0, int((self.round_opens_at - time.time()) * 1000)),
            players=[VersusPlayer(player_id=p.player_id, hp=p.hp) for p in self.players.values()],
            max_hp=START_HP,
            winner=self.winner,
        )

    def attempt_message(
        self, player_id: str, status: Status, accuracy: float, letter: str, paths
    ) -> VersusAttemptMessage:
        return VersusAttemptMessage(
            player_id=player_id,
            status=status,
            accuracy=accuracy,
            letter=letter,
            paths=paths,
            retry_in_ms=int(RETRY_COOLDOWN_S * 1000) if status == "failed" else 0,
        )
