"""The routes of the map: servers, graph, people, state. Everything here needs the session cookie.

Names go through one expression (api/common.py: LABEL), so that a pseudonymized mode can replace them in a single place.
Roles of age or gender never come out: the only roles that leave this file are those that say an ideology (and a color never comes from an age or gender role).
"""
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from dindon.api.auth import require_session
from dindon.api.common import LABEL, iso, resolve_guild
from dindon.clock import utc_now

router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

# How much each kind of link says about a tie between two people (a reply is a conversation, a reaction a nod)
KIND_FACTOR = {"reply": 1.0, "mention": 0.6, "reaction": 0.25}

# The color of a person's name in Discord: the highest role of theirs that has a color (black is Discord's "no color"), except the
# roles of age and gender (their color would say what the role says, and those roles never come out). Only from roles that can be
# classified: the color that an export gives for a member is the one of their highest colored role *whatever it is*, so it is not
# used. Needs a guild id and a list of user ids.
MEMBER_COLORS = """
    SELECT m.user_id AS id,
           (SELECT r.color FROM member_roles mr JOIN roles r ON r.id = mr.role_id JOIN classified_roles cr ON cr.role_id = r.id
             WHERE mr.guild_id = m.guild_id AND mr.user_id = m.user_id AND r.color IS NOT NULL AND upper(r.color) <> '#000000'
               AND cr.kind NOT IN ('age', 'genre')
             ORDER BY r.position DESC, r.id LIMIT 1) AS color
    FROM members m WHERE m.guild_id = %s AND m.user_id = ANY(%s)"""
_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")

HALF_LIFE = "86400 * COALESCE((SELECT value FROM scoring_settings WHERE key = 'edge_half_life_days'), 90)::double precision"


def _utc(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _color(value: str | None) -> str | None:
    """A color as #RRGGBB, or nothing: the text comes from an export file, and no color (black) is Discord's default."""
    return value.upper() if value and _HEX_COLOR.fullmatch(value) and value != "#000000" else None


@router.get("/guilds")
def guilds(request: Request) -> list[dict]:
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            """SELECT g.id, g.name,
                      (SELECT count(*) FROM channels c WHERE c.guild_id = g.id) AS channels,
                      (SELECT count(*) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = g.id) AS messages,
                      (SELECT count(DISTINCT m.author_id) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = g.id) AS authors,
                      (SELECT max(m.sent_at) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = g.id) AS last_message_at
               FROM guilds g ORDER BY g.name"""
        ).fetchall()
    return [{**r, "id": str(r["id"]), "last_message_at": iso(r["last_message_at"])} for r in rows]


_GRAPH = f"""
WITH hl AS (SELECT {HALF_LIFE} AS s),
d AS (
    {{source}}
), pairs AS (
    SELECT least(d.f, d.t) AS a, greatest(d.f, d.t) AS b,
           sum(d.w * CASE d.kind WHEN 'reply' THEN 1.0 WHEN 'mention' THEN 0.6 ELSE 0.25 END) AS weight,
           sum(d.n) AS n, max(d.last_at) AS last_at,
           sum(d.w) FILTER (WHERE d.kind = 'reply') AS reply,
           sum(d.w) FILTER (WHERE d.kind = 'mention') AS mention,
           sum(d.w) FILTER (WHERE d.kind = 'reaction') AS reaction
    FROM d JOIN users uf ON uf.id = d.f JOIN users ut ON ut.id = d.t
    WHERE %(bots)s OR (NOT uf.is_bot AND NOT ut.is_bot)
    GROUP BY 1, 2
    HAVING sum(d.w * CASE d.kind WHEN 'reply' THEN 1.0 WHEN 'mention' THEN 0.6 ELSE 0.25 END) >= %(min_weight)s
), degree AS (
    SELECT u, sum(weight) AS influence FROM (SELECT a AS u, weight FROM pairs UNION ALL SELECT b, weight FROM pairs) x GROUP BY u
), top AS (
    SELECT u FROM degree ORDER BY influence DESC LIMIT %(limit)s
)
SELECT p.a, p.b, p.weight, p.n, p.last_at, p.reply, p.mention, p.reaction, (SELECT count(*) FROM degree) AS nodes_total,
       count(*) OVER () AS edges_total
FROM pairs p JOIN top ta ON ta.u = p.a JOIN top tb ON tb.u = p.b
ORDER BY p.weight DESC LIMIT %(max_edges)s
"""
# All the time: the links kept up to date by the ingestion, aged up to now
_ALL_TIME = """SELECT e.from_user_id AS f, e.to_user_id AS t, e.kind,
           e.weight * power(0.5::float8, GREATEST(extract(epoch FROM (%(ref)s - e.last_at)), 0) / hl.s) AS w, e.n, e.last_at
    FROM edges e, hl WHERE e.guild_id = %(guild)s AND e.kind = ANY(%(kinds)s)"""
