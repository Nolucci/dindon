"""The rules of a debate, with no database and no Discord: its limits and its vocabulary. See docs/regles-du-bot.md.

A debate has **no time limit**. It is opened from a popup where the person chooses its parameters, people take a position with a button (for / not sure / against) and write, and it ends when
somebody who may (the person who opened it, or a moderator) presses « Terminer », or by itself after a silence that the person chose in the popup.
"""
from __future__ import annotations

POSITIONS = ("for", "unsure", "against")        # the three buttons of the question: pour, ne sait pas, contre

QUIET_CHOICES = (3_600, 21_600, 86_400, 259_200, 604_800)    # the silences offered by the popup: 1 hour, 6 hours, 24 hours, 3 days, 7 days
DEFAULT_QUIET = 86_400
MAX_OPEN_PER_PERSON = 1                           # debates open at once, started by the same person
MAX_OPEN_PER_SERVER = 3                           # each open debate keeps the local AI busy, and that machine is shared
TOPIC_MIN, TOPIC_MAX = 3, 200
CONTEXT_MAX = 1_000

# Why a debate was closed (debates.close_reason)
ENDED, SILENCE, NO_PARTICIPANTS, FAILED = "ended", "silence", "no_participants", "failed"


def clean_topic(raw: str) -> str | None:
    """The subject as typed, with the spaces tidied; None when it is too short or too long to be a subject."""
    topic = " ".join(str(raw).split())
    return topic if TOPIC_MIN <= len(topic) <= TOPIC_MAX else None


def clean_context(raw: object) -> str | None:
    """What was written to frame the debate, tidied (paragraphs are kept); None when there is nothing, or too much."""
    text = "\n".join(" ".join(line.split()) for line in str(raw or "").strip().split("\n")).strip()
    return text if 0 < len(text) <= CONTEXT_MAX else None


def quiet_label(seconds: int) -> str:
    """A silence in words, for the people who read the message that opens the debate."""
    if seconds % 86_400 == 0:
        days = seconds // 86_400
        return f"{days} jour{'s' if days > 1 else ''}"
    hours = seconds // 3_600
    return f"{hours} heure{'s' if hours > 1 else ''}" if seconds % 3_600 == 0 else f"{seconds // 60} minutes"
