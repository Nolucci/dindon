"""The debates, for the person in charge (everything needs the session cookie): the list, and for each debate its statistics and, when the claims were checked, each claim with its verdict,
its exact quotations and its links (docs/regles-du-bot.md). Read only. People who asked not to be recorded are in none of it. The names come from the people table: this is the owner's interface,
not Discord."""
from fastapi import APIRouter, Depends, HTTPException, Request

from dindon.api.auth import require_session
from dindon.debate import claims, stats
from dindon.debate.checker import resolve_mode

router = APIRouter(prefix="/api/debates", dependencies=[Depends(require_session)])


def _names(conn, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = conn.execute("SELECT id, name, global_name FROM users WHERE id = ANY(%s)", ([int(i) for i in ids],)).fetchall()
    return {str(r["id"]): r["global_name"] or r["name"] for r in rows}


@router.get("")
def overview(request: Request) -> dict:
    settings = request.app.state.settings
    mode, why = resolve_mode(settings)
    with request.app.state.pool.connection() as conn:
        listed = stats.list_recent(conn)
    return {"checks": {"asked": settings.debate_checks, "mode": mode, "why_not": why, "model": settings.debate_model,
                       "search_services": [name for name, on in (("factcheck", bool(settings.factcheck_api_key)), ("searxng", bool(settings.searxng_url))) if on],
                       "min_precision": settings.debate_min_precision, "measured_precision": settings.debate_precision},
            "debates": listed}


@router.get("/{debate_id}")
def detail(debate_id: int, request: Request) -> dict:
    with request.app.state.pool.connection() as conn:
        found = stats.collect(conn, debate_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Ce débat n'existe pas.")
        names = _names(conn, [p["user_id"] for p in found["participants"]])
        waiting = conn.execute("SELECT count(*) AS n FROM debate_messages dm WHERE dm.debate_id = %s AND dm.read_at IS NULL "
                               "AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = dm.author_id)", (debate_id,)).fetchone()["n"]
        corrections = conn.execute("SELECT count(*) FILTER (WHERE posted_message_id IS NOT NULL AND retracted_at IS NULL) AS posted, "
                                   "count(*) FILTER (WHERE retracted_at IS NOT NULL) AS taken_back FROM debate_corrections WHERE debate_id = %s", (debate_id,)).fetchone()
    for person in found["participants"]:
        person["name"] = names.get(person["user_id"])
    by_id = {p["user_id"]: p["name"] for p in found["participants"]}
    for claim in found["claims"]:
        claim["author_name"] = by_id.get(claim["author_id"])
    return {**found, "messages_waiting_to_be_read": waiting, "corrections": {"posted": corrections["posted"], "taken_back": corrections["taken_back"]}, "verdicts": list(claims.VERDICTS)}