# A period: counted again from the messages, aged up to the end of the period
_PERIOD = """SELECT i.from_user_id AS f, i.to_user_id AS t, i.kind,
           sum(power(0.5::float8, GREATEST(extract(epoch FROM (%(ref)s - i.sent_at)), 0) / hl.s)) AS w, count(*) AS n, max(i.sent_at) AS last_at
    FROM interactions i, hl
    WHERE i.guild_id = %(guild)s AND i.kind = ANY(%(kinds)s) AND i.from_user_id <> i.to_user_id
      AND i.sent_at >= %(since)s AND i.sent_at < %(until)s
    GROUP BY 1, 2, 3"""


# Filters on the messages that the links come from. Only added when asked, so that the usual map is not slowed down.
_IN_CHANNELS = " AND i.message_id IN (SELECT x.id FROM messages x WHERE x.channel_id = ANY(%(channels)s))"
_IN_THEME = """ AND EXISTS (SELECT 1 FROM conversation_messages cm JOIN topic_assignments ta ON ta.conversation_id = cm.conversation_id
                            WHERE cm.message_id = i.message_id AND ta.topic_id IN (SELECT t.id FROM topics t WHERE t.id = %(theme)s OR t.merged_into = %(theme)s))"""
# Both ends of a link have the ideology (as the role that they gave themselves)
_WITH_IDEOLOGY = """ AND d.f IN (SELECT user_id FROM claimed_ideologies WHERE guild_id = %(guild)s AND ideology_id = %(ideology)s)
                  AND d.t IN (SELECT user_id FROM claimed_ideologies WHERE guild_id = %(guild)s AND ideology_id = %(ideology)s)"""


def graph_sql(period: bool, channels: bool = False, theme: bool = False, ideology: bool = False) -> str:
    """The query of the map (also the one of the map on Discord): from the stored links, or counted again from the messages when a period, a channel or a topic
    narrows it; and, when asked, only the people who gave themselves an ideology. The parameters are named in the filters above."""
    source = (_PERIOD.replace("GROUP BY 1, 2, 3", (_IN_CHANNELS if channels else "") + (_IN_THEME if theme else "") + " GROUP BY 1, 2, 3") if period else _ALL_TIME)
    sql = _GRAPH.replace("{source}", source)
    if ideology:
        sql = sql.replace("WHERE %(bots)s OR (NOT uf.is_bot AND NOT ut.is_bot)", "WHERE (%(bots)s OR (NOT uf.is_bot AND NOT ut.is_bot))" + _WITH_IDEOLOGY)
    return sql


