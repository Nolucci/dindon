"""Inviting the bot to a server, from the interface. Everything needs the session cookie.

Dindon follows the servers of DINDON_GUILD_IDS, or, when that is empty or "all", every server that the bot is in (being
invited is then the decision). With a list, a bot invited to another server is there and nothing of it is recorded. These routes say which servers the bot is in and which of them are followed; what they say
never contains the token (the link holds the public identifier of the application, nothing else).
"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request

from dindon.api.auth import require_session
from dindon.collector.discord_api import DiscordAPI, DiscordError, RateLimited

router = APIRouter(prefix="/api/bot", dependencies=[Depends(require_session)])

# What the bot needs, and no more. To record: see the channels and read their history. For the debates (`/dindon debat`, docs/DEBAT.md): open a public thread,
# write in channels and in threads, and show embeds. It moderates and manages nothing, and does not mention anyone (every message it writes forbids mentions).
# (The Gateway intents, the privileged one for the content of messages included, are set in the Developer Portal, not here.)
PERMISSIONS = {"VIEW_CHANNEL": 1 << 10, "SEND_MESSAGES": 1 << 11, "EMBED_LINKS": 1 << 14, "READ_MESSAGE_HISTORY": 1 << 16,
               "CREATE_PUBLIC_THREADS": 1 << 35, "SEND_MESSAGES_IN_THREADS": 1 << 38}
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"


def invite_url(client_id: str) -> str:
    return f"{AUTHORIZE_URL}?{urlencode({'client_id': client_id, 'scope': 'bot applications.commands', 'permissions': sum(PERMISSIONS.values())})}"


@router.get("/invite")
def invite(request: Request) -> dict:
    """The link that adds the bot to a server, and the servers where the bot already is (followed or not)."""
    settings = request.app.state.settings
    if not settings.discord_token:
        return {"configured": False}
    api = DiscordAPI(settings.discord_api_url, settings.discord_token)
    try:
        application = api.application()
        servers = api.servers()
    except RateLimited as error:
        raise HTTPException(status_code=429, detail=f"Discord demande d'attendre {error.retry_after:.0f} s.") from None
    except DiscordError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    followed = {str(g) for g in settings.followed()}
    return {
        "configured": True,
        "follow_all": settings.follow_all,
        "kind": "bot" if application else "account",
        "application": application,
        "url": invite_url(application["id"]) if application else None,
        "permissions": list(PERMISSIONS),
        "servers": [{**server, "following": server["id"] in followed} for server in sorted(servers, key=lambda s: s["name"].casefold())],
    }
