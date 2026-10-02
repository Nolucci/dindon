"""Invented Gateway payloads, shaped like Discord's (https://discord.com/developers/docs/events/gateway-events).

Nothing here comes from a real server: names, IDs and texts are made up. The IDs are strings of digits, as on the real Gateway.
"""
from __future__ import annotations

GUILD = "100"
CATEGORY, GENERAL, VOICE, THREAD = "190", "200", "201", "210"
CITIZEN, EUROPEAN, ADMIN = "300", "302", "301"   # roles: position 1 (no color), 3 (green), 5 (red)

ALICE = {"id": "1000000000000000001", "username": "alice", "discriminator": "0", "global_name": "Alice", "avatar": "ahash", "bot": False}
BOB = {"id": "1000000000000000002", "username": "bob", "discriminator": "0", "global_name": "Bobby", "avatar": None}
CAROL = {"id": "1000000000000000003", "username": "carol", "discriminator": "0", "global_name": None, "avatar": "a_animated"}
BOT = {"id": "1000000000000000009", "username": "robot", "discriminator": "0", "global_name": None, "avatar": None}
OLD_DAVE = {"id": "1000000000000000004", "username": "dave", "discriminator": "1234", "global_name": None, "avatar": None}


def role(id: str, name: str, position: int, color: int = 0) -> dict:
    return {"id": id, "name": name, "position": position, "color": color, "permissions": "0", "managed": False}


def channel(id: str, name: str, type: int = 0, parent_id: str | None = None, topic: str | None = None, guild_id: str = GUILD) -> dict:
    return {"id": id, "type": type, "guild_id": guild_id, "name": name, "parent_id": parent_id, "topic": topic, "position": 1}


def guild_create(guild_id: str = GUILD, name: str = "Serveur test", icon: str | None = None, threads: list | None = None) -> dict:
    return {
        "id": guild_id, "name": name, "icon": icon, "unavailable": False,
        "roles": [role(guild_id, "@everyone", 0), role(CITIZEN, "Citoyen", 1), role(EUROPEAN, "Européiste", 3, 0x00FF00),
                  role(ADMIN, "Admin", 5, 0xFF0000)],
        "channels": [channel(CATEGORY, "Politique", 4), channel(GENERAL, "general", 0, CATEGORY, "Le salon principal"),
                     channel(VOICE, "Vocal", 2, CATEGORY)],
        "threads": threads if threads is not None else [channel(THREAD, "un fil", 11, GENERAL)],
    }


def member(nick: str | None = None, roles: tuple[str, ...] = (), avatar: str | None = None) -> dict:
    return {"nick": nick, "roles": list(roles), "avatar": avatar, "joined_at": "2024-01-01T00:00:00.000000+00:00", "flags": 0}


def message_create(id: int | str, content: str, author: dict = ALICE, *, channel_id: str = GENERAL, guild_id: str = GUILD,
                   timestamp: str = "2026-10-02T19:00:00.123456+00:00", type: int = 0, member_data: dict | None = ...,  # type: ignore[assignment]
                   mentions: tuple = (), reply_to: dict | None = None, referenced: dict | None = None, **extra) -> dict:
    """What MESSAGE_CREATE carries. `member_data=...` means "a plain member"; None means no member (a webhook, say)."""
    payload = {
        "id": str(id), "channel_id": channel_id, "guild_id": guild_id, "type": type, "timestamp": timestamp, "edited_timestamp": None,
        "content": content, "author": author, "member": member() if member_data is ... else member_data,
        # a mention is a user, or (user, member) when the test needs the member to say something
        "mentions": [dict(u[0], member=u[1]) if isinstance(u, tuple) else dict(u, member=member()) for u in mentions], "mention_roles": [], "mention_everyone": False,
        "attachments": [], "embeds": [], "pinned": False, "tts": False, "flags": 0, "components": [],
    }
    if reply_to is not None:
        payload["message_reference"] = {"message_id": str(reply_to["id"]), "channel_id": channel_id, "guild_id": guild_id}
        payload["referenced_message"] = referenced if referenced is not None else reply_to
        payload["type"] = 19
    payload.update(extra)
    return payload
