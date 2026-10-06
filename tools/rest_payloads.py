"""An invented server (make_demo_server.World) as Discord's REST API would show it: users, members, roles, channels, and messages with the shape of the
objects that Discord sends. Used by the fake Discord (tools/fake_discord.py), and by tools/replay_through_bot.py's idea in the other direction: the same messages
must give the same documents whichever way they come in.

The World keeps its messages as the contract wants them (JSON v2); this turns one back into what Discord would have said: `<@id>` for a mention, `type` as a number,
`edited_timestamp`, a reply with its `referenced_message`, reactions with their emoji and count.
"""
from __future__ import annotations

from datetime import datetime

from dindon.bot.adapter import CHANNEL_KINDS, MESSAGE_KINDS

KIND_NUMBERS = {name: number for number, name in MESSAGE_KINDS.items()}
CHANNEL_NUMBERS = {name: number for number, name in CHANNEL_KINDS.items()}


def when(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def int_color(value: str | None) -> int:
    return int(value.lstrip("#"), 16) if value else 0


def user_object(person) -> dict:
    return {"id": str(person.id), "username": person.name, "discriminator": "0", "global_name": person.global_name, "avatar": None, "bot": bool(person.is_bot)}


def member_object(person) -> dict:
    return {"nick": person.nickname, "roles": [str(r) for r in person.role_ids], "avatar": None, "joined_at": "2024-01-01T00:00:00.000000+00:00", "flags": 0}


def role_object(role: dict) -> dict:
    return {"id": role["id"], "name": role["name"], "position": role.get("position", 1), "color": int_color(role.get("color")), "permissions": "0", "managed": False}


def channel_object(world, channel) -> dict:
    return {"id": str(channel.id), "type": CHANNEL_NUMBERS.get(channel.type, 0), "guild_id": str(world.guild_id), "name": channel.name,
            "parent_id": str(channel.parent_id or channel.category_id), "position": 1, "permission_overwrites": [], "flags": 0, "topic": None,
            "last_message_id": channel.last_message_id}


def category_objects(world) -> list[dict]:
    seen: dict[int, str] = {}
    for c in world.channels:
        seen.setdefault(c.category_id, c.category)
    return [{"id": str(cid), "type": 4, "guild_id": str(world.guild_id), "name": name, "parent_id": None, "position": 0, "permission_overwrites": [], "flags": 0}
            for cid, name in seen.items()]


def message_object(world, channel, entry: dict, depth: int = 0) -> dict:
    """One message of the World as Discord's REST API gives it."""
    author = world.person_by_id(entry["authorId"])
    content = entry["content"]
    mentions = []
    for uid in entry.get("mentionedUserIds", []):
        person = world.person_by_id(uid)
        name = person.display_name
        if f"@{name}" in content:
            content = content.replace(f"@{name}", f"<@{uid}>", 1)
        mentions.append(user_object(person))
    payload = {"id": entry["id"], "channel_id": str(channel.id), "type": KIND_NUMBERS.get(entry["type"], 0), "timestamp": when(entry["timestamp"]),
               "edited_timestamp": when(entry["timestampEdited"]) if "timestampEdited" in entry else None, "content": content, "author": user_object(author),
               "mentions": mentions, "mention_roles": [], "mention_everyone": False, "pinned": bool(entry.get("isPinned")), "tts": False, "flags": 0, "components": [],
               "attachments": [{"id": a["id"], "url": a["url"], "filename": a["fileName"], "size": a["fileSizeBytes"]} for a in entry.get("attachments", [])],
               "embeds": [{"type": "rich", **{k: v for k, v in e.items() if k in ("title", "url", "description")}} for e in entry.get("embeds", [])]}
    custom = world.custom_emoji["id"]
    if entry.get("reactions"):
        payload["reactions"] = [{"count": r["count"], "me": False, "emoji": {"id": r["emoji"], "name": world.custom_emoji["name"]} if r["emoji"] == custom
                                else {"id": None, "name": r["emoji"]}} for r in entry["reactions"]]
    ref = entry.get("reference")
    if ref:
        payload["message_reference"] = {"message_id": ref["messageId"], "channel_id": ref.get("channelId", str(channel.id)), "guild_id": ref.get("guildId", str(world.guild_id))}
        parent = world.msg_index.get(ref["messageId"])
        if parent and depth == 0:
            payload["referenced_message"] = message_object(world, parent[0], parent[1], depth + 1)
    return payload
