"""What the Gateway connection tells the engine. Plain Python: neither module imports discord.py, so that the engine and the adapter
work without it (and a test checks that)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GatewayEvent:
    kind: str                 # 'dispatch', 'connected' (a new session), 'resumed' (same session, nothing missed), 'disconnected'
    type: str = ""            # for a dispatch: MESSAGE_CREATE, GUILD_CREATE, ...
    data: dict | None = None


class FatalGatewayError(Exception):
    """Something that trying again will not fix (a refused token, an intent that is not allowed): the message says what to do."""
