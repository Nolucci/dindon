"""The register of people who are not recorded, and the rights that the person in charge can exercise for them from the interface
(everything needs the session cookie). The same functions serve the commands on Discord (bot/privacy_commands.py) and `dindon privacy`.
The log only holds counts: never a message."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from dindon import privacy
from dindon.api.auth import require_session
from dindon.api.common import iso

router = APIRouter(prefix="/api/privacy", dependencies=[Depends(require_session)])

MAX_ID = 9_223_372_036_854_775_807


class Subject(BaseModel):
    user_id: int = Field(gt=0, le=MAX_ID)
    reason: str = Field("", max_length=200)


def _directories(request: Request):
    settings = request.app.state.settings
    return (settings.inbox_dir, settings.archive_dir)


@router.get("")
def overview(request: Request) -> dict:
    settings = request.app.state.settings
    with request.app.state.pool.connection() as conn:
        subjects = conn.execute(
            """SELECT s.user_id, s.status, s.reason, s.source, s.requested_at, s.erased_at, u.name, u.global_name
               FROM privacy_subjects s LEFT JOIN users u ON u.id = s.user_id ORDER BY s.requested_at DESC LIMIT 500""").fetchall()
        log = conn.execute("SELECT id, at, user_id, action, source, detail FROM privacy_log ORDER BY id DESC LIMIT 50").fetchall()
    return {
        "retention_days": settings.retention_days,
        "erase_on_removal": settings.erase_on_removal,
        "subjects": [{"user_id": str(r["user_id"]), "status": r["status"], "reason": r["reason"], "source": r["source"],
                      "requested_at": iso(r["requested_at"]), "erased_at": iso(r["erased_at"]),
                      "name": r["global_name"] or r["name"]} for r in subjects],
        "log": [{"id": r["id"], "at": iso(r["at"]), "user_id": str(r["user_id"]) if r["user_id"] else None, "action": r["action"],
                 "source": r["source"], "detail": r["detail"]} for r in log],
    }


@router.get("/find")
def find(request: Request, q: str = Query(..., min_length=2, max_length=100)) -> list[dict]:
    """People by name (or by id), to pick the one concerned. Names only: nothing of what they wrote."""
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            """SELECT u.id, u.name, u.global_name, (SELECT count(*) FROM messages m WHERE m.author_id = u.id) AS messages,
                      EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = u.id) AS registered
               FROM users u WHERE u.name ILIKE %s OR u.global_name ILIKE %s OR u.id::text = %s ORDER BY u.name LIMIT 10""",
            (like, like, q.strip())).fetchall()
    people = [{"user_id": str(r["id"]), "name": r["global_name"] or r["name"], "username": r["name"], "messages": r["messages"],
               "registered": r["registered"]} for r in rows]
    wanted = q.strip()
    if wanted.isdigit() and 5 <= len(wanted) <= 19 and int(wanted) <= MAX_ID and not any(p["user_id"] == wanted for p in people):
        # Somebody Dindon has never seen can still ask not to be recorded (before they ever write): an id is enough
        with request.app.state.pool.connection() as conn:
            registered = conn.execute("SELECT 1 FROM privacy_subjects WHERE user_id = %s", (int(wanted),)).fetchone() is not None
        people.append({"user_id": wanted, "name": "Identifiant inconnu de Dindon", "username": "", "messages": 0, "registered": registered})
    return people


@router.post("/stop")
def stop(request: Request, body: Subject) -> dict:
    """Nothing more is recorded of this person. What is already held stays (see /erase)."""
    with request.app.state.pool.connection() as conn:
        return privacy.stop_recording(conn, body.user_id, reason=body.reason or "objection", source="interface")


@router.post("/erase")
def erase(request: Request, body: Subject) -> dict:
    """Stops the recording AND deletes everything held of this person (database and files). Cannot be undone."""
    with request.app.state.pool.connection() as conn:
        counts = privacy.erase_person(conn, body.user_id, reason=body.reason or "erasure", source="interface", file_directories=_directories(request))
    return {"user_id": str(body.user_id), **counts}


@router.post("/release")
def release(request: Request, body: Subject) -> dict:
    """The person agrees to be recorded again. Nothing that was erased comes back."""
    with request.app.state.pool.connection() as conn:
        return {"user_id": str(body.user_id), "released": privacy.release(conn, body.user_id, source="interface")}


@router.get("/export/{user_id}")
def export(request: Request, user_id: int) -> Response:
    """Everything held of a person, as a file to give them (right of access)."""
    if not 0 < user_id <= MAX_ID:
        raise HTTPException(status_code=422, detail="identifiant invalide")
    with request.app.state.pool.connection() as conn:
        data = privacy.export_person(conn, user_id)
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="dindon-{user_id}.json"'})
