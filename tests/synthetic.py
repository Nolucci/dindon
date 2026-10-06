"""Builds small invented worlds in the database, for the tests. No real data, ever."""
import itertools
from datetime import datetime, timezone, UTC
from pathlib import Path

from dindon.config import Settings

_ids = itertools.count(1_000_000)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class World:
    """One guild with one channel, in which people, roles, propositions and claims are created."""

    def __init__(self, conn):
        self.conn = conn
        self.guild_id = next(_ids)
        self.channel_id = next(_ids)
        self._roles: dict[str, int] = {}
        conn.execute("INSERT INTO guilds (id, name) VALUES (%s, 'Test server')", (self.guild_id,))
        conn.execute(
            "INSERT INTO channels (id, guild_id, type, name) VALUES (%s, %s, 'GuildTextChat', 'general')",
            (self.channel_id, self.guild_id),
        )

    def person(self, name: str, roles: tuple[str, ...] = ()) -> int:
        user_id = next(_ids)
        self.conn.execute("INSERT INTO users (id, name) VALUES (%s, %s)", (user_id, name))
        self.conn.execute(
            "INSERT INTO members (guild_id, user_id, observed_at) VALUES (%s, %s, %s)",
            (self.guild_id, user_id, NOW),
        )
        for role in roles:
            if role not in self._roles:
                self._roles[role] = next(_ids)
                self.conn.execute(
                    "INSERT INTO roles (id, guild_id, name, position) VALUES (%s, %s, %s, 1)",
                    (self._roles[role], self.guild_id, role),
                )
            self.conn.execute(
                "INSERT INTO member_roles (guild_id, user_id, role_id) VALUES (%s, %s, %s)",
                (self.guild_id, user_id, self._roles[role]),
            )
        return user_id

    def proposition(self, text: str, loadings: dict[str, float]) -> int:
        prop_id = self.conn.execute(
            "INSERT INTO propositions (text) VALUES (%s) RETURNING id", (text,)
        ).fetchone()[0]
        for axis_code, loading in loadings.items():
            self.conn.execute(
                """INSERT INTO proposition_axis (proposition_id, axis_id, loading)
                   SELECT %s, id, %s FROM axes WHERE code = %s""",
                (prop_id, loading, axis_code),
            )
        return prop_id

    def claim(self, user_id: int, proposition_id: int, stance: int, confidence: float) -> int:
        """A claim with its proof: a message of the person, quoted."""
        message_id = next(_ids)
        self.conn.execute(
            """INSERT INTO messages (id, channel_id, author_id, type, sent_at, content)
               VALUES (%s, %s, %s, 'Default', %s, 'synthetic message')""",
            (message_id, self.channel_id, user_id, NOW),
        )
        claim_id = self.conn.execute(
            """INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence,
                                   stated_at, model, prompt_version)
               VALUES (%s, %s, %s, 'opinion', 'synthetic claim', %s, %s, %s, 'test', 'test') RETURNING id""",
            (self.guild_id, user_id, proposition_id, stance, confidence, NOW),
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO claim_evidence (claim_id, message_id, quote) VALUES (%s, %s, 'synthetic message')",
            (claim_id, message_id),
        )
        return claim_id

    def refresh_scores(self) -> None:
        self.conn.execute("SELECT refresh_person_axis_scores(%s)", (self.guild_id,))

    def score(self, user_id: int, axis_code: str):
        """(score, uncertainty, evidence_weight, n_propositions) as floats, or None."""
        row = self.conn.execute(
            """SELECT s.score, s.uncertainty, s.evidence_weight, s.n_propositions
               FROM person_axis_scores s JOIN axes a ON a.id = s.axis_id
               WHERE s.guild_id = %s AND s.user_id = %s AND a.code = %s""",
            (self.guild_id, user_id, axis_code),
        ).fetchone()
        return None if row is None else (float(row[0]), float(row[1]), float(row[2]), row[3])

    def verdicts(self, user_id: int) -> dict[str, str]:
        """Verdict of each ideology role that the person claims, by role name."""
        rows = self.conn.execute(
            "SELECT role_name, verdict FROM claimed_ideology_summary WHERE guild_id = %s AND user_id = %s",
            (self.guild_id, user_id),
        ).fetchall()
        return dict(rows)

    def conflicts(self, user_id: int) -> set[frozenset[str]]:
        """Pairs of ideology codes that contradict each other among the roles of a person."""
        rows = self.conn.execute(
            """SELECT DISTINCT ia.code, ib.code
               FROM claimed_ideology_conflicts c
               JOIN ideologies ia ON ia.id = c.ideology_a
               JOIN ideologies ib ON ib.id = c.ideology_b
               WHERE c.guild_id = %s AND c.user_id = %s""",
            (self.guild_id, user_id),
        ).fetchall()
        return {frozenset(r) for r in rows}


def settings_for(database_url: str, tmp_path: Path, password: str = "correct horse") -> Settings:
    """Settings for a test application: the given database, nothing from outside, folders in tmp_path."""
    return Settings(database_url=database_url, db_dir=Path(__file__).resolve().parents[1] / "db", host="127.0.0.1", port=8000,
                    ollama_url="http://127.0.0.1:9",  # nothing listens there
                    password=password, inbox_dir=tmp_path / "inbox", archive_dir=tmp_path / "archive", discord_token="", guild_ids=(),
                    discord_api_url="http://127.0.0.1:9", exporter_threads="active", poll_seconds=1,
                    catchup_hour_utc=3, catchup_days=7, web_dir=tmp_path / "no-web")
