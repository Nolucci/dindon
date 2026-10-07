"""The limits of the machine, from the interface (page Système): how much the bot and the AI may use, at the cost of their speed. Needs the session.
The bot reads the values again within half a minute, the analysis while it runs: nothing to restart. See performance.py."""
import os
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from dindon import performance
from dindon.analysis import helpers
from dindon.analysis.job import AnalysisBusy
from dindon.analysis.ollama import OllamaPool
from dindon.api.auth import require_session
from fastapi import HTTPException

router = APIRouter(prefix="/api/performance", dependencies=[Depends(require_session)])


def _equal(keys: list[str]) -> dict[str, int]:
    """100 % split evenly; the remainder goes to the first ones (the server is listed first)."""
    base, extra = divmod(100, len(keys))
    return {key: base + (1 if index < extra else 0) for index, key in enumerate(keys)}


@router.get("/workers")
def workers(request: Request) -> dict:
    """Only the logged-in administrator can see the configured analysis computers."""
    client = request.app.state.analysis.client
    if not isinstance(client, OllamaPool):
        return {"workers": [], "configured": [], "shares": {helpers.LOCAL: 100}}
    configured = [c.base_url for c in client.clients if c is not client.local]
    keys = [helpers.LOCAL, *configured]
    with request.app.state.pool.connection() as conn:
        stored = helpers.load_shares(conn)
    shares = stored if stored and set(stored) == set(keys) else _equal(keys)
    return {"workers": client.status((request.app.state.analysis.embed_model, request.app.state.analysis.name_model)), "configured": configured, "shares": shares}


class WorkerList(BaseModel):
    urls: list[str] = Field(max_length=8)


@router.put("/workers")
def set_workers(request: Request, body: WorkerList) -> dict:
    try:
        with request.app.state.pool.connection() as conn, conn.transaction():
            urls = helpers.save(conn, body.urls)
            request.app.state.analysis.configure_helpers(urls)      # a new list starts again from an equal split
            helpers.clear_shares(conn)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except AnalysisBusy:
        raise HTTPException(status_code=409, detail="Attendez la fin de l'analyse avant de modifier les ordinateurs.") from None
    return workers(request)


class Shares(BaseModel):
    shares: dict[str, int] = Field(max_length=9)


@router.put("/workers/shares")
def set_shares(request: Request, body: Shares) -> dict:
    """The percentage of the work for the server ("local") and for each computer; it applies to the next calls, even during an analysis."""
    client = request.app.state.analysis.client
    configured = [c.base_url for c in client.clients if c is not client.local] if isinstance(client, OllamaPool) else []
    try:
        with request.app.state.pool.connection() as conn:
            saved = helpers.save_shares(conn, body.shares, configured)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    request.app.state.analysis.set_shares(saved)
    return workers(request)


class Settings(BaseModel):
    preset: Literal["saver", "balanced", "full", "custom"] = "custom"
    ai_max_load: int = Field(default=100, ge=10, le=100)
    ai_threads: int = Field(default=0, ge=0, le=64)
    ai_keep_alive: Literal["0", "30s", "5m", "10m", "30m"] = "10m"
    ai_batch: int = Field(default=16, ge=1, le=32)
    bot_batch_seconds: float = Field(default=0.3, ge=0.1, le=10)


def _answer(current: dict) -> dict:
    return {"settings": current, "presets": performance.PRESETS, "defaults": performance.DEFAULT, "limits": performance.LIMITS,
            "keep_alive": list(performance.KEEP_ALIVE), "cpu_count": os.cpu_count()}


@router.get("")
def read(request: Request) -> dict:
    with request.app.state.pool.connection() as conn:
        return _answer(performance.load(conn))


@router.put("")
def write(request: Request, body: Settings) -> dict:
    """Saves the limits. A preset gives its own values; `custom` takes the ones that are sent."""
    with request.app.state.pool.connection() as conn:
        return _answer(performance.save(conn, body.model_dump()))
