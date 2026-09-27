"""Tiger Data (TimescaleDB) persistence: every attempt goes into the
`attempts` hypertable, SRS card state into `cards`, and progress stats are
read from the `attempt_stats_1m` continuous aggregate. Every table is keyed
by (player_id, language, letter) — Latin and Japanese decks are independent
SRS schedules, not just a label on the same one.

Gameplay never depends on this module: GameState keeps its own in-memory
copy of cards/attempts, and main.py treats every call here as best-effort
(see CLAUDE.md's "degrade gracefully on flaky venue Wi-Fi" rule).
"""

import logging

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from srs import Card

log = logging.getLogger(__name__)

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS attempts (
        ts timestamptz NOT NULL DEFAULT now(),
        player_id text NOT NULL,
        language text NOT NULL,
        letter text NOT NULL,
        score double precision NOT NULL,
        per_stroke_scores double precision[],
        mode text NOT NULL
    )
    """,
    "SELECT create_hypertable('attempts', by_range('ts'), if_not_exists => TRUE)",
    "CREATE INDEX IF NOT EXISTS attempts_player_lang_letter_ts ON attempts (player_id, language, letter, ts DESC)",
    """
    CREATE TABLE IF NOT EXISTS cards (
        player_id text NOT NULL,
        language text NOT NULL,
        letter text NOT NULL,
        ease double precision NOT NULL,
        interval double precision NOT NULL,
        reps int NOT NULL,
        lapses int NOT NULL,
        due int NOT NULL,
        PRIMARY KEY (player_id, language, letter)
    )
    """,
    # materialized_only = false: real-time aggregation, so the last minute's
    # attempts show up in charts immediately instead of after the next refresh.
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS attempt_stats_1m
    WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
    SELECT time_bucket('1 minute', ts) AS bucket, player_id, language, letter,
           avg(score) AS avg_score, max(score) AS best_score, count(*) AS attempts
    FROM attempts
    GROUP BY bucket, player_id, language, letter
    WITH NO DATA
    """,
    """
    SELECT add_continuous_aggregate_policy('attempt_stats_1m',
        start_offset => INTERVAL '30 days',
        end_offset => INTERVAL '1 minute',
        schedule_interval => INTERVAL '1 minute',
        if_not_exists => TRUE)
    """,
    # id is assigned by GameState (in-memory, source of truth), not generated
    # here — this table is just this row's persistence, same relationship as
    # attempts/cards to GameState's in-memory copies.
    """
    CREATE TABLE IF NOT EXISTS players (
        id integer PRIMARY KEY,
        name text NOT NULL,
        is_admin boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "INSERT INTO players (id, name, is_admin) VALUES (444, 'Admin', true) ON CONFLICT (id) DO NOTHING",
]


class TigerStore:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    @classmethod
    async def connect(cls, url: str, timeout: float = 10.0) -> "TigerStore":
        pool = AsyncConnectionPool(
            url, min_size=1, max_size=4, open=False, kwargs={"autocommit": True}
        )
        await pool.open(wait=True, timeout=timeout)
        store = cls(pool)
        async with pool.connection() as conn:
            for stmt in SCHEMA:
                await conn.execute(stmt)
        return store

    async def close(self) -> None:
        await self.pool.close()

    async def load(self, player_id: str, language: str) -> tuple[dict[str, Card], int]:
        """Cards plus the player's review count for this language/deck (the
        SRS clock) — Latin and Japanese progress are counted separately."""
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT letter, ease, interval, reps, lapses, due FROM cards "
                "WHERE player_id = %s AND language = %s",
                (player_id, language),
            )
            cards = {r["letter"]: Card(**r) for r in await cur.fetchall()}
            await cur.execute(
                "SELECT count(*) AS n FROM attempts WHERE player_id = %s AND language = %s",
                (player_id, language),
            )
            clock = (await cur.fetchone())["n"]
        return cards, clock

    async def record(
        self,
        player_id: str,
        language: str,
        letter: str,
        score: float,
        per_stroke_scores: list[float] | None,
        mode: str,
        card: Card,
    ) -> None:
        async with self.pool.connection(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO attempts (player_id, language, letter, score, per_stroke_scores, mode) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (player_id, language, letter, score, per_stroke_scores, mode),
                )
                await conn.execute(
                    """
                    INSERT INTO cards (player_id, language, letter, ease, interval, reps, lapses, due)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, language, letter) DO UPDATE SET
                        ease = EXCLUDED.ease, interval = EXCLUDED.interval,
                        reps = EXCLUDED.reps, lapses = EXCLUDED.lapses, due = EXCLUDED.due
                    """,
                    (
                        player_id, language, card.letter, card.ease, card.interval,
                        card.reps, card.lapses, card.due,
                    ),
                )

    async def reset_player(self, player_id: str, language: str) -> None:
        """Wipe just this player's progress in one language/deck."""
        async with self.pool.connection(timeout=5) as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM attempts WHERE player_id = %s AND language = %s",
                    (player_id, language),
                )
                await conn.execute(
                    "DELETE FROM cards WHERE player_id = %s AND language = %s",
                    (player_id, language),
                )
            # Deleted rows stay in already-materialized buckets until refreshed.
            await conn.execute("CALL refresh_continuous_aggregate('attempt_stats_1m', NULL, NULL)")

    async def stats(self, player_id: str, language: str) -> tuple[dict[str, dict], list[dict]]:
        """(per-letter aggregates, per-minute timeline) for one language."""
        async with self.pool.connection(timeout=2) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                """
                SELECT letter,
                       sum(attempts)::int AS attempts,
                       sum(avg_score * attempts) / sum(attempts) AS avg_score,
                       max(best_score) AS best_score
                FROM attempt_stats_1m
                WHERE player_id = %s AND language = %s
                GROUP BY letter
                """,
                (player_id, language),
            )
            letters = {r["letter"]: {**r, "recent": []} for r in await cur.fetchall()}

            await cur.execute(
                """
                SELECT letter, array_agg(score ORDER BY ts) AS recent
                FROM (
                    SELECT letter, score, ts,
                           row_number() OVER (PARTITION BY letter ORDER BY ts DESC) AS rn
                    FROM attempts WHERE player_id = %s AND language = %s
                ) t
                WHERE rn <= 10
                GROUP BY letter
                """,
                (player_id, language),
            )
            for r in await cur.fetchall():
                if r["letter"] in letters:
                    letters[r["letter"]]["recent"] = r["recent"]

            await cur.execute(
                """
                SELECT bucket,
                       sum(avg_score * attempts) / sum(attempts) AS avg_score,
                       sum(attempts)::int AS attempts
                FROM attempt_stats_1m
                WHERE player_id = %s AND language = %s
                GROUP BY bucket
                ORDER BY bucket
                """,
                (player_id, language),
            )
            timeline = await cur.fetchall()
        return letters, timeline

    async def create_player(self, player_id: int, name: str, is_admin: bool = False) -> None:
        async with self.pool.connection(timeout=5) as conn:
            await conn.execute(
                "INSERT INTO players (id, name, is_admin) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (player_id, name, is_admin),
            )

    async def list_players(self) -> list[dict]:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute("SELECT id, name, is_admin FROM players ORDER BY id")
            return await cur.fetchall()
