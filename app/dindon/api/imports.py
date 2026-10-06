"""Importing a part of a server from the interface: the channels, the people, the period. Everything needs the session cookie.

The work is the one of `dindon backfill` (collector/selection.py says what a narrowed import is). Only the servers of
DINDON_GUILD_IDS can be imported, and what these routes say never contains the token nor a message.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from dindon.api.auth import require_session
from dindon.collector.discord_api import DiscordAPI, DiscordError, RateLimited
from dindon.collector.job import ImportBusy, NotConfigured
from dindon.collector.selection import ImportSelection, SelectionError

router = APIRouter(prefix="/api/import", dependencies=[Depends(require_session)])


class ImportRequest(BaseModel):
    guild: str
    channels: list[str] = []
    authors: list[str] = []
    mentions: list[str] = []
    after: str | None = None
    before: str | None = None


@router.get("/options")
def options(request: Request) -> dict:
    """The servers that can be imported and their channels, as Discord lists them now (a channel that was never imported is there too)."""
    state = request.app.state
    if not state.imports.configured():
        return {"configured": False, "guilds": []}
    api = DiscordAPI(state.settings.discord_api_url, state.settings.discord_token)
    with state.pool.connection() as conn:
        known = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM guilds").fetchall()}
    guilds = []
    try:
        for guild_id in state.settings.followed():
            channels = [{"id": str(c.id), "name": c.name or str(c.id), "kind": c.kind, "empty": c.last_message_id is None}
                        for c in api.channels(guild_id) if c.kind != "thread"]
            guilds.append({"id": str(guild_id), "name": known.get(guild_id, str(guild_id)), "channels": sorted(channels, key=lambda c: c["name"].casefold())})
    except RateLimited as error:
        raise HTTPException(status_code=429, detail=f"Discord demande d'attendre {error.retry_after:.0f} s.") from None
    except DiscordError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    return {"configured": True, "guilds": guilds}


@router.get("")
def status(request: Request) -> dict:
    return request.app.state.imports.status()


@router.post("")
def start(request: Request, body: ImportRequest) -> dict:
    state = request.app.state
    try:
        guild_id = int(body.guild)
    except ValueError:
        raise HTTPException(status_code=422, detail="Serveur : identifiant invalide.") from None
    if guild_id not in state.settings.followed():
        raise HTTPException(status_code=403, detail="Ce serveur n'est pas suivi (le bot n'y est pas, ou il n'est pas dans DINDON_GUILD_IDS) : il ne peut pas être importé.")
    try:
        selection = ImportSelection.parse(body.channels, body.authors, body.mentions, body.after, body.before)
        state.imports.start(guild_id, selection)
    except SelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except NotConfigured:
        raise HTTPException(status_code=409, detail="Aucun jeton ou aucun serveur n'est configuré (DISCORD_TOKEN, DINDON_GUILD_IDS).") from None
    except ImportBusy:
        raise HTTPException(status_code=409, detail="Un import est déjà en cours : attendez qu'il finisse, ou annulez-le.") from None
    except RateLimited as error:
        raise HTTPException(status_code=429, detail=f"Discord demande d'attendre {error.retry_after:.0f} s.") from None
    except DiscordError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    return state.imports.status()


@router.post("/cancel")
def cancel(request: Request) -> dict:
    request.app.state.imports.cancel()
    return request.app.state.imports.status()