@router.get("/graph")
def graph(
    request: Request,
    guild: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    kinds: str = "reply,mention,reaction",
    min_weight: float = Query(0, ge=0),
    limit: int = Query(3000, ge=10, le=20000, description="most people shown (the most connected ones)"),
    max_edges: int = Query(20000, ge=10, le=100000),
    bots: bool = False,
    isolated: bool = Query(False, description="also the people who ever wrote and are not on the map: points without a link"),
    channels: str = Query("", pattern=r"^[0-9]*(,[0-9]+)*$", description="only the exchanges in these channels (ids, comma separated)"),
    theme: int | None = Query(None, description="only the exchanges of the conversations about this topic"),
    ideology: int | None = Query(None, description="only the links between people who both gave themselves this ideology"),
) -> dict:
    kind_list = [k for k in kinds.split(",") if k in KIND_FACTOR]
    if not kind_list:
        raise HTTPException(status_code=422, detail="Types d'échanges : reply, mention ou reaction.")
    since, until = _utc(since), _utc(until)
    channel_ids = [int(c) for c in channels.split(",") if c]
    narrowed = bool(channel_ids) or theme is not None          # the stored links do not know the channel or the topic: counted again from the messages
    period = since is not None or until is not None or narrowed
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        now = utc_now()
        params = {"guild": guild_id, "kinds": kind_list, "bots": bots, "min_weight": min_weight, "limit": limit, "channels": channel_ids, "theme": theme, "ideology": ideology,
                  "max_edges": max_edges, "ref": min(until, now) if until else now,
                  "since": since or datetime(1970, 1, 1, tzinfo=UTC), "until": until or datetime(2200, 1, 1, tzinfo=UTC)}
        rows = conn.execute(graph_sql(period, bool(channel_ids), theme is not None, ideology is not None), params).fetchall()
        node_ids = sorted({r["a"] for r in rows} | {r["b"] for r in rows})
        # Points without a link: whoever ever wrote in this server (not only during the period) and is not on the map. Linked
        # people come first and keep their places; these only take what is left of `limit`, the most talkative first.
        loners, loners_total = [], 0
        if isolated:
            on_map = set(node_ids)
            candidates = [r for r in conn.execute(
                """SELECT m.author_id AS id, count(*) AS messages, max(m.sent_at) AS last_at
                   FROM messages m JOIN channels c ON c.id = m.channel_id JOIN users u ON u.id = m.author_id
                   WHERE c.guild_id = %(guild)s AND (%(bots)s OR NOT u.is_bot)
                     AND (%(ideology)s::int IS NULL OR m.author_id IN (SELECT user_id FROM claimed_ideologies WHERE guild_id = %(guild)s AND ideology_id = %(ideology)s))
                     AND (cardinality(%(channels)s::bigint[]) = 0 OR m.channel_id = ANY(%(channels)s))
                   GROUP BY m.author_id ORDER BY count(*) DESC, m.author_id""", params) if r["id"] not in on_map]
            loners_total = len(candidates)
            loners = candidates[:max(limit - len(node_ids), 0)]
        labels, colors, stats = {}, {}, {}
        label_ids = node_ids + [r["id"] for r in loners]
        pictured = {r["user_id"] for r in conn.execute(                    # the people with a photo that can be shown (not the ones who asked not to be recorded)
            """SELECT m.user_id FROM members m WHERE m.guild_id = %s AND m.user_id = ANY(%s) AND m.avatar_url IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = m.user_id)""", (guild_id, label_ids))} if label_ids else set()
        if label_ids:
            for r in conn.execute(
                f"""SELECT u.id, {LABEL} AS label FROM users u LEFT JOIN members m ON m.guild_id = %s AND m.user_id = u.id
                    WHERE u.id = ANY(%s)""", (guild_id, label_ids)):
                labels[r["id"]] = r["label"]
            colors = {r["id"]: _color(r["color"]) for r in conn.execute(MEMBER_COLORS, (guild_id, label_ids))}
        if node_ids:
            for r in conn.execute(
                """SELECT m.author_id, count(*) AS messages, max(m.sent_at) AS last_at
                   FROM messages m JOIN channels c ON c.id = m.channel_id
                   WHERE c.guild_id = %(guild)s AND m.author_id = ANY(%(ids)s) AND m.sent_at >= %(since)s AND m.sent_at < %(until)s
                   GROUP BY m.author_id""", {**params, "ids": node_ids}):
                stats[r["author_id"]] = r
        half_life_days = conn.execute("SELECT value FROM scoring_settings WHERE key = 'edge_half_life_days'").fetchone()
    influence: dict[int, float] = {}
    edges = []
    for r in rows:
        influence[r["a"]] = influence.get(r["a"], 0) + r["weight"]
        influence[r["b"]] = influence.get(r["b"], 0) + r["weight"]
        edges.append({"source": str(r["a"]), "target": str(r["b"]), "weight": round(r["weight"], 4), "n": int(r["n"]),
                      "last_at": iso(r["last_at"]),
                      "kinds": {k: round(r[k], 4) for k in KIND_FACTOR if r[k]}})
    nodes = [{"id": str(uid), "label": labels.get(uid, str(uid)), "color": colors.get(uid), "influence": round(influence[uid], 4),
              "messages": stats[uid]["messages"] if uid in stats else 0,
              "last_message_at": iso(stats[uid]["last_at"]) if uid in stats else None,
              "community": None,  # filled in by the community detection (phase 5)
              "isolated": False, "avatar": f"/api/avatar/{uid}?guild={guild_id}" if uid in pictured else None}
             for uid in sorted(node_ids, key=lambda u: -influence[u])]
    nodes += [{"id": str(r["id"]), "label": labels.get(r["id"], str(r["id"])), "color": colors.get(r["id"]), "influence": 0, "messages": r["messages"],
               "last_message_at": iso(r["last_at"]), "community": None, "isolated": True,
               "avatar": f"/api/avatar/{r['id']}?guild={guild_id}" if r["id"] in pictured else None} for r in loners]
    nodes_total = rows[0]["nodes_total"] if rows else 0
    edges_total = rows[0]["edges_total"] if rows else 0
    return {"meta": {"guild": str(guild_id), "period": {"since": iso(since), "until": iso(until)} if period else None,
                     "half_life_days": float(half_life_days["value"]) if half_life_days else 90, "kind_factor": KIND_FACTOR,
                     "nodes_total": nodes_total, "nodes_shown": len(nodes), "nodes_hidden": nodes_total - len(node_ids),
                     "isolated_shown": len(loners), "isolated_hidden": loners_total - len(loners),
                     "edges_shown": len(edges), "edges_hidden": edges_total - len(edges), "generated_at": iso(utc_now())},
            "nodes": nodes, "edges": edges}


