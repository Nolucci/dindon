"""The current time, in UTC: one place for it, so that a test can replace it and the code does not repeat `datetime.now(UTC)` in twenty files."""
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_iso() -> str:
    """The current time as an ISO 8601 string (what is stored in the state of the services and sent to the interface)."""
    return utc_now().isoformat()
