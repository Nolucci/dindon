"""Cheap, deterministic compaction of Discord noise before any model sees a conversation.

The raw messages stay in the database for the map and privacy commands. Only the
derived analysis text is compacted. Keep this in sync with analysis_clean_text in
db/migrations/0022_analysis_compact.sql.
"""
import re

REMOVED_ACCOUNT = re.compile(r"one message removed from a suspended account\.?", re.I)
URL = re.compile(r"https?://\S+", re.I)
EMOJI = re.compile(r"<a?:\w+:\d+>")
SPACES = re.compile(r"\s+")


def clean(content: str) -> str:
    """Remove transport artefacts; never invent a summary or change a person's words."""
    text = REMOVED_ACCOUNT.sub(" ", content or "")
    text = URL.sub(" ", text)
    text = EMOJI.sub(" ", text)
    return SPACES.sub(" ", text).strip()


def distinct_messages(messages: list[str]) -> list[str]:
    """Repeated identical messages contribute once to a topic vector."""
    seen: set[str] = set()
    result = []
    for message in messages:
        key = SPACES.sub(" ", message).casefold().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(message)
    return result
