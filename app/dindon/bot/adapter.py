"""The Discord adapter: turns what the Gateway says into the JSON v2 documents that the ingestion already knows.

It is pure: dictionaries in, dictionaries out. It knows nothing of discord.py, of the database or of the clock, so that
it can be tested with recorded payloads, and so that the core of Dindon stays independent of Discord's library.

The contract is the one that the exporter writes (contracts/JSON-format.md), and a message must come out the same whether
it was exported or announced by the bot: otherwise the nightly catch-up would rewrite what the bot wrote, and the analysis
would later read two dialects. The mappings below therefore mirror the exporter's code (DiscordChatExporter.Core:
JsonMessageWriter, PlainTextMarkdownVisitor, MessageKind, ChannelKind, User, Member, Role, ImageCdn). The expected values
in the tests come from reading that code, not from running the exporter (see tests/test_adapter.py).

What a MESSAGE_CREATE does not carry, or what is not covered here yet (a later export or the nightly catch-up brings it):
embeds (link previews are added later by Discord through MESSAGE_UPDATE), polls, forwarded messages, and the standard
(Unicode) emoji of the text, which the exporter finds with its full emoji index. Reactions do not exist yet at creation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

# --- names, as the exporter writes them (the enums of DiscordChatExporter.Core.Discord.Data) -----------------------

MESSAGE_KINDS = {
    0: "Default", 1: "RecipientAdd", 2: "RecipientRemove", 3: "Call", 4: "ChannelNameChange", 5: "ChannelIconChange",
    6: "ChannelPinnedMessage", 7: "GuildMemberJoin", 8: "GuildBoost", 9: "GuildBoostTier1", 10: "GuildBoostTier2",
    11: "GuildBoostTier3", 12: "ChannelFollowAdd", 18: "ThreadCreated", 19: "Reply", 20: "ChatInputCommand",
    21: "ThreadStarterMessage", 22: "GuildInviteReminder", 23: "ContextMenuCommand", 24: "AutoModerationAction",
    25: "RoleSubscriptionPurchase", 26: "InteractionPremiumUpsell", 27: "StageStart", 28: "StageEnd", 29: "StageSpeaker",
    31: "StageTopic", 32: "GuildApplicationPremiumSubscription", 44: "PurchaseNotification", 46: "PollResult",
}
CHANNEL_KINDS = {
    0: "GuildTextChat", 1: "DirectTextChat", 2: "GuildVoiceChat", 3: "DirectGroupTextChat", 4: "GuildCategory", 5: "GuildNews",
    10: "GuildNewsThread", 11: "GuildPublicThread", 12: "GuildPrivateThread", 13: "GuildStageVoice", 14: "GuildDirectory",
    15: "GuildForum",
}
VOICE_CHANNELS = {2, 13}
REFERENCE_KINDS = {0: "Default", 1: "Forward"}
STICKER_FORMATS = {1: ("Png", "png"), 2: ("Apng", "png"), 3: ("Lottie", "json"), 4: ("Gif", "gif")}

# The exporter calls these "system notifications": their content is replaced by a sentence (PlainTextMessageExtensions)
SYSTEM_KINDS = set(range(1, 19)) | {46}

# Gateway events that change what the adapter knows of a server
DIRECTORY_EVENTS = frozenset({
    "GUILD_CREATE", "GUILD_UPDATE", "GUILD_DELETE", "GUILD_ROLE_CREATE", "GUILD_ROLE_UPDATE", "GUILD_ROLE_DELETE",
    "CHANNEL_CREATE", "CHANNEL_UPDATE", "CHANNEL_DELETE", "THREAD_CREATE", "THREAD_UPDATE", "THREAD_DELETE", "THREAD_LIST_SYNC",
})

_CDN = "https://cdn.discordapp.com"


# --- time -------------------------------------------------------------------------------------------------------------


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def format_time(value: datetime) -> str:
    """Always UTC, always the same shape (2025-10-21T00:38:02.164Z): milliseconds are cut, not rounded, as the exporter does."""
    value = value.astimezone(timezone.utc)
    return f"{value:%Y-%m-%dT%H:%M:%S}.{value.microsecond // 1000:03d}Z"


# --- what the adapter knows of the servers --------------------------------------------------------------------------


@dataclass
class GuildInfo:
    id: str
    name: str
    icon: str | None
    roles: dict[str, dict] = field(default_factory=dict)      # id -> role object of the Gateway
    channels: dict[str, dict] = field(default_factory=dict)   # id -> channel object (threads included)


class Directory:
    """Roles, channels and threads of the servers that Dindon follows, kept up to date from the Gateway itself (GUILD_CREATE
    at the start, then the events of roles, channels and threads). `allowed` is the list of server IDs: anything about
    another server is ignored."""

    def __init__(self, allowed: Iterable[int | str] | None = None):
        self.allowed = None if allowed is None else frozenset(str(g) for g in allowed)
        self.guilds: dict[str, GuildInfo] = {}

    def is_allowed(self, guild_id: str | int | None) -> bool:
        return guild_id is not None and (self.allowed is None or str(guild_id) in self.allowed)

    def guild(self, guild_id: str | int) -> GuildInfo | None:
        return self.guilds.get(str(guild_id))

    def channel(self, guild_id: str | int, channel_id: str | int) -> dict | None:
        guild = self.guild(guild_id)
        return guild.channels.get(str(channel_id)) if guild else None

    def apply(self, event: str, data: dict) -> bool:
        """Takes one Gateway event into account. Returns whether it concerned a server that is followed."""
        guild_id = data.get("id") if event.startswith("GUILD_") and not event.startswith("GUILD_ROLE") else data.get("guild_id")
        if not self.is_allowed(guild_id):
            return False
        gid = str(guild_id)
        if event == "GUILD_CREATE":
            info = GuildInfo(gid, data.get("name", gid), data.get("icon"))
            info.roles = {str(r["id"]): r for r in data.get("roles", [])}
            info.channels = {str(c["id"]): c for c in [*data.get("channels", []), *data.get("threads", [])]}
            self.guilds[gid] = info
        elif event == "GUILD_DELETE":
            if not data.get("unavailable"):  # an outage keeps what is known; leaving the server forgets it
                self.guilds.pop(gid, None)
        else:
            guild = self.guilds.get(gid)
            if guild is None:
                return True
            if event == "GUILD_UPDATE":
                guild.name, guild.icon = data.get("name", guild.name), data.get("icon")
                if "roles" in data:
                    guild.roles = {str(r["id"]): r for r in data["roles"]}
            elif event in ("GUILD_ROLE_CREATE", "GUILD_ROLE_UPDATE"):
                guild.roles[str(data["role"]["id"])] = data["role"]
            elif event == "GUILD_ROLE_DELETE":
                guild.roles.pop(str(data["role_id"]), None)
            elif event in ("CHANNEL_CREATE", "CHANNEL_UPDATE", "THREAD_CREATE", "THREAD_UPDATE"):
                guild.channels[str(data["id"])] = data
            elif event in ("CHANNEL_DELETE", "THREAD_DELETE"):
                guild.channels.pop(str(data["id"]), None)
            elif event == "THREAD_LIST_SYNC":
                guild.channels.update({str(t["id"]): t for t in data.get("threads", [])})
        return True


# --- the text of a message --------------------------------------------------------------------------------------------

# What the exporter's plain-text formatting recognizes, in its order (MarkdownParser.MinimalNodeMatcher): the earliest match
# wins and, at the same place, the first of the list. All the rest of the markdown is left exactly as written.
_MINIMAL = re.compile(
    r"(?P<everyone>@everyone)|(?P<here>@here)|<@!?(?P<user>[0-9]+)>|<#!?(?P<channel>[0-9]+)>|<@&(?P<role>[0-9]+)>"
    r"|<(?P<animated>a)?:(?P<emoji_name>.+?):(?P<emoji_id>[0-9]+?)>|<t:(?P<instant>-?[0-9]+)(?::(?P<style>\w))?>",
    re.MULTILINE)

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _format_instant(instant: datetime, style: str | None) -> str:
    """Date styles of Discord, written the way .NET writes them with the invariant culture, in UTC. (The exporter writes them in the
    culture and the time zone of the machine it runs on: invariant and UTC is what a container gives.)"""
    date = f"{instant:%m/%d/%Y}"
    long_date = f"{_DAYS[instant.weekday()]}, {instant.day:02d} {_MONTHS[instant.month - 1]} {instant.year:04d}"
    short_time, long_time = f"{instant:%H:%M}", f"{instant:%H:%M:%S}"
    return {"t": short_time, "T": long_time, "d": date, "D": long_date, "f": f"{long_date} {short_time}",
            "F": f"{long_date} {long_time}"}.get(style or "", f"{date} {short_time}")


@dataclass
class Names:
    """What can be put in place of a mention: users known from the message itself, roles and channels of the server."""
    users: dict[str, str]
    roles: dict[str, dict]
    channels: dict[str, dict]


def format_content(text: str, names: Names) -> str:
    def replace(match: re.Match) -> str:
        if match["everyone"] or match["here"]:
            return match[0]
        if match["user"]:
            return "@" + names.users.get(match["user"], "Unknown")
        if match["channel"]:
            channel = names.channels.get(match["channel"])
            if channel is None:
                return "#deleted-channel"
            return f"#{channel.get('name') or channel['id']}" + (" [voice]" if channel.get("type") in VOICE_CHANNELS else "")
        if match["role"]:
            role = names.roles.get(match["role"])
            return "@" + (role["name"] if role else "deleted-role")
        if match["emoji_id"]:
            return f":{match['emoji_name']}:"
        try:  # a timestamp
            instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=int(match["instant"]))
        except (OverflowError, ValueError):
            return "Invalid date"
        if match["style"] and match["style"] not in "tTdDfFrR":
            return "Invalid date"
        return _format_instant(instant, match["style"] if match["style"] not in (None, "r", "R") else None)

    return _MINIMAL.sub(replace, text)


def _display_name(user: dict, member: dict | None = None) -> str:
    """What Discord shows: the server nickname, otherwise the display name, otherwise the username."""
    return (member or {}).get("nick") or user.get("global_name") or user["username"]


def _names_of(message: dict, directory_guild: GuildInfo) -> Names:
    users = {str(message["author"]["id"]): _display_name(message["author"], message.get("member"))}
    for user in message.get("mentions", []):
        users[str(user["id"])] = _display_name(user, user.get("member"))
    return Names(users, directory_guild.roles, directory_guild.channels)


def _minutes(delta: timedelta) -> str:
    return f"{int(Decimal(delta.total_seconds() / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP)):,}"


def fallback_content(message: dict) -> str:
    """The sentence that replaces the content of a system message (PlainTextMessageExtensions.GetFallbackContent)."""
    kind = message["type"]
    content = message.get("content") or ""
    mentioned = [u for u in message.get("mentions", [])]
    first = _display_name(mentioned[0]) if mentioned else None
    if kind == 1:
        return f"Added {first} to the group." if mentioned else "Added a recipient."
    if kind == 2:
        if not mentioned:
            return "Removed a recipient."
        return "Left the group." if str(message["author"]["id"]) == str(mentioned[0]["id"]) else f"Removed {first} from the group."
    if kind == 3:
        ended = (message.get("call") or {}).get("ended_timestamp")
        lasted = _minutes(parse_time(ended) - parse_time(message["timestamp"])) if ended else "0"
        return f"Started a call that lasted {lasted} minutes."
    if kind == 4:
        return f"Changed the channel name: {content}" if content.strip() else "Changed the channel name."
    return {5: "Changed the channel icon.", 6: "Pinned a message.", 18: "Started a thread.", 7: "Joined the server.",
            46: "A poll has closed."}.get(kind, content)


def message_text(message: dict, guild: GuildInfo) -> str:
    """The `content` of a message in the contract."""
    if message["type"] in SYSTEM_KINDS:
        return fallback_content(message)
    return format_content(message.get("content") or "", _names_of(message, guild))


# --- people ---------------------------------------------------------------------------------------------------------


def _hex(color: int | None) -> str | None:
    return f"#{color & 0xFFFFFF:06X}" if color and color & 0xFFFFFF else None


def _asset(base: str, hash_: str, size: int = 512) -> str:
    return f"{base}.{'gif' if hash_.startswith('a_') else 'png'}?size={size}"


def _avatar_url(user: dict, member: dict | None, guild_id: str) -> str:
    if member and member.get("avatar"):
        return _asset(f"{_CDN}/guilds/{guild_id}/users/{user['id']}/avatars/{member['avatar']}", member["avatar"])
    if user.get("avatar"):
        return _asset(f"{_CDN}/avatars/{user['id']}/{user['avatar']}", user["avatar"])
    discriminator = _discriminator(user)
    index = discriminator % 5 if discriminator else (int(user["id"]) >> 22) % 6
    return f"{_CDN}/embed/avatars/{index}.png"


def _discriminator(user: dict) -> int:
    try:
        return int(user.get("discriminator") or 0)
    except ValueError:
        return 0


def _user_entry(user: dict, member: dict | None, guild: GuildInfo) -> dict:
    entry: dict = {"id": str(user["id"]), "name": user["username"], "discriminator": f"{_discriminator(user):04d}"}
    global_name = user.get("global_name")
    if global_name and global_name != user["username"]:
        entry["globalName"] = global_name
    if member and member.get("nick"):
        entry["nickname"] = member["nick"]
    roles = sorted((guild.roles[str(r)] for r in (member or {}).get("roles", []) if str(r) in guild.roles),
                   key=lambda r: -r.get("position", 0))  # most important first; ties keep the order given
    color = next((_hex(r.get("color")) for r in roles if _hex(r.get("color"))), None)
    if color:
        entry["color"] = color
    entry["isBot"] = bool(user.get("bot", False))
    if roles:
        entry["roleIds"] = [str(r["id"]) for r in roles]
    entry["avatarUrl"] = _avatar_url(user, member, guild.id)
    return entry


# --- the document ---------------------------------------------------------------------------------------------------


class _Tables:
    """The lookup tables of a document (users, emoji), filled as messages are read."""

    def __init__(self, guild: GuildInfo):
        self.guild = guild
        self.people: dict[str, tuple[dict, dict | None]] = {}
        self.emojis: dict[str, dict] = {}

    def user(self, user: dict, member: dict | None = None) -> str:
        uid = str(user["id"])
        known = self.people.get(uid)
        self.people[uid] = (user, member if member is not None else (known[1] if known else None))  # the latest member data wins
        return uid

    def inline_emojis(self, text: str) -> list[str]:
        keys: list[str] = []
        for match in _MINIMAL.finditer(text):
            if match["emoji_id"] and match["emoji_id"] not in keys:
                key = match["emoji_id"]
                keys.append(key)
                animated = bool(match["animated"])
                self.emojis.setdefault(key, {"id": key, "name": match["emoji_name"], "isAnimated": animated,
                                             "imageUrl": f"{_CDN}/emojis/{key}.{'gif' if animated else 'png'}"})
        return keys


def _message_entry(message: dict, tables: _Tables) -> dict:
    guild = tables.guild
    entry: dict = {"id": str(message["id"]), "type": MESSAGE_KINDS.get(message["type"], str(message["type"])),
                   "timestamp": format_time(parse_time(message["timestamp"]))}
    if message.get("edited_timestamp"):
        entry["timestampEdited"] = format_time(parse_time(message["edited_timestamp"]))
    ended = (message.get("call") or {}).get("ended_timestamp")
    if ended:
        entry["callEndedTimestamp"] = format_time(parse_time(ended))
    if message.get("pinned"):
        entry["isPinned"] = True
    entry["content"] = message_text(message, guild)
    entry["authorId"] = tables.user(message["author"], message.get("member"))
    if message.get("attachments"):
        entry["attachments"] = [{"id": str(a["id"]), "url": a["url"], "fileName": a["filename"], "fileSizeBytes": a["size"]}
                                for a in message["attachments"]]
    stickers = [{"id": str(s["id"]), "name": s["name"], "format": STICKER_FORMATS[s["format_type"]][0],
                 "sourceUrl": f"{_CDN}/stickers/{s['id']}.{STICKER_FORMATS[s['format_type']][1]}"}
                for s in message.get("sticker_items", []) if s.get("format_type") in STICKER_FORMATS]
    if stickers:
        entry["stickers"] = stickers
    if message.get("mentions"):
        entry["mentionedUserIds"] = [tables.user(u, u.get("member")) for u in message["mentions"]]
    reference = message.get("message_reference")
    if reference:
        ref: dict = {"type": REFERENCE_KINDS.get(reference.get("type", 0), str(reference.get("type")))}
        for key, name in (("message_id", "messageId"), ("channel_id", "channelId"), ("guild_id", "guildId")):
            if reference.get(key):
                ref[name] = str(reference[key])
        parent = message.get("referenced_message")
        if parent:  # who and what was replied to, even if that message is not in the database
            ref["authorId"] = tables.user(parent["author"])
            text = message_text(parent, guild)
            if text:
                ref["content"] = text
        entry["reference"] = ref
    interaction = message.get("interaction")
    if interaction:
        entry["interaction"] = {"id": str(interaction["id"]), "name": interaction["name"], "userId": tables.user(interaction["user"])}
    inline = tables.inline_emojis(message.get("content") or "")
    if inline:
        entry["inlineEmojis"] = inline
    return entry


def build_document(directory: Directory, guild_id: str | int, channel_id: str | int, messages: list[dict]) -> dict | None:
    """One JSON v2 document for the new messages of one channel. None when the server or the channel is not known: nothing is
    invented, because a made-up name would overwrite the real one (the exporter or a later event brings it).

    The document does not depend on the moment it was made: `exportedAt` is the time of the newest message, so that the same
    messages give the same document, and so that a message announced late can never look newer than a later export."""
    guild = directory.guild(guild_id)
    channel = directory.channel(guild_id, channel_id)
    if guild is None or channel is None or not messages:
        return None
    ordered = sorted(messages, key=lambda m: int(m["id"]))
    tables = _Tables(guild)
    entries = [_message_entry(m, tables) for m in ordered]

    users = [_user_entry(user, member, guild) for user, member in tables.people.values()]
    role_ids = {r for u in users for r in u.get("roleIds", [])}
    roles = sorted((guild.roles[r] for r in role_ids), key=lambda r: -r.get("position", 0))

    channel_doc: dict = {"id": str(channel["id"]), "type": CHANNEL_KINDS.get(channel["type"], str(channel["type"]))}
    parent = guild.channels.get(str(channel["parent_id"])) if channel.get("parent_id") else None
    if parent:  # as in the exporter, "category" is the parent: a category, or the channel of a thread
        channel_doc["categoryId"], channel_doc["category"] = str(parent["id"]), parent.get("name") or str(parent["id"])
    channel_doc["name"] = channel.get("name") or str(channel["id"])
    if channel.get("topic"):
        channel_doc["topic"] = channel["topic"]

    return {
        "users": users,
        "roles": [{"id": str(r["id"]), "name": r["name"], **({"color": _hex(r.get("color"))} if _hex(r.get("color")) else {}),
                   "position": r.get("position", 0)} for r in roles],
        "emojis": list(tables.emojis.values()),
        "guild": {"id": guild.id, "name": guild.name,
                  "iconUrl": _asset(f"{_CDN}/icons/{guild.id}/{guild.icon}", guild.icon) if guild.icon else f"{_CDN}/embed/avatars/0.png"},
        "channel": channel_doc,
        "exportedAt": max(e["timestamp"] for e in entries),
        "schemaVersion": 2,
        "messageCount": len(entries),
        "messages": entries,
    }


def digest(document: dict) -> str:
    """Identifies a document: the same one sent twice is recognized (and skipped) by the ingestion."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
