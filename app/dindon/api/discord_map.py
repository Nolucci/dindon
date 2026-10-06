"""What the map on Discord shows (page Système, panel « Carte sur Discord »). Needs the session. See discord_map.py: off by default."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from dindon import discord_map
from dindon.api.auth import require_session

router = APIRouter(prefix="/api/discord-map", dependencies=[Depends(require_session)])


class Body(BaseModel):
    enabled: bool = False
    max_people: int = Field(default=40, ge=5, le=350)
    names: int = Field(default=15, ge=0, le=350)
    kinds: list[str] = Field(default_factory=lambda: list(discord_map.KINDS))
    sections: list[str] = Field(default_factory=lambda: list(discord_map.DEFAULT["sections"]))     # what the card of a person shows in the Activity
    acknowledged: bool = False                                                                       # the people are informed: needed for the sections that read them


@router.get("")
def read(request: Request) -> dict:
    with request.app.state.pool.connection() as conn:
        return discord_map.load(conn)


@router.put("")
def write(request: Request, body: Body) -> dict:
    """Saves the settings. The sections that read the people (roles, axes) are refused without the confirmation that the people are informed (it would be dropped silently otherwise)."""
    if not body.acknowledged and set(body.sections) & set(discord_map.SENSITIVE):
        raise HTTPException(status_code=422, detail="Pour montrer les rôles ou les positions, confirmez que les personnes sont informées (docs/regles-du-bot.md).")
    with request.app.state.pool.connection() as conn:
        return discord_map.save(conn, body.model_dump())
