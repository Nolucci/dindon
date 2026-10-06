"""The analysis, from the interface: start it, follow it, and look at the topics that it proposes. Everything needs the session cookie.

A topic is found without any regard to people, and what these routes show of it is its name, its keywords, how many conversations it
holds, and a few typical excerpts *without the names of the people* (mentions are removed). A person decides what becomes of each
proposal: validated, rejected, renamed, merged into another. The code never validates by itself.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dindon.analysis.embeddings import conversation_texts
from dindon.analysis.job import STAGES, AnalysisBusy, NotReady
from dindon.api.auth import require_session
from dindon.api.common import resolve_guild

router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

EXCERPT_CHARS = 500


class StartRequest(BaseModel):
    guild: str | None = Field(default=None, pattern=r"^[0-9]{1,20}$", description="a Discord id, as text (18 digits do not fit a JavaScript number)")
    stages: list[Literal["conversations", "embeddings", "themes", "claims", "axes"]] = list(STAGES)
    limit: int | None = Field(default=None, ge=1, le=100000, description="for the claims: read at most this many conversations")
    topics: int | None = Field(default=None, ge=2, le=80, description="the number of topics, when the person wants to choose it")
    rebuild: bool = False


class TopicChange(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    status: Literal["proposed", "validated", "rejected"] | None = None


class Merge(BaseModel):
    into: int


@router.get("/analysis")
def analysis(request: Request, guild: int | None = None) -> dict:
    """Is the analysis possible (Ollama, the models), what is done, and what it is doing."""
    state = request.app.state
    with state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        counts = conn.execute(
            """SELECT count(*) AS conversations, count(*) FILTER (WHERE c.kept) AS kept,
                      count(*) FILTER (WHERE c.kept AND EXISTS (SELECT 1 FROM conversation_embeddings e WHERE e.conversation_id = c.id AND e.model = %s)) AS embedded
               FROM conversations c JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s""",
            (state.analysis.embed_model, guild_id)).fetchone()
        topics = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM topics WHERE guild_id = %s GROUP BY status", (guild_id,))}
        messages = conn.execute("SELECT count(*) AS n FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s", (guild_id,)).fetchone()["n"]
        run = conn.execute("SELECT id, model, created_at, parameters FROM topic_runs WHERE guild_id = %s ORDER BY id DESC LIMIT 1", (guild_id,)).fetchone()
    return {
        "guild": str(guild_id), "ready": state.analysis.readiness(), "job": state.analysis.status(),
        "models": {"embeddings": state.analysis.embed_model, "naming": state.analysis.name_model},
        "counts": {"messages": messages, **counts, "topics": topics},
        "last_run": None if run is None else {"id": run["id"], "model": run["model"], "at": run["created_at"].isoformat(),
                                              "k": run["parameters"].get("k"), "chosen_by": run["parameters"].get("chosen_by")},
    }


@router.post("/analysis")
def start(request: Request, body: StartRequest) -> dict:
    state = request.app.state
    with state.pool.connection() as conn:
        guild_id = resolve_guild(conn, int(body.guild) if body.guild else None)
    try:
        state.analysis.start(guild_id, tuple(body.stages), topics=body.topics, rebuild=body.rebuild, limit=body.limit)
    except NotReady as problem:
        raise HTTPException(status_code=409, detail=str(problem)) from None
    except AnalysisBusy:
        raise HTTPException(status_code=409, detail="Une analyse est déjà en cours : attendez qu'elle finisse, ou annulez-la.") from None
    return state.analysis.status()


@router.post("/analysis/cancel")
def cancel(request: Request) -> dict:
    request.app.state.analysis.cancel()
    return request.app.state.analysis.status()


def _topic(row: dict, examples: dict[int, list[str]]) -> dict:
    return {"id": row["id"], "label": row["label"], "description": row["description"], "keywords": row["keywords"], "status": row["status"],
            "conversations": row["conversations"], "last_at": row["last_at"].isoformat() if row["last_at"] else None,
            "validated_at": row["validated_at"].isoformat() if row["validated_at"] else None, "examples": examples.get(row["id"], [])}


_SELECT = """
SELECT t.id, t.label, t.description, t.keywords, t.status, t.validated_at,
       (SELECT count(*) FROM topic_assignments a JOIN topics s ON s.id = a.topic_id WHERE s.id = t.id OR s.merged_into = t.id) AS conversations,
       (SELECT max(c.ended_at) FROM topic_assignments a JOIN topics s ON s.id = a.topic_id JOIN conversations c ON c.id = a.conversation_id
         WHERE s.id = t.id OR s.merged_into = t.id) AS last_at
