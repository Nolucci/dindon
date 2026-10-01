"""Reference loader: imports one JSON export (schema version 2) into the PostgreSQL schema. It is the oracle of behavior for the real ingestion (app/dindon/ingest), which does the same by batches.

It shows how every property of the export maps to the tables, and it is idempotent: importing the
same file again does nothing, and importing a newer export of the same channel updates what changed
(edited messages, new nicknames) without duplicating anything. Row by row, so it is meant for
clarity rather than for speed; use COPY for very large imports.

    pip install "psycopg[binary]"
    DATABASE_URL=postgresql://dindon:PASSWORD@127.0.0.1:5432/dindon python load_export.py export.json [...]
"""
import hashlib, json, sys, os
from datetime import datetime
import psycopg
from psycopg.types.json import Jsonb

def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None

def load(conn, path):
    raw = open(path, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    d = json.loads(raw)
    if d.get("schemaVersion") != 2:
        raise SystemExit(f"{path}: schemaVersion {d.get('schemaVersion')} is not supported")
    exported_at = ts(d["exportedAt"])
    guild_id = int(d["guild"]["id"]); channel = d["channel"]; channel_id = int(channel["id"])
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("select id from ingest_runs where source_sha256 = %s", (sha,))
        if cur.fetchone():
            print("already imported:", os.path.basename(path)[-40:]); return False
        dr = d.get("dateRange", {})
        cur.execute("""insert into ingest_runs (source_file, source_sha256, schema_version, exported_at, guild_id, channel_id, message_count, date_after, date_before)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                    (os.path.basename(path), sha, 2, exported_at, guild_id, channel_id, d["messageCount"], ts(dr.get("after")), ts(dr.get("before"))))
        run = cur.fetchone()[0]

        cur.execute("insert into guilds (id, name, icon_url) values (%s,%s,%s) on conflict (id) do update set name=excluded.name, icon_url=excluded.icon_url",
                    (guild_id, d["guild"]["name"], d["guild"].get("iconUrl")))
        cur.execute("""insert into channels (id, guild_id, parent_id, parent_name, type, name, topic, icon_url) values (%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (id) do update set name=excluded.name, topic=excluded.topic, type=excluded.type, parent_id=excluded.parent_id, parent_name=excluded.parent_name, icon_url=excluded.icon_url""",
                    (channel_id, guild_id, int(channel["categoryId"]) if "categoryId" in channel else None, channel.get("category"),
                     channel["type"], channel["name"], channel.get("topic"), channel.get("iconUrl")))

        for r in d["roles"]:
            cur.execute("insert into roles (id, guild_id, name, color, position) values (%s,%s,%s,%s,%s) on conflict (id) do update set name=excluded.name, color=excluded.color, position=excluded.position",
                        (int(r["id"]), guild_id, r["name"], r.get("color"), r["position"]))

        for u in d["users"]:
            uid = int(u["id"])
            cur.execute("""insert into users (id, name, discriminator, global_name, is_bot, first_seen_at, last_seen_at) values (%s,%s,%s,%s,%s,%s,%s)
                           on conflict (id) do update set name=excluded.name, discriminator=excluded.discriminator, global_name=excluded.global_name,
                             is_bot=excluded.is_bot, last_seen_at=greatest(users.last_seen_at, excluded.last_seen_at)""",
                        (uid, u["name"], u["discriminator"], u.get("globalName"), u["isBot"], exported_at, exported_at))
            cur.execute("""insert into members (guild_id, user_id, nickname, color, avatar_url, observed_at) values (%s,%s,%s,%s,%s,%s)
                           on conflict (guild_id, user_id) do update set nickname=excluded.nickname, color=excluded.color, avatar_url=excluded.avatar_url, observed_at=excluded.observed_at""",
                        (guild_id, uid, u.get("nickname"), u.get("color"), u.get("avatarUrl"), exported_at))
            cur.execute("delete from member_roles where guild_id=%s and user_id=%s", (guild_id, uid))
            for rid in u.get("roleIds", []):
                cur.execute("insert into member_roles (guild_id, user_id, role_id) values (%s,%s,%s)", (guild_id, uid, int(rid)))
            for field, gid, value in (("name", 0, u["name"]), ("globalName", 0, u.get("globalName")), ("nickname", guild_id, u.get("nickname"))):
                if value:
                    cur.execute("""insert into identity_history (user_id, guild_id, field, value, first_seen_at, last_seen_at) values (%s,%s,%s,%s,%s,%s)
                                   on conflict (user_id, guild_id, field, value) do update set
                                     first_seen_at=least(identity_history.first_seen_at, excluded.first_seen_at), last_seen_at=greatest(identity_history.last_seen_at, excluded.last_seen_at)""",
                                (uid, gid, field, value, exported_at, exported_at))

        for e in d["emojis"]:
            key = e.get("id") or e["name"]
            cur.execute("insert into emojis (key, id, name, code, is_animated, image_url) values (%s,%s,%s,%s,%s,%s) on conflict (key) do update set image_url=excluded.image_url",
                        (key, int(e["id"]) if "id" in e else None, e["name"], e.get("code"), e["isAnimated"], e["imageUrl"]))

        for m in d["messages"]:
            mid = int(m["id"]); ref = m.get("reference", {}); inter = m.get("interaction", {})
            extra = {k: m[k] for k in ("embeds", "stickers", "poll", "forwardedMessage") if k in m}
            cur.execute("""insert into messages (id, channel_id, author_id, type, sent_at, edited_at, call_ended_at, is_pinned, content,
                             reference_type, reference_message_id, reference_channel_id, reference_guild_id, reference_author_id, reference_content,
                             interaction_id, interaction_name, interaction_user_id, extra, last_seen_run_id)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           on conflict (id) do update set content=excluded.content, edited_at=excluded.edited_at, is_pinned=excluded.is_pinned,
                             extra=excluded.extra, last_seen_run_id=excluded.last_seen_run_id""",
                        (mid, channel_id, int(m["authorId"]), m["type"], ts(m["timestamp"]), ts(m.get("timestampEdited")), ts(m.get("callEndedTimestamp")),
                         m.get("isPinned", False), m["content"],
                         ref.get("type"), int(ref["messageId"]) if "messageId" in ref else None, int(ref["channelId"]) if "channelId" in ref else None,
                         int(ref["guildId"]) if "guildId" in ref else None, int(ref["authorId"]) if "authorId" in ref else None, ref.get("content"),
                         int(inter["id"]) if inter else None, inter.get("name"), int(inter["userId"]) if inter else None,
                         Jsonb(extra) if extra else None, run))
            # children are replaced as a whole, so that an edited message ends up exactly as exported
            for table in ("attachments", "mentions", "message_emojis", "reactions"):
                cur.execute(f"delete from {table} where message_id=%s", (mid,))
            for a in m.get("attachments", []):
                cur.execute("insert into attachments (id, message_id, url, file_name, size_bytes) values (%s,%s,%s,%s,%s)",
                            (int(a["id"]), mid, a["url"], a["fileName"], a["fileSizeBytes"]))
            for uid in m.get("mentionedUserIds", []):
                cur.execute("insert into mentions (message_id, user_id) values (%s,%s)", (mid, int(uid)))
            for key in m.get("inlineEmojis", []):
                cur.execute("insert into message_emojis (message_id, emoji_key) values (%s,%s) on conflict do nothing", (mid, key))
            for r in m.get("reactions", []):
                cur.execute("insert into reactions (message_id, emoji_key, count) values (%s,%s,%s)", (mid, r["emoji"], r["count"]))
                for uid in r.get("userIds", []):
                    cur.execute("insert into reaction_users (message_id, emoji_key, user_id) values (%s,%s,%s)", (mid, r["emoji"], int(uid)))
    print(f"imported {len(d['messages'])} messages from {os.path.basename(path)[-45:]}")
    return True

if __name__ == "__main__":
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for p in sys.argv[1:]:
            load(conn, p)
