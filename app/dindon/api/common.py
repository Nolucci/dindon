"""What several routers of the API need: the server that a request is about, the name shown for a person, a date as text."""
from datetime import UTC, datetime

from fastapi import HTTPException

# The name shown for a person: nickname, otherwise display name, otherwise username, with fancy Unicode letters turned into plain ones (a name made of
# "mathematical" letters is unreadable on a map). Every route that names a person goes through it, so that a pseudonymized mode can replace it in one place.
# Needs u (users), m (members).
LABEL = "normalize(COALESCE(m.nickname, u.global_name, u.name), NFKC)"


def iso(value: datetime | None) -> str | None:
    """A date as ISO 8601 in UTC, for the interface; nothing for nothing."""
    return value.astimezone(UTC).isoformat() if value else None


def resolve_guild(conn, guild: int | None) -> int:
    """The server asked for, or the one that was imported most recently."""
    if guild is not None:
        if conn.execute("SELECT 1 FROM guilds WHERE id = %s", (guild,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Serveur inconnu.")
        return guild
    row = conn.execute(
        """SELECT g.id FROM guilds g
           ORDER BY (SELECT max(r.imported_at) FROM ingest_runs r WHERE r.guild_id = g.id) DESC NULLS LAST LIMIT 1"""
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Aucun serveur importé : importez d'abord un export.")
    return row["id"]
