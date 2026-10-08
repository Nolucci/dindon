"""The reread, from the interface (docs/regles-du-bot.md, « Relecture »): start it, follow it, look at what it changed, and undo a change. Everything needs the session cookie.

A reread reads again each position of the people with the messages that came before it, and corrects what is not right (the sense of the position, the proposition, the theme): see
analysis/reread.py. It is apart from the analysis and never runs with it. What these routes show of a change is the words of the position (as the page Positions already does) and what it was
before: never a name that the page does not show, never a message beyond the proof that the position already has.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dindon.analysis import reread
from dindon.analysis.job import NotReady
from dindon.api.auth import require_session
from dindon.api.common import resolve_guild

router = APIRouter(prefix="/api/reread", dependencies=[Depends(require_session)])


class StartRequest(BaseModel):
    guild: str | None = Field(default=None, pattern=r"^[0-9]{1,20}$")
    user: str | None = Field(default=None, pattern=r"^[0-9]{1,20}$", description="only the positions of this person")
    theme: int | None = Field(default=None, ge=1, description="only the positions in this theme")
    proposition: int | None = Field(default=None, ge=1, description="only the positions on this proposition")
    force: bool = Field(default=False, description="also read again what the current method already read")
    limit: int | None = Field(default=None, ge=1, le=100000, description="read at most this many positions")


@router.get("")
def overview(request: Request, guild: int | None = None) -> dict:
    """What there is to reread, what a reread is doing, and the last ones with what they changed (counts)."""
    state = request.app.state
    with state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        runs = conn.execute(
            """SELECT id, started_at, finished_at, state, scope, model, version, counts, error FROM reread_runs WHERE guild_id = %s ORDER BY id DESC LIMIT 5""", (guild_id,)).fetchall()
        todo = reread.counts(conn, guild_id)
    return {"guild": str(guild_id), "version": reread.VERSION, "todo": todo, "job": state.reread.status(), "model": state.reread.model,
            "runs": [{"id": r["id"], "at": r["started_at"].isoformat(), "finished": r["finished_at"].isoformat() if r["finished_at"] else None, "state": r["state"], "scope": r["scope"],
                      "model": r["model"], "counts": r["counts"], "error": r["error"]} for r in runs]}


@router.post("")
def start(request: Request, body: StartRequest) -> dict:
    state = request.app.state
    with state.pool.connection() as conn:
        guild_id = resolve_guild(conn, int(body.guild) if body.guild else None)
    try:
        state.reread.start(guild_id, user_id=int(body.user) if body.user else None, theme_id=body.theme, proposition_id=body.proposition, force=body.force, limit=body.limit)
    except NotReady as problem:
        raise HTTPException(status_code=409, detail=str(problem)) from None
    except reread.RereadBusy:
        raise HTTPException(status_code=409, detail="Une analyse ou une relecture est déjà en cours : attendez qu'elle finisse, ou annulez-la.") from None
    return state.reread.status()


@router.post("/cancel")
def cancel(request: Request) -> dict:
    request.app.state.reread.cancel()
    return request.app.state.reread.status()


@router.get("/changes")
def changes(request: Request, guild: int | None = None, run: int | None = None, verdict: Literal["corrected", "uncertain", "confirmed"] = "corrected",
            limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    """What a reread decided, newest first (by default what it corrected, with what it was before). `run`: one reread; else all of them."""
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        rows = conn.execute(
            """SELECT r.run_id, r.claim_id, r.verdict, r.changes, r.reason, r.certainty, r.undone_at, r.created_at, cl.user_id, cl.text AS claim, cl.stance, cl.kind,
                      p.text AS proposition, COALESCE(u.global_name, u.name) AS person
               FROM claim_rereads r JOIN reread_runs rr ON rr.id = r.run_id JOIN claims cl ON cl.id = r.claim_id LEFT JOIN propositions p ON p.id = cl.proposition_id
               JOIN users u ON u.id = cl.user_id
               WHERE rr.guild_id = %s AND r.verdict = %s AND (%s::bigint IS NULL OR r.run_id = %s)
                 AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = cl.user_id)
               ORDER BY r.created_at DESC, r.claim_id LIMIT %s OFFSET %s""", (guild_id, verdict, run, run, limit, offset)).fetchall()
        quotes: dict[int, list[str]] = {}
        for q in conn.execute("SELECT claim_id, quote FROM claim_evidence WHERE claim_id = ANY(%s) AND quote IS NOT NULL ORDER BY message_id", ([r["claim_id"] for r in rows],)):
            quotes.setdefault(q["claim_id"], []).append(q["quote"])
        propositions = {r["id"]: r["text"] for r in conn.execute(
            "SELECT id, text FROM propositions WHERE id = ANY(%s)", ([v for r in rows for v in (r["changes"].get("proposition_id") or []) if isinstance(v, int)],))}
        topics = {r["id"]: r["label"] for r in conn.execute(
            "SELECT id, label FROM topics WHERE id = ANY(%s)", ([v for r in rows for v in (r["changes"].get("theme") or []) if isinstance(v, int)],))}
    words = {1: "accord", 0: "nuance", -1: "désaccord", None: "aucune"}
    out = []
    for r in rows:
        c = r["changes"]
        shown = {}
        if "stance" in c:
            shown["stance"] = [words.get(c["stance"][0]), words.get(c["stance"][1])]
        if "kind" in c:
            shown["kind"] = c["kind"]
        if "proposition_id" in c:
            shown["proposition"] = [propositions.get(c["proposition_id"][0]), propositions.get(c["proposition_id"][1])]
        if "theme" in c:
            shown["theme"] = [topics.get(c["theme"][0]), topics.get(c["theme"][1])]
        out.append({"run": r["run_id"], "claim": r["claim_id"], "user": str(r["user_id"]), "person": r["person"], "text": r["claim"], "proposition": r["proposition"], "quotes": quotes.get(r["claim_id"], [])[:3],
                    "verdict": r["verdict"], "changes": shown, "reason": r["reason"], "certainty": r["certainty"], "undone": r["undone_at"] is not None, "at": r["created_at"].isoformat()})
    return {"changes": out, "next": offset + len(out) if len(out) == limit else None}


@router.post("/undo/{claim_id}")
def undo(request: Request, claim_id: int) -> dict:
    """Puts a corrected position back as it was, and keeps it as confirmed by a person: a reread never touches it again."""
    with request.app.state.pool.connection() as conn:
        found = conn.execute("SELECT guild_id FROM claims WHERE id = %s", (claim_id,)).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="Cette position n'existe pas.")
        if not reread.undo(conn, claim_id):
            raise HTTPException(status_code=409, detail="Rien à annuler pour cette position.")
        conn.execute("SELECT refresh_person_axis_scores(%s)", (found["guild_id"],))
    return {"claim": claim_id, "undone": True}
