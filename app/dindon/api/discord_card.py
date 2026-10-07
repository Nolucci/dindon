"""What the card on Discord shows (page Système, panel « Fiche sur Discord »). Needs the session: only the administrator changes it, from the web panel. See cards.py."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from dindon import cards
from dindon.api.auth import require_session

router = APIRouter(prefix="/api/discord-card", dependencies=[Depends(require_session)])


class Body(BaseModel):
    pages: list[str] = Field(default_factory=lambda: list(cards.PAGE_KEYS))
    blocks: dict[str, list[str]] = Field(default_factory=dict)


@router.get("")
def read(request: Request) -> dict:
    with request.app.state.pool.connection() as conn:
        return {**cards.load(conn), "available": {page: list(blocks) for page, blocks in cards.BLOCKS.items()}}


@router.put("")
def write(request: Request, body: Body) -> dict:
    with request.app.state.pool.connection() as conn:
        return cards.save(conn, body.model_dump())
