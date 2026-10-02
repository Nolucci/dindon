"""Discord ids carry the time at which they were made."""
from datetime import datetime, timezone

DISCORD_EPOCH_MS = 1_420_070_400_000


def snowflake_at(when: datetime) -> int:
    """The message id that corresponds to a date: everything sent after `when` has a larger id."""
    return (int(when.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22


def created_at(snowflake: int) -> datetime:
    return datetime.fromtimestamp(((snowflake >> 22) + DISCORD_EPOCH_MS) / 1000, tz=timezone.utc)