FROM topics t
"""


def _one(conn, topic_id: int) -> dict:
    row = conn.execute(_SELECT + "WHERE t.id = %s", (topic_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="thème inconnu")
    return _topic(row, {})


@router.get("/topics")
def topics(request: Request, guild: int | None = None, rejected: bool = False, examples: bool = Query(True)) -> list[dict]:
    """The topics of a server: the proposals, then what was validated; with a few typical excerpts, without names."""
    statuses = ["proposed", "validated"] + (["rejected"] if rejected else [])
    with request.app.state.pool.connection() as conn:
        guild_id = resolve_guild(conn, guild)
        rows = conn.execute(_SELECT + "WHERE t.guild_id = %s AND t.status = ANY(%s) ORDER BY conversations DESC, t.id", (guild_id, statuses)).fetchall()
        samples: dict[int, list[str]] = {}
        if examples and rows:
            picked = conn.execute(
                """SELECT topic_id, conversation_id FROM (
                       SELECT a.topic_id, a.conversation_id, row_number() OVER (PARTITION BY a.topic_id ORDER BY a.similarity DESC) AS rn
                       FROM topic_assignments a WHERE a.topic_id = ANY(%s)) x WHERE rn <= 3""", ([r["id"] for r in rows],)).fetchall()
            texts = conversation_texts(conn, sorted({p["conversation_id"] for p in picked}))
            for p in picked:
                text = texts.get(p["conversation_id"], "")
                if text:
                    samples.setdefault(p["topic_id"], []).append(text.replace("\n", " / ")[:EXCERPT_CHARS])
    return [_topic(r, samples) for r in rows]


@router.patch("/topics/{topic_id}")
def change(request: Request, topic_id: int, body: TopicChange) -> dict:
    """Renames, describes, validates, rejects or puts back a topic. Whatever the person does, the topic is theirs from then on: a new
    run of the discovery never replaces it (`touched_at`). The several updates are one transaction."""
    with request.app.state.pool.connection() as conn, conn.transaction():
        _one(conn, topic_id)
        if body.label is not None:
            conn.execute("UPDATE topics SET label = %s WHERE id = %s", (body.label.strip(), topic_id))
        if body.description is not None:
            conn.execute("UPDATE topics SET description = %s WHERE id = %s", (body.description.strip() or None, topic_id))
        if body.status is not None:
            conn.execute("UPDATE topics SET status = %s, validated_at = CASE WHEN %s::text = 'validated' THEN now() END, merged_into = NULL WHERE id = %s",
                         (body.status, body.status, topic_id))
            if body.status == "rejected":                        # what was merged into a rejected topic is not lost: it is a proposal again
                conn.execute("UPDATE topics SET status = 'proposed', merged_into = NULL WHERE merged_into = %s", (topic_id,))
        conn.execute("UPDATE topics SET touched_at = now() WHERE id = %s", (topic_id,))
        return _one(conn, topic_id)


@router.post("/topics/{topic_id}/merge")
def merge(request: Request, topic_id: int, body: Merge) -> dict:
    """The topic is the same as another one: its conversations count for that one (nothing is lost, and it can be undone). Both are
    now the person's work: a new run of the discovery replaces neither."""
    if body.into == topic_id:
        raise HTTPException(status_code=422, detail="Un thème ne peut pas être fusionné avec lui-même.")
    with request.app.state.pool.connection() as conn, conn.transaction():
        _one(conn, topic_id)
        target = conn.execute("SELECT guild_id, status FROM topics WHERE id = %s", (body.into,)).fetchone()
        mine = conn.execute("SELECT guild_id FROM topics WHERE id = %s", (topic_id,)).fetchone()
        if target is None or target["guild_id"] != mine["guild_id"] or target["status"] in ("merged", "rejected"):
            raise HTTPException(status_code=422, detail="Le thème choisi n'existe pas, est rejeté, ou est lui-même fusionné.")
        conn.execute("UPDATE topics SET status = 'merged', merged_into = %s, validated_at = NULL, touched_at = now() WHERE id = %s", (body.into, topic_id))
        conn.execute("UPDATE topics SET merged_into = %s WHERE merged_into = %s", (body.into, topic_id))   # what was merged into it follows
        conn.execute("UPDATE topics SET touched_at = now() WHERE id = %s", (body.into,))
        return _one(conn, body.into)
