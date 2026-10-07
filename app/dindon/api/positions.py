"""What the AI read of each person: their positions on propositions, each with the proof (the quote and its message). Everything needs
the session cookie. A position is the latest one of the person on a proposition (`current_stances`); earlier ones stay in `claims`.

Nothing here is a verdict on a person: it is what a model read, with the quote that the code checked, to be read and judged by a person.
The propositions are the model's, *proposed*: they are not validated by anything.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dindon.analysis.extraction import PROMPT_VERSION
from dindon.api.auth import require_session
from dindon.api.common import LABEL, iso, resolve_guild

router = APIRouter(prefix="/api/positions", dependencies=[Depends(require_session)])


def fold_text(text: str) -> str:
    """Case, accents and fancy letters ignored (the same as the search of people)."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)).casefold()

QUOTE_CHARS = 280


def _evidence(conn, claim_ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if not claim_ids:
        return out
    for r in conn.execute(
            """SELECT e.claim_id, e.quote, m.id AS message_id, m.sent_at, c.name AS channel FROM claim_evidence e
               JOIN messages m ON m.id = e.message_id JOIN channels c ON c.id = m.channel_id
               WHERE e.claim_id = ANY(%s) ORDER BY m.sent_at, m.id""", (claim_ids,)):
        out.setdefault(r["claim_id"], []).append({"message_id": str(r["message_id"]), "quote": (r["quote"] or "")[:QUOTE_CHARS], "at": iso(r["sent_at"]),
                                                  "channel": r["channel"]})
    return out


@router.get("")
def overview(request: Request, guild: int | None = None, limit: int = Query(250, ge=1, le=500), q: str = Query("", max_length=100),
             theme: int | None = None, sort: str = Query("people", pattern="^(people|divided|recent)$"), stance: str = Query("", pattern="^(|for|against|nuanced)$"),
             rejected: bool = False) -> dict:
    """How much was read, and the propositions with how many people are for, nuanced, against.

    Filters: `q` (words of the proposition, or the name of a person who takes a position on it), `theme`, `stance` (only the propositions where somebody is
    for / against / nuanced), `sort` (most people, most divided, most recent)."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        done = conn.execute(
            """SELECT count(*) FILTER (WHERE c.kept) AS kept,
                      count(*) FILTER (WHERE c.kept AND EXISTS (SELECT 1 FROM conversation_extractions x WHERE x.conversation_id = c.id)) AS read
               FROM conversations c JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s""", (guild_id,)).fetchone()
        totals = conn.execute(
            """SELECT count(*) AS claims, count(*) FILTER (WHERE stance IS NOT NULL) AS positions, count(DISTINCT user_id) AS people
               FROM claims WHERE guild_id = %s AND review_status <> 'rejected'""", (guild_id,)).fetchone()
        refused = conn.execute(
            """SELECT coalesce(sum(x.refused), 0) AS refused FROM conversation_extractions x JOIN conversations c ON c.id = x.conversation_id
               JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s""", (guild_id,)).fetchone()["refused"]
        # The theme of a proposition: the one where most of the conversations that it was read in were put (a merged theme counts for the one it joined)
        words = [w for w in q.replace("%", " ").replace("_", " ").split() if w]
        props = conn.execute(
            """SELECT p.id, p.text, p.status, count(*) AS people, count(*) FILTER (WHERE s.stance = 1) AS pour,
                      count(*) FILTER (WHERE s.stance = 0) AS nuance, count(*) FILTER (WHERE s.stance = -1) AS contre,
                      th.topic_id, tt.label AS theme, max(s.stated_at) AS last_at
               FROM current_stances s JOIN propositions p ON p.id = s.proposition_id
               LEFT JOIN LATERAL (
                   SELECT COALESCE(t.merged_into, t.id) AS topic_id FROM claims c
                   JOIN topic_assignments a ON a.conversation_id = c.conversation_id JOIN topics t ON t.id = a.topic_id
                   WHERE c.proposition_id = p.id GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1) th ON true
               LEFT JOIN topics tt ON tt.id = th.topic_id
               WHERE s.guild_id = %(guild)s AND p.status <> 'merged' AND (p.status <> 'rejected' OR %(rejected)s)
               GROUP BY p.id, th.topic_id, tt.label""", {"guild": guild_id, "rejected": rejected}).fetchall()
        named: dict[str, set[int]] = {}
        if words:                                           # the people whose name has the word: the propositions they take a position on
            for w in set(words):
                named[w] = {r["proposition_id"] for r in conn.execute(
                    f"""SELECT DISTINCT s.proposition_id FROM current_stances s JOIN users u ON u.id = s.user_id
                        LEFT JOIN members m ON m.guild_id = s.guild_id AND m.user_id = u.id
                        WHERE s.guild_id = %s AND unaccent(lower({LABEL})) LIKE '%%' || unaccent(lower(%s)) || '%%'""", (guild_id, w)).fetchall()}
        themes_all: dict[int, dict] = {}
        for r in props:
            t = themes_all.setdefault(r["topic_id"] or 0, {"id": r["topic_id"], "label": r["theme"] or "Sans thème", "propositions": 0})
            t["propositions"] += 1
        n_props = len(props)
    def keep(r) -> bool:
        if theme is not None and (r["topic_id"] or 0) != theme:
            return False
        if stance and not r[{"for": "pour", "against": "contre", "nuanced": "nuance"}[stance]]:
            return False
        text = fold_text(r["text"])
        return all(fold_text(w) in text or r["id"] in named.get(w, ()) for w in words)

    kept = [r for r in props if keep(r)]
    key = {"people": lambda r: (-r["people"], r["id"]),
           "divided": lambda r: (-(min(r["pour"], r["contre"]) * 2 + r["nuance"]), -r["people"], r["id"]),
           "recent": lambda r: (-r["last_at"].timestamp(), r["id"])}[sort]
    kept.sort(key=key)
    props = kept[:limit]
    with request.app.state.pool.connection() as conn:
        catalog = [{"code": r["code"], "name": r["name"], "negative_pole": r["negative_pole"], "positive_pole": r["positive_pole"]}
                   for r in conn.execute("SELECT code, name, negative_pole, positive_pole FROM axes WHERE is_active ORDER BY position").fetchall()]
        links = conn.execute("""SELECT count(*) AS total, count(*) FILTER (WHERE pa.is_validated) AS validated FROM proposition_axis pa
                                JOIN axes a ON a.id = pa.axis_id AND a.is_active
                                WHERE pa.proposition_id IN (SELECT proposition_id FROM claims WHERE guild_id = %s AND proposition_id IS NOT NULL)""", (guild_id,)).fetchone()
        only = conn.execute("SELECT value FROM scoring_settings WHERE key = 'only_validated_loadings'").fetchone()
    return {"guild": str(guild_id), "prompt_version": PROMPT_VERSION, "matching": len(kept), "axes_catalog": catalog,
            "axes_links": {"total": links["total"], "validated": links["validated"], "only_validated": bool(only and only["value"])},
            "themes": sorted(themes_all.values(), key=lambda t: -t["propositions"]),
            "conversations": {"kept": done["kept"], "read": done["read"]},
            "claims": {"total": totals["claims"], "positions": totals["positions"], "people": totals["people"], "refused": int(refused)},
            "propositions_total": n_props,
            "propositions": [{"id": p["id"], "text": p["text"], "status": p["status"], "people": p["people"], "for": p["pour"], "nuanced": p["nuance"],
                              "against": p["contre"], "theme": p["theme"], "theme_id": p["topic_id"]} for p in props]}


class PropositionReview(BaseModel):
    rejected: bool


@router.patch("/proposition/{proposition_id}")
def review_proposition(request: Request, proposition_id: int, body: PropositionReview, guild: int | None = None) -> dict:
    """Keep a bad AI proposal out of the results and scores; allow a person to restore it."""
    with request.app.state.pool.connection() as conn, conn.transaction():
        guild_id = resolve_guild(conn, guild)
        other = conn.execute("SELECT 1 FROM claims WHERE proposition_id = %s AND guild_id <> %s LIMIT 1", (proposition_id, guild_id)).fetchone()
        if other is not None:
            raise HTTPException(status_code=409, detail="Cette proposition est aussi utilisée par un autre serveur ; corrigez ses liens aux axes ici.")
        row = conn.execute("""UPDATE propositions SET status = %s WHERE id = %s AND status IN ('proposed', 'rejected')
                              AND EXISTS (SELECT 1 FROM claims WHERE guild_id = %s AND proposition_id = %s)
                              RETURNING status""", ('rejected' if body.rejected else 'proposed', proposition_id, guild_id, proposition_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="proposition inconnue ou déjà validée")
        conn.execute("SELECT refresh_person_axis_scores(%s)", (guild_id,))
        return {"id": proposition_id, "status": row["status"]}


def _links(conn, proposition_id: int) -> list[dict]:
    """The axes that agreeing with a proposition moves someone on: which pole it moves toward, how much, and whether a person validated it."""
    return [{"axis": r["code"], "name": r["name"], "negative_pole": r["negative_pole"], "positive_pole": r["positive_pole"], "loading": float(r["loading"]),
             "toward": r["positive_pole"] if r["loading"] > 0 else r["negative_pole"], "validated": r["is_validated"], "active": r["is_active"]}
            for r in conn.execute(
                """SELECT a.code, a.name, a.negative_pole, a.positive_pole, a.is_active, pa.loading, pa.is_validated FROM proposition_axis pa
                   JOIN axes a ON a.id = pa.axis_id WHERE pa.proposition_id = %s ORDER BY abs(pa.loading) DESC, a.position""", (proposition_id,))]


class AxisLink(BaseModel):
    axis: str = Field(max_length=40)
    loading: float = Field(ge=-1, le=1)


class AxisLinks(BaseModel):
    links: list[AxisLink] = Field(max_length=6)


@router.put("/proposition/{proposition_id}/axes")
def set_links(request: Request, proposition_id: int, body: AxisLinks, guild: int | None = None) -> dict:
    """A person says which axes a proposition moves someone on, and how (-1 toward the negative pole, +1 toward the positive one): the links are replaced by
    these, **validated**, and the scores of the server are computed again. An empty list is also a decision: this proposition weighs on no axis."""
    with request.app.state.pool.connection() as conn, conn.transaction():
        guild_id = resolve_guild(conn, guild)
        if conn.execute("SELECT 1 FROM propositions WHERE id = %s", (proposition_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="proposition inconnue")
        ids = {r["code"]: r["id"] for r in conn.execute("SELECT code, id FROM axes WHERE is_active").fetchall()}
        wanted = {}
        for link in body.links:
            if link.axis not in ids:
                raise HTTPException(status_code=422, detail=f"axe inconnu ou inactif : {link.axis}")
            if abs(link.loading) >= 0.3:
                wanted[link.axis] = round(link.loading, 2)
        conn.execute("DELETE FROM proposition_axis WHERE proposition_id = %s AND axis_id IN (SELECT id FROM axes WHERE is_active)", (proposition_id,))
        for code, loading in wanted.items():
            conn.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence, is_validated) VALUES (%s, %s, %s, 1, true)", (proposition_id, ids[code], loading))
        conn.execute("UPDATE propositions SET axes_read_at = COALESCE(axes_read_at, now()), axes_validated_at = now() WHERE id = %s", (proposition_id,))
        conn.execute("SELECT refresh_person_axis_scores(%s)", (guild_id,))
        return {"axes": _links(conn, proposition_id)}


class OnlyValidated(BaseModel):
    value: bool


@router.put("/only-validated")
def only_validated(request: Request, body: OnlyValidated, guild: int | None = None) -> dict:
    """Whether only the links that a person validated count in the scores of people (the others are ignored), and the scores are computed again."""
    with request.app.state.pool.connection() as conn, conn.transaction():
        guild_id = resolve_guild(conn, guild)
        conn.execute("""INSERT INTO scoring_settings (key, value, description) VALUES ('only_validated_loadings', %s, 'only the validated weights count')
                        ON CONFLICT (key) DO UPDATE SET value = excluded.value""", (1 if body.value else 0,))
        conn.execute("SELECT refresh_person_axis_scores(%s)", (guild_id,))
    return {"only_validated": body.value}


@router.post("/proposition/{proposition_id}/axes/validate")
def validate_links(request: Request, proposition_id: int, guild: int | None = None) -> dict:
    """The links as the model proposed them are right: validated as they are."""
    with request.app.state.pool.connection() as conn, conn.transaction():
        guild_id = resolve_guild(conn, guild)
        conn.execute("UPDATE proposition_axis SET is_validated = true WHERE proposition_id = %s", (proposition_id,))
        conn.execute("UPDATE propositions SET axes_validated_at = now() WHERE id = %s", (proposition_id,))
        conn.execute("SELECT refresh_person_axis_scores(%s)", (guild_id,))
        return {"axes": _links(conn, proposition_id)}


@router.get("/proposition/{proposition_id}")
def proposition(request: Request, proposition_id: int, guild: int | None = None) -> dict:
    """The people who take a position on a proposition, with their quote."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        p = conn.execute("SELECT id, text, status FROM propositions WHERE id = %s", (proposition_id,)).fetchone()
        if p is None:
            raise HTTPException(status_code=404, detail="proposition inconnue")
        rows = conn.execute(
            f"""SELECT s.user_id, {LABEL} AS label, s.stance, s.confidence, s.stated_at, s.claim_id, cl.text AS claim
                FROM current_stances s JOIN claims cl ON cl.id = s.claim_id JOIN users u ON u.id = s.user_id
                LEFT JOIN members m ON m.guild_id = s.guild_id AND m.user_id = u.id
                WHERE s.guild_id = %s AND s.proposition_id = %s ORDER BY s.stance DESC, s.confidence DESC, label""", (guild_id, proposition_id)).fetchall()
        evidence = _evidence(conn, [r["claim_id"] for r in rows])
        axes = _links(conn, proposition_id)
        roles: dict[int, list[str]] = {}
        for r in conn.execute(
                """SELECT ci.user_id, cr.name FROM claimed_ideologies ci JOIN classified_roles cr ON cr.role_id = ci.role_id
                   WHERE ci.guild_id = %s AND ci.user_id = ANY(%s) ORDER BY cr.name""", (guild_id, [x["user_id"] for x in rows])):
            roles.setdefault(r["user_id"], []).append(r["name"])
    return {"id": p["id"], "text": p["text"], "status": p["status"], "axes": axes,
            "people": [{"id": str(r["user_id"]), "label": r["label"], "roles": roles.get(r["user_id"], []), "stance": r["stance"], "confidence": round(float(r["confidence"]), 2),
                        "at": iso(r["stated_at"]), "claim": r["claim"], "evidence": evidence.get(r["claim_id"], [])} for r in rows]}


def _theme_of_claim():
    """SQL: the theme (a merged theme counts for the one it joined) of the conversation that a claim was read in."""
    return """LEFT JOIN LATERAL (
                   SELECT COALESCE(t.merged_into, t.id) AS topic_id FROM topic_assignments a JOIN topics t ON t.id = a.topic_id
                   WHERE a.conversation_id = cl.conversation_id AND t.status <> 'rejected'
                   ORDER BY a.run_id DESC LIMIT 1) th ON true
               LEFT JOIN topics tt ON tt.id = th.topic_id"""


@router.get("/person/{user_id}")
def person(request: Request, user_id: int, guild: int | None = None) -> dict:
    """What was read of one person: where they stand on each axis (with how sure), whether the ideologies that they gave themselves match
    it, and, theme by theme, their positions with the quotes and the people they talked with in those conversations."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        axes = conn.execute(
            """SELECT a.id, a.code, a.name, a.question, a.negative_pole, a.positive_pole, s.score, s.uncertainty, s.n_propositions, s.evidence_weight
               FROM axes a LEFT JOIN person_axis_scores s ON s.axis_id = a.id AND s.guild_id = %s AND s.user_id = %s
               WHERE a.is_active ORDER BY a.position""", (guild_id, user_id)).fetchall()
        expected: dict[int, list[dict]] = {}
        for r in conn.execute(
                """SELECT c.axis_id, c.role_name, c.min_score, c.max_score, c.verdict FROM ideology_concordance c
                   WHERE c.guild_id = %s AND c.user_id = %s ORDER BY c.role_name""", (guild_id, user_id)):
            expected.setdefault(r["axis_id"], []).append({"role": r["role_name"], "min": float(r["min_score"]), "max": float(r["max_score"]), "verdict": r["verdict"]})
        contributions: dict[int, list[dict]] = {}
        for r in conn.execute(
                """SELECT pa.axis_id, p.id AS proposition_id, p.text, pa.loading, pa.is_validated, s.stance, s.confidence FROM current_stances s
                   JOIN proposition_axis pa ON pa.proposition_id = s.proposition_id AND pa.loading <> 0 JOIN propositions p ON p.id = s.proposition_id
                   WHERE s.guild_id = %s AND s.user_id = %s AND p.status NOT IN ('rejected', 'merged') ORDER BY abs(pa.loading) DESC""", (guild_id, user_id)):
            contributions.setdefault(r["axis_id"], []).append({"proposition_id": r["proposition_id"], "proposition": r["text"], "loading": float(r["loading"]), "validated": r["is_validated"], "stance": r["stance"],
                                                               "confidence": round(float(r["confidence"]), 2)})
        roles = conn.execute(
            """SELECT role_name, verdict, confirmed_axes, compatible_axes, incompatible_axes, insufficient_axes FROM claimed_ideology_summary
               WHERE guild_id = %s AND user_id = %s ORDER BY role_name""", (guild_id, user_id)).fetchall()
        conflicts = conn.execute(
            """SELECT ia.name AS a, ib.name AS b, ax.name AS axis FROM claimed_ideology_conflicts c JOIN ideologies ia ON ia.id = c.ideology_a
               JOIN ideologies ib ON ib.id = c.ideology_b JOIN axes ax ON ax.id = c.axis_id WHERE c.guild_id = %s AND c.user_id = %s""", (guild_id, user_id)).fetchall()
        rows = conn.execute(
            f"""SELECT s.proposition_id, p.text AS proposition, s.stance, s.confidence, s.stated_at, s.claim_id, cl.text AS claim, cl.conversation_id,
                       th.topic_id, tt.label AS theme
                FROM current_stances s JOIN claims cl ON cl.id = s.claim_id JOIN propositions p ON p.id = s.proposition_id
                {_theme_of_claim()}
                WHERE s.guild_id = %s AND s.user_id = %s AND p.status NOT IN ('rejected', 'merged') ORDER BY s.stated_at DESC""", (guild_id, user_id)).fetchall()
        earlier: dict[int, list[dict]] = {}
        for r in conn.execute(
                """SELECT proposition_id, stance, stated_at FROM claims WHERE guild_id = %s AND user_id = %s AND stance IS NOT NULL AND proposition_id IS NOT NULL
                   AND review_status <> 'rejected' ORDER BY stated_at""", (guild_id, user_id)):
            earlier.setdefault(r["proposition_id"], []).append({"stance": r["stance"], "at": iso(r["stated_at"])})
        evidence = _evidence(conn, [r["claim_id"] for r in rows])
        conversations = sorted({r["conversation_id"] for r in rows if r["conversation_id"]})
        others: dict[int, dict[int, dict]] = {}
        if conversations:
            for r in conn.execute(
                    f"""SELECT cm.conversation_id, msg.author_id, {LABEL} AS label, count(*) AS n FROM conversation_messages cm
                        JOIN messages msg ON msg.id = cm.message_id JOIN users u ON u.id = msg.author_id
                        LEFT JOIN members m ON m.guild_id = %s AND m.user_id = u.id
                        WHERE cm.conversation_id = ANY(%s) AND msg.author_id <> %s AND NOT u.is_bot GROUP BY cm.conversation_id, msg.author_id, label""",
                (guild_id, conversations, user_id)):
                others.setdefault(r["conversation_id"], {})[r["author_id"]] = {"label": r["label"], "n": r["n"]}
            # Did the other person take a position on the same proposition in that conversation, and the same one?
            their = {(r["conversation_id"], r["user_id"], r["proposition_id"]): r["stance"] for r in conn.execute(
                """SELECT conversation_id, user_id, proposition_id, stance FROM claims WHERE conversation_id = ANY(%s) AND user_id <> %s AND stance IS NOT NULL
                   AND proposition_id IS NOT NULL AND review_status <> 'rejected'""", (conversations, user_id))}
    themes: dict[int, dict] = {}
    positions = []
    for r in rows:
        position = {"proposition_id": r["proposition_id"], "proposition": r["proposition"], "stance": r["stance"], "confidence": round(float(r["confidence"]), 2),
                    "at": iso(r["stated_at"]), "claim": r["claim"], "evidence": evidence.get(r["claim_id"], []),
                    "history": earlier.get(r["proposition_id"], []) if len(earlier.get(r["proposition_id"], [])) > 1 else []}
        positions.append(position)
        key = r["topic_id"] or 0
        theme = themes.setdefault(key, {"id": r["topic_id"], "label": r["theme"] or "Sans thème", "positions": [], "_people": {}})
        theme["positions"].append(position)
        for uid, info in others.get(r["conversation_id"], {}).items():
            entry = theme["_people"].setdefault(uid, {"id": str(uid), "label": info["label"], "messages": 0, "agrees": None, "disagrees": None})
            entry["messages"] += info["n"]
            stance = their.get((r["conversation_id"], uid, r["proposition_id"]))
            if stance is not None:
                entry["agrees" if stance == r["stance"] else "disagrees"] = True
    out_themes = []
    for t in sorted(themes.values(), key=lambda t: -len(t["positions"])):
        people = sorted(t.pop("_people").values(), key=lambda p: -p["messages"])[:15]
        out_themes.append({**t, "talked_with": [{"id": p["id"], "label": p["label"], "messages": p["messages"],
                                                  "relation": "d'accord" if p["agrees"] and not p["disagrees"] else "en désaccord" if p["disagrees"] and not p["agrees"] else "" if not p["agrees"] else "mitigé"}
                                                 for p in people]})
    return {
        "axes": [{"code": a["code"], "name": a["name"], "question": a["question"], "negative_pole": a["negative_pole"], "positive_pole": a["positive_pole"],
                  "score": None if a["score"] is None else float(a["score"]), "uncertainty": None if a["uncertainty"] is None else float(a["uncertainty"]),
                  "positions": a["n_propositions"] or 0, "evidence": None if a["evidence_weight"] is None else round(float(a["evidence_weight"]), 2),
                  "expected": expected.get(a["id"], []), "contributions": contributions.get(a["id"], [])[:8]} for a in axes],
        "roles": [{"role": r["role_name"], "verdict": r["verdict"], "confirmed": r["confirmed_axes"], "compatible": r["compatible_axes"],
                   "incompatible": r["incompatible_axes"], "insufficient": r["insufficient_axes"]} for r in roles],
        "role_conflicts": [{"a": c["a"], "b": c["b"], "axis": c["axis"]} for c in conflicts],
        "themes": out_themes, "positions": positions,
    }


@router.get("/coherence")
def coherence(request: Request, guild: int | None = None) -> dict:
    """The people who gave themselves an ideology, and whether what they say matches it: the ones that do not first."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        rows = conn.execute(
            f"""SELECT s.user_id, {LABEL} AS label, s.role_name, s.verdict, s.confirmed_axes, s.compatible_axes, s.incompatible_axes, s.insufficient_axes
                FROM claimed_ideology_summary s JOIN users u ON u.id = s.user_id LEFT JOIN members m ON m.guild_id = s.guild_id AND m.user_id = u.id
                WHERE s.guild_id = %s AND NOT u.is_bot""", (guild_id,)).fetchall()
        bad: dict[tuple[int, str], list[dict]] = {}
        for r in conn.execute(
                """SELECT c.user_id, c.role_name, c.axis_id, ax.name AS axis, ax.negative_pole, ax.positive_pole, c.score, c.uncertainty, c.min_score, c.max_score, c.n_propositions
                   FROM ideology_concordance c JOIN axes ax ON ax.id = c.axis_id WHERE c.guild_id = %s AND c.verdict = 'incompatible'""", (guild_id,)):
            bad.setdefault((r["user_id"], r["role_name"]), []).append(
                {"axis": r["axis"], "negative_pole": r["negative_pole"], "positive_pole": r["positive_pole"], "score": float(r["score"]),
                 "uncertainty": float(r["uncertainty"]), "expected": [float(r["min_score"]), float(r["max_score"])], "positions": r["n_propositions"],
                 "axis_id": r["axis_id"], "contributions": []})
        # What was said, so that a contradiction can be judged without opening the person: their positions on that axis, with their messages
        wanted = {(user, a["axis_id"]) for (user, _), axes_ in bad.items() for a in axes_}
        if wanted:
            rows_ = conn.execute(
                """SELECT s.user_id, pa.axis_id, s.claim_id, p.id AS proposition_id, p.text, pa.loading, pa.is_validated, s.stance FROM current_stances s
                   JOIN proposition_axis pa ON pa.proposition_id = s.proposition_id AND pa.loading <> 0 JOIN propositions p ON p.id = s.proposition_id
                   WHERE s.guild_id = %s AND s.user_id = ANY(%s) AND pa.axis_id = ANY(%s) AND p.status NOT IN ('rejected', 'merged')
                   ORDER BY abs(pa.loading) DESC, s.stated_at DESC""",
                (guild_id, list({u for u, _ in wanted}), list({a for _, a in wanted}))).fetchall()
            rows_ = [r for r in rows_ if (r["user_id"], r["axis_id"]) in wanted]
            quotes = _evidence(conn, [r["claim_id"] for r in rows_])
            said: dict[tuple[int, int], list[dict]] = {}
            for r in rows_:
                said.setdefault((r["user_id"], r["axis_id"]), []).append(
                    {"proposition_id": r["proposition_id"], "proposition": r["text"], "loading": float(r["loading"]), "validated": r["is_validated"],
                     "stance": r["stance"], "evidence": quotes.get(r["claim_id"], [])[:3]})
            for (user, _), axes_ in bad.items():
                for a in axes_:
                    a["contributions"] = said.get((user, a["axis_id"]), [])[:8]
        conflicts = {(r["user_id"]) for r in conn.execute("SELECT DISTINCT user_id FROM claimed_ideology_conflicts WHERE guild_id = %s", (guild_id,))}
    people: dict[int, dict] = {}
    for r in rows:
        p = people.setdefault(r["user_id"], {"id": str(r["user_id"]), "label": r["label"], "roles": [], "role_conflict": r["user_id"] in conflicts})
        p["roles"].append({"role": r["role_name"], "verdict": r["verdict"], "confirmed": r["confirmed_axes"], "incompatible": r["incompatible_axes"],
                           "insufficient": r["insufficient_axes"], "against": bad.get((r["user_id"], r["role_name"]), [])})
    order = {"discordant": 0, "not_verifiable": 2, "concordant": 1}
    listed = sorted(people.values(), key=lambda p: (min(order[r["verdict"]] for r in p["roles"]), not p["role_conflict"], p["label"].casefold()))
    return {"people": listed, "totals": {"people": len(listed), **_people_by_verdict(listed)}}


def _people_by_verdict(people: list[dict]) -> dict[str, int]:
    """How many people are in each verdict, counted by person (the figures of the page add up to the number of people): the worst verdict of their roles decides
    (a role that contradicts them counts before one that fits; « not enough said » only when no role can be judged)."""
    counts = {"discordant": 0, "concordant": 0, "not_verifiable": 0}
    for person in people:
        verdicts = {role["verdict"] for role in person["roles"]}
        counts["discordant" if "discordant" in verdicts else "concordant" if "concordant" in verdicts else "not_verifiable"] += 1
    return counts