@router.get("/map/filters")
def map_filters(request: Request, guild: int | None = None) -> dict:
    """What the map can be narrowed to: the channels, the topics (when the analysis found some) and the ideologies that people gave themselves."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        channels = conn.execute(
            """SELECT c.id, c.name, count(*) AS messages FROM channels c JOIN messages m ON m.channel_id = c.id WHERE c.guild_id = %s
               GROUP BY c.id, c.name ORDER BY count(*) DESC, c.name LIMIT 300""", (guild_id,)).fetchall()
        themes = conn.execute("SELECT id, label FROM topics WHERE guild_id = %s AND status IN ('proposed', 'validated') ORDER BY label", (guild_id,)).fetchall()
        ideologies = conn.execute(
            """SELECT i.id, i.name, count(DISTINCT ci.user_id) AS people FROM claimed_ideologies ci JOIN ideologies i ON i.id = ci.ideology_id
               WHERE ci.guild_id = %s GROUP BY i.id, i.name ORDER BY count(DISTINCT ci.user_id) DESC, i.name""", (guild_id,)).fetchall()
    return {"channels": [{"id": str(r["id"]), "name": r["name"], "messages": r["messages"]} for r in channels],
            "themes": [{"id": r["id"], "label": r["label"]} for r in themes],
            "ideologies": [{"id": r["id"], "name": r["name"], "people": r["people"]} for r in ideologies]}


@router.get("/avatar/{user_id}")
def avatar(request: Request, user_id: int, guild: int | None = None) -> Response:
    """The photo of a person, fetched from Discord's CDN by the server and kept in memory (the page may only load what the application serves). Nothing for somebody who asked not to be recorded."""
    from dindon.api.activity import cached_picture

    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        row = conn.execute("""SELECT m.avatar_url FROM members m WHERE m.guild_id = %s AND m.user_id = %s
                              AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = m.user_id)""", (guild_id, user_id)).fetchone()
    if row is None or not row["avatar_url"]:
        raise HTTPException(status_code=404, detail="Pas de photo.")
    body, kind = cached_picture(guild_id, user_id, row["avatar_url"])
    return Response(body, media_type=kind, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/people")
def people(request: Request, q: str = Query("", max_length=100), guild: int | None = None, limit: int = Query(15, ge=1, le=50)) -> list[dict]:
    """Search by name, ignoring case, accents and fancy letters; the most active first."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        rows = conn.execute(
            f"""SELECT u.id, {LABEL} AS label, s.message_count
                FROM users u
                JOIN user_stats s ON s.user_id = u.id AND s.guild_id = %(guild)s
                LEFT JOIN members m ON m.guild_id = %(guild)s AND m.user_id = u.id
                WHERE NOT u.is_bot AND unaccent(lower({LABEL})) LIKE '%%' || unaccent(lower(%(q)s)) || '%%'
                ORDER BY s.message_count DESC LIMIT %(limit)s""", {"guild": guild_id, "q": q.replace("%", ""), "limit": limit}).fetchall()
    return [{"id": str(r["id"]), "label": r["label"], "messages": r["message_count"]} for r in rows]


@router.get("/person/{user_id}")
def person(request: Request, user_id: int, guild: int | None = None) -> dict:
    """The simple card of a person: who they are in this server, what they do, who they talk to."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        who = conn.execute(
            f"""SELECT u.id, {LABEL} AS label, u.name, u.global_name, m.nickname, u.is_bot FROM users u
                LEFT JOIN members m ON m.guild_id = %s AND m.user_id = u.id WHERE u.id = %s""", (guild_id, user_id)).fetchone()
        if who is None:
            raise HTTPException(status_code=404, detail="Personne inconnue.")
        activity = conn.execute(
            """SELECT count(*) AS messages, min(m.sent_at) AS first_at, max(m.sent_at) AS last_at,
                      count(DISTINCT (m.sent_at AT TIME ZONE 'UTC')::date) AS active_days, round(avg(length(m.content))) AS avg_length,
                      count(*) FILTER (WHERE m.reference_message_id IS NOT NULL) AS replies_sent,
                      count(*) FILTER (WHERE m.edited_at IS NOT NULL) AS edited, count(DISTINCT m.channel_id) AS channels
               FROM messages m JOIN channels c ON c.id = m.channel_id WHERE m.author_id = %s AND c.guild_id = %s""", (user_id, guild_id)).fetchone()
        by_month = conn.execute(
            """SELECT to_char(date_trunc('month', m.sent_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month, count(*) AS messages
               FROM messages m JOIN channels c ON c.id = m.channel_id WHERE m.author_id = %s AND c.guild_id = %s
               GROUP BY 1 ORDER BY 1 DESC LIMIT 24""", (user_id, guild_id)).fetchall()
        top_channels = conn.execute(
            """SELECT c.name, count(*) AS messages FROM messages m JOIN channels c ON c.id = m.channel_id
               WHERE m.author_id = %s AND c.guild_id = %s GROUP BY c.name ORDER BY 2 DESC LIMIT 5""", (user_id, guild_id)).fetchall()
        color = next((_color(r["color"]) for r in conn.execute(MEMBER_COLORS, (guild_id, [user_id]))), None)
        names = conn.execute(
            """SELECT value FROM identity_history WHERE user_id = %s AND guild_id IN (0, %s) ORDER BY last_seen_at DESC LIMIT 20""",
            (user_id, guild_id)).fetchall()
        links = conn.execute(
            f"""SELECT e.from_user_id, e.to_user_id, e.kind, e.n,
                       (e.weight * power(0.5::float8, GREATEST(extract(epoch FROM (now() - e.last_at)), 0) / ({HALF_LIFE})))::float8 AS w
                FROM edges e WHERE e.guild_id = %(guild)s AND (e.from_user_id = %(user)s OR e.to_user_id = %(user)s)""",
            {"guild": guild_id, "user": user_id}).fetchall()
        # Only roles that say an ideology, and only as what the person says about themselves
        roles = conn.execute(
            """SELECT cr.name AS role, i.name AS ideology FROM claimed_ideologies ci
               JOIN classified_roles cr ON cr.role_id = ci.role_id JOIN ideologies i ON i.id = ci.ideology_id
               WHERE ci.guild_id = %s AND ci.user_id = %s ORDER BY cr.name""", (guild_id, user_id)).fetchall()
        partners: dict[int, dict] = {}
        sent = {k: 0 for k in KIND_FACTOR}
        received = {k: 0 for k in KIND_FACTOR}
        for link in links:
            outgoing = link["from_user_id"] == user_id
            other = link["to_user_id"] if outgoing else link["from_user_id"]
            (sent if outgoing else received)[link["kind"]] += link["n"]
            entry = partners.setdefault(other, {"weight": 0.0, "n": 0, "kinds": {}})
            entry["weight"] += link["w"] * KIND_FACTOR[link["kind"]]
            entry["n"] += link["n"]
            entry["kinds"][link["kind"]] = entry["kinds"].get(link["kind"], 0) + link["n"]
        top = sorted(partners.items(), key=lambda kv: -kv[1]["weight"])[:10]
        partner_labels = {}
        if top:
            for r in conn.execute(
                f"""SELECT u.id, {LABEL} AS label FROM users u LEFT JOIN members m ON m.guild_id = %s AND m.user_id = u.id
                    WHERE u.id = ANY(%s)""", (guild_id, [uid for uid, _ in top])):
                partner_labels[r["id"]] = r["label"]
    days = max(activity["active_days"], 1)
    return {
        "id": str(who["id"]), "label": who["label"], "is_bot": who["is_bot"], "color": color,
        "names": {"username": who["name"], "display": who["global_name"], "nickname": who["nickname"],
                  "seen_as": sorted({n["value"] for n in names})},
        "activity": {"messages": activity["messages"], "first_message_at": iso(activity["first_at"]), "last_message_at": iso(activity["last_at"]),
                     "active_days": activity["active_days"], "messages_per_active_day": round(activity["messages"] / days, 1),
                     "average_length": int(activity["avg_length"] or 0), "channels": activity["channels"],
                     "replies_sent": activity["replies_sent"], "edited": activity["edited"],
                     "share_of_replies": round(activity["replies_sent"] / activity["messages"], 3) if activity["messages"] else 0},
        "exchanges": {"sent": sent, "received": received},
        "by_month": list(reversed(by_month)), "top_channels": top_channels,
        "top_links": [{"id": str(uid), "label": partner_labels.get(uid, str(uid)), "weight": round(e["weight"], 3), "n": e["n"], "kinds": e["kinds"]}
                      for uid, e in top],
        "claimed_roles": roles,
        "claimed_roles_note": "Rôles que la personne s'est donnés elle-même : ce n'est pas vérifié. La vérification arrive avec l'analyse des propos.",
    }


@router.get("/status")
def status(request: Request) -> dict:
    state = request.app.state
    inbox = state.settings.inbox_dir
    pending = len([p for p in inbox.glob("*.json")]) if inbox.is_dir() else 0
    failed = len(list((inbox / "failed").glob("*.json"))) if (inbox / "failed").is_dir() else 0
    with state.pool.connection() as conn:
        runs = conn.execute("SELECT count(*) AS runs, max(imported_at) AS last_at FROM ingest_runs").fetchone()
        queued = conn.execute("SELECT kind, count(*) AS n FROM jobs GROUP BY kind ORDER BY kind").fetchall()
    collector = state.collector.status() if state.collector else {"enabled": False}
    return {
        "inbox": {"pending": pending, "failed": failed},
        "ingest": {"files": runs["runs"], "last_at": iso(runs["last_at"])},
        "jobs": {r["kind"]: r["n"] for r in queued},
        "collector": collector,
        # Shown by the interface: continuous automation of a personal account is against Discord's terms of service
        "warnings": ["account_token"] if collector.get("token_kind") == "account" else [],
        "live": state.hub.listening,
    }
