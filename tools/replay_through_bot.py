"""Plays an invented server (JSON v2 exports) to the REAL engine of the bot, as the Gateway would announce it, then compares what the
bot wrote with the exports: the same message must come out the same, whichever way it came in.

    .venv/bin/python tools/replay_through_bot.py political/exports [--database dindon_politique_bot]

What is real: the adapter, the engine (batches, retries), the ingestion, PostgreSQL. What is simulated: Discord (no network, no discord.py
connection: the Gateway frames are built here from the export files, so the payload shapes are what the tests of the adapter assume).
A scratch database of its own is made (and kept, to look at it; pass --drop to remove it). The real data is never touched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from compare_with_export import compare  # noqa: E402
from dindon.bot.events import GatewayEvent  # noqa: E402
from dindon.bot.runner import BotRunner, Writer  # noqa: E402
from dindon.config import load_settings  # noqa: E402
from dindon.migrate import migrate  # noqa: E402

CHANNEL_TYPES = {"GuildTextChat": 0, "GuildVoiceChat": 2, "GuildCategory": 4, "GuildNews": 5}


def when(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def int_color(value: str | None) -> int:
    return int(value.lstrip("#"), 16) if value else 0


def collect(files: list[Path]):
    users, roles, channels, categories, messages, guild = {}, {}, {}, {}, [], None
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        guild = doc["guild"]
        users.update({u["id"]: u for u in doc["users"]})
        roles.update({r["id"]: r for r in doc["roles"]})
        c = doc["channel"]
        channels[c["id"]] = c
        categories[c["categoryId"]] = c["category"]
        messages += [(c["id"], m) for m in doc["messages"]]
    messages.sort(key=lambda cm: int(cm[1]["id"]))
    return guild, users, roles, channels, categories, messages


def user_object(u: dict) -> dict:
    return {"id": u["id"], "username": u["name"], "discriminator": "0", "global_name": u.get("globalName"), "avatar": None, "bot": bool(u.get("isBot"))}


def member_object(u: dict) -> dict:
    return {"nick": u.get("nickname"), "roles": list(u.get("roleIds", [])), "avatar": None, "joined_at": "2024-01-01T00:00:00.000000+00:00", "flags": 0}


def display(u: dict) -> str:
    return u.get("nickname") or u.get("globalName") or u["name"]


def payloads(guild, users, channels, messages):
    by_id: dict[str, dict] = {}
    out = []
    for channel_id, m in messages:
        author = users[m["authorId"]]
        content = m["content"]
        mentions = []
        for uid in m.get("mentionedUserIds", []):
            u = users[uid]
            if f"@{display(u)}" in content:
                content = content.replace(f"@{display(u)}", f"<@{uid}>", 1)
            mentions.append({**user_object(u), "member": member_object(u)})
        payload = {"id": m["id"], "channel_id": channel_id, "guild_id": guild["id"], "type": 0, "timestamp": when(m["timestamp"]), "edited_timestamp": None,
                   "content": content, "author": user_object(author), "member": member_object(author), "mentions": mentions, "mention_roles": [],
                   "mention_everyone": False, "attachments": [], "embeds": [], "pinned": bool(m.get("isPinned")), "tts": False, "flags": 0, "components": []}
        ref = m.get("reference")
        if ref and ref.get("messageId") in by_id:
            payload["type"] = 19
            payload["message_reference"] = {"message_id": ref["messageId"], "channel_id": channel_id, "guild_id": guild["id"]}
            payload["referenced_message"] = by_id[ref["messageId"]]
        by_id[m["id"]] = payload
        out.append(payload)
    return out


async def play(url: str, guild, users, roles, channels, categories, messages) -> dict:
    gid = guild["id"]
    guild_payload = {
        "id": gid, "name": guild["name"], "icon": None, "unavailable": False,
        "roles": [{"id": gid, "name": "@everyone", "position": 0, "color": 0, "permissions": "0", "managed": False}] + [
            {"id": r["id"], "name": r["name"], "position": r.get("position", 1), "color": int_color(r.get("color")), "permissions": "0", "managed": False}
            for r in roles.values()],
        "channels": [{"id": cid, "type": 4, "guild_id": gid, "name": name, "parent_id": None, "position": 0, "permission_overwrites": [], "flags": 0}
                     for cid, name in categories.items()] +
                    [{"id": c["id"], "type": CHANNEL_TYPES.get(c["type"], 0), "guild_id": gid, "name": c["name"], "parent_id": c.get("categoryId"), "position": 1,
                      "permission_overwrites": [], "flags": 0, "topic": None, "nsfw": False, "last_message_id": None, "rate_limit_per_user": 0}
                     for c in channels.values()],
        "threads": [],
    }
    runner = BotRunner([int(gid)], Writer(url), batch_seconds=0)
    runner.handle(GatewayEvent("dispatch", "GUILD_CREATE", guild_payload))
    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    engine = asyncio.create_task(runner.run(queue, stop))
    start = time.monotonic()
    for payload in payloads(guild, users, channels, messages):
        queue.put_nowait(GatewayEvent("dispatch", "MESSAGE_CREATE", payload))
    while not queue.empty() or runner.status()["waiting"]:
        await asyncio.sleep(0.2)
    stop.set()
    await engine
    return {**runner.status(), "seconds": round(time.monotonic() - start, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("exports", type=Path)
    parser.add_argument("--database", default="dindon_politique_bot")
    parser.add_argument("--drop", action="store_true", help="remove the scratch database at the end")
    args = parser.parse_args()
    settings = load_settings()
    base, _, _ = settings.database_url.rpartition("/")
    url = f"{base}/{args.database}"
    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{args.database}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{args.database}"')
    with psycopg.connect(url) as conn:
        migrate(conn, settings.db_dir)
    files = sorted(args.exports.glob("*.json"))
    guild, users, roles, channels, categories, messages = collect(files)
    status = asyncio.run(play(url, guild, users, roles, channels, categories, messages))
    print(f"bot engine: {status['received']} received, {status['new']} new, {status['batches']} documents, {status['rejected']} refused, "
          f"{status['dropped']} dropped, {status['skipped_unknown_channel']} unknown channel, in {status['seconds']} s")
    totals = {"compared": 0, "same": 0, "edited_since": 0}
    differences = []
    fields: dict[str, int] = {}
    with psycopg.connect(url) as conn:
        for f in files:
            r = compare(conn, json.loads(f.read_text(encoding="utf-8")))
            for k in totals:
                totals[k] += r[k]
            differences += r["differences"]
        rows = conn.execute("SELECT (SELECT count(*) FROM messages), (SELECT count(*) FROM users), (SELECT count(*) FROM member_roles), (SELECT count(*) FROM roles)").fetchone()
    # The people: the roles they wear, their names and the colour of their name, as the exports say them
    wrong_people = []
    with psycopg.connect(url) as conn:
        have_roles: dict[int, set[int]] = {}
        for uid, rid in conn.execute("SELECT user_id, role_id FROM member_roles"):
            have_roles.setdefault(uid, set()).add(rid)
        have_users = {r[0]: r[1:] for r in conn.execute("SELECT id, name, global_name FROM users")}
    seen = {m["authorId"] for _, m in messages} | {x for _, m in messages for x in m.get("mentionedUserIds", [])}   # (a reaction is not announced at creation)
    for uid, u in users.items():
        if uid not in seen:
            continue
        if int(uid) not in have_users or have_users[int(uid)] != (u["name"], u.get("globalName")):
            wrong_people.append((uid, "names"))
        elif have_roles.get(int(uid), set()) != {int(r) for r in u.get("roleIds", [])}:
            wrong_people.append((uid, "roles"))
    print(f"people: {len(users & seen) if False else len([u for u in users if u in seen])} who wrote or were mentioned, {len(wrong_people)} whose names or roles differ in the database")
    for _, field, _, _ in differences:
        fields[field] = fields.get(field, 0) + 1
    print(f"database: {rows[0]} messages, {rows[1]} people, {rows[2]} role assignments, {rows[3]} roles")
    print(f"compared with the exports: {totals['compared']} messages, {totals['same']} identical, {len({d[0] for d in differences})} different {fields or ''}; "
          f"{totals['edited_since']} edited since (not compared)")
    for mid, field, have, want in differences[:8]:
        print(f"  {mid} {field}\n     bot:    {str(have)[:90]!r}\n     export: {str(want)[:90]!r}")
    if args.drop:
        with psycopg.connect(settings.database_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{args.database}" WITH (FORCE)')
    return 1 if differences or wrong_people or status["rejected"] or status["dropped"] else 0


if __name__ == "__main__":
    sys.exit(main())
