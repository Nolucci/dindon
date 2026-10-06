"""The automatic reading, from the interface (page Système). Needs the session. See automation.py: off by default, and the positions cannot be switched on
without saying that the people are informed."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from dindon import automation
from dindon.api.auth import require_session

router = APIRouter(prefix="/api/automation", dependencies=[Depends(require_session)])


class Body(BaseModel):
    enabled: bool = False
    vectors: bool = True
    themes: bool = False
    positions: bool = False
    positions_acknowledged: bool = False
    interval_minutes: int = Field(default=30, ge=1, le=10080)
    batch: int = Field(default=20, ge=1, le=500)
    window_from: int = Field(default=0, ge=0, le=23)
    window_to: int = Field(default=24, ge=1, le=24)


def _answer(request: Request, conn) -> dict:
    state = request.app.state
    cfg, st = automation.load(conn), automation.state(conn)
    totals = {"new_messages": 0, "without_vector": 0, "unread": 0, "unlinked": 0, "unplaced": 0}
    for row in conn.execute("""SELECT g.id FROM guilds g WHERE EXISTS (SELECT 1 FROM channels c JOIN messages m ON m.channel_id = c.id WHERE c.guild_id = g.id)""").fetchall():
        for key, value in automation.pending(conn, row["id"], state.analysis.embed_model).items():
            if key in totals:
                totals[key] += value
    return {"settings": cfg, "state": st, "next_at": automation.next_at(cfg, st), "in_window": automation.in_window(cfg), "pending": totals,
            "timezone": automation.timezone_name(), "intervals": list(automation.INTERVALS), "running": state.analysis.status()["state"] in ("running", "cancelling")}


@router.get("")
def read(request: Request) -> dict:
    with request.app.state.pool.connection() as conn:
        return _answer(request, conn)


@router.put("")
def write(request: Request, body: Body) -> dict:
    """Saves the settings. Switching on the positions without `positions_acknowledged` is refused (it would be switched off silently otherwise)."""
    if body.positions and not body.positions_acknowledged:
        raise HTTPException(status_code=422, detail="Pour lire les positions des personnes, confirmez qu'elles sont informées (docs/CONFORMITE.md).")
    with request.app.state.pool.connection() as conn:
        automation.save(conn, body.model_dump())
        return _answer(request, conn)


@router.post("/run")
def run_now(request: Request) -> dict:
    """Asks for a cycle at once (the loop starts it within seconds), whatever the interval and the hours; what is read still follows the settings."""
    with request.app.state.pool.connection() as conn:
        automation.request_run(conn)
        return _answer(request, conn)
