"""The limits of the machine, from the interface (page Système): how much the bot and the AI may use, at the cost of their speed. Needs the session.
The bot reads the values again within half a minute, the analysis while it runs: nothing to restart. See performance.py."""
import os
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from dindon import performance
from dindon.api.auth import require_session

router = APIRouter(prefix="/api/performance", dependencies=[Depends(require_session)])


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
