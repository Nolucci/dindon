"""The Activity: the map inside a Discord voice channel (docs/ACTIVITE.md). The page is `activity.html`, opened by Discord in an iframe.

The one part of the API that is not behind the password of the interface, so it is kept as small as it can be:

* `GET /activity/config`: the id of the application (not a secret), so that the page can start Discord's SDK.
* `POST /activity/token`: the page gives the code that Discord handed it, the server trades it for an access token (that is what the client secret is for).
* `GET /activity/avatar/{id}`: the picture of a person, fetched from Discord's CDN by the server (the page may only load what the application serves) and kept in memory.
* `GET /activity/map`: the people and links of the map, **for a member of the server asked for**: the token is checked with Discord (`/users/@me/guilds`),
  and what comes back is the same as the picture of `/dindon map` (discord_map.py): the same settings, nobody who asked not to be recorded, no message.
  Nothing else of the API can be opened with this token.
"""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from dindon import discord_map, privacy
from dindon.api.common import iso
from dindon.clock import utc_now

router = APIRouter(prefix="/activity")
_MEMBERSHIP_SECONDS, _MEMBERSHIP_MAX = 300, 500
_AVATAR_HOST, _AVATAR_PATHS, _AVATAR_MAX_BYTES, _AVATARS_KEPT = "cdn.discordapp.com", ("/avatars/", "/guilds/", "/embed/avatars/"), 1_000_000, 300
_avatars: dict[tuple[int, int], tuple[bytes, str]] = {}      # (server, person) -> (the picture, its type)
_members: dict[str, tuple[float, set[str]]] = {}          # hash of a token -> (when it was asked, the servers of the person)


class Code(BaseModel):
    code: str = Field(min_length=1, max_length=512)


def _discord(settings, method: str, path: str, *, token: str | None = None, form: dict | None = None) -> dict:
    headers = {"User-Agent": "dindon"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(f"{settings.discord_api_url}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        raise HTTPException(status_code=401, detail="Discord a refusé.") from None


def _on(request: Request):
    settings = request.app.state.settings
    if not (settings.discord_client_id and settings.discord_client_secret):
        raise HTTPException(status_code=404, detail="L'Activité n'est pas configurée.")
    return settings


@router.get("/config")
def config(request: Request) -> dict:
    return {"client_id": _on(request).discord_client_id}


@router.post("/token")
def token(request: Request, body: Code) -> dict:
    settings = _on(request)
    answer = _discord(settings, "POST", "/oauth2/token", form={
        "client_id": settings.discord_client_id, "client_secret": settings.discord_client_secret, "grant_type": "authorization_code", "code": body.code})
    if not isinstance(answer.get("access_token"), str):
        raise HTTPException(status_code=401, detail="Discord a refusé.")
    return {"access_token": answer["access_token"]}


def _member_of(request: Request, access_token: str, guild_id: int) -> bool:
    """Is the person behind this token in this server? Asked to Discord, and remembered a few minutes (the page asks again at each period)."""
    memory = _members
    key = hashlib.sha256(access_token.encode()).hexdigest()
    now = time.monotonic()
    known = memory.get(key)
    if known is None or now - known[0] > _MEMBERSHIP_SECONDS:
        guilds = _discord(request.app.state.settings, "GET", "/users/@me/guilds", token=access_token)
        if len(memory) >= _MEMBERSHIP_MAX:
            memory.clear()
        known = memory[key] = (now, {str(g.get("id")) for g in guilds if isinstance(g, dict)})
    return str(guild_id) in known[1]


def _read(request: Request, guild: int, period: str, authorization: str):
    """What both routes need first: refuses unless the request carries the token of a member of this server (checked with Discord) and a period that exists."""
    _on(request)
    access_token = authorization.removeprefix("Bearer ").strip()
    if not access_token or period not in discord_map.PERIODS:
        raise HTTPException(status_code=401 if not access_token else 422, detail="Demande refusée.")
    if not _member_of(request, access_token, guild):
        raise HTTPException(status_code=403, detail="Vous n'êtes pas membre de ce serveur.")


def _kinds(cfg: dict, wanted: str) -> dict:
    """The settings, with the kinds of exchange that the member ticked on the page, among the ones that the admins allow (never more; none ticked means all that is allowed)."""
    chosen = [k for k in cfg["kinds"] if k in wanted.split(",")]
    return {**cfg, "kinds": chosen or cfg["kinds"]}


def _enabled(conn, guild: int) -> dict:
    cfg = discord_map.load(conn)
    if not cfg["enabled"]:
        raise HTTPException(status_code=403, detail="La carte n'est pas activée sur ce serveur : les administrateurs peuvent le faire depuis l'interface de Dindon.")
    if conn.execute("SELECT 1 FROM guilds WHERE id = %s", (guild,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Serveur inconnu.")
    return cfg


@router.get("/map")
def activity_map(request: Request, guild: int, period: str = Query("30", max_length=3), focus: int | None = None, kinds: str = Query("", max_length=40),
                 authorization: str = Header("")) -> dict:
    _read(request, guild, period, authorization)
    with request.app.state.pool.connection() as conn:
        allowed = _enabled(conn, guild)
        cfg = _kinds(allowed, kinds)
        data = discord_map.collect(conn, guild, discord_map.PERIODS[period][1], focus, cfg)
    meta = {"period": period, "generated_at": iso(utc_now()), "kinds_allowed": allowed["kinds"], "kinds": cfg["kinds"]}
    if data is None:
        return {"meta": meta, "nodes": [], "edges": []}
    shown = discord_map.named(data, cfg)
    with request.app.state.pool.connection() as conn:           # a picture is shown like a name: only for the people that the map names
        pictured = {r["user_id"] for r in conn.execute("SELECT user_id FROM members WHERE guild_id = %s AND user_id = ANY(%s) AND avatar_url IS NOT NULL",
                                                      (guild, sorted(shown)))}
    nodes = [{"id": str(p["id"]), "label": p["label"] if p["id"] in shown else "", "color": p["color"], "influence": round(p["influence"], 4),
              "messages": 0, "last_message_at": None, "community": None, "isolated": False,
              "avatar": f"/activity/avatar/{p['id']}?guild={guild}" if p["id"] in pictured else None} for p in data["people"]]
    edges = [{"source": str(a), "target": str(b), "weight": round(w, 4), "n": 0, "last_at": None, "kinds": {}} for a, b, w in data["links"]]
    return {"meta": meta, "nodes": nodes, "edges": edges}


@router.get("/person/{user_id}")
def activity_person(request: Request, user_id: int, guild: int, period: str = Query("30", max_length=3), focus: int | None = None, kinds: str = Query("", max_length=40),
                    authorization: str = Header("")) -> dict:
    """The card of a person on the map (the period and the person in focus are those of the map being looked at, so that the names are the ones that it shows)."""
    _read(request, guild, period, authorization)
    with request.app.state.pool.connection() as conn:
        cfg = _kinds(_enabled(conn, guild), kinds)
        data = discord_map.collect(conn, guild, discord_map.PERIODS[period][1], focus, cfg)
        card = discord_map.person(conn, guild, user_id, data, cfg) if data else None
    if card is None:
        raise HTTPException(status_code=404, detail="Pas de fiche pour cette personne : les administrateurs n'affichent pas son nom, ou elle n'est pas enregistrée.")
    return card


def _fetch_image(url: str) -> tuple[bytes, str]:
    """A picture from Discord's CDN, small (the page draws it at the size of a point). Only an address of the CDN is ever fetched: it is read from the database, still checked."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _AVATAR_HOST or not parsed.path.startswith(_AVATAR_PATHS):
        raise HTTPException(status_code=404, detail="Pas de photo.")
    small = urllib.parse.urlunparse(parsed._replace(query="size=128"))
    try:
        with urllib.request.urlopen(urllib.request.Request(small, headers={"User-Agent": "dindon"}), timeout=10) as response:
            kind = response.headers.get_content_type()
            body = response.read(_AVATAR_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError):
        raise HTTPException(status_code=404, detail="Pas de photo.") from None
    if not kind.startswith("image/") or len(body) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=404, detail="Pas de photo.")
    return body, kind


def cached_picture(guild: int, user_id: int, url: str) -> tuple[bytes, str]:
    """The picture of a person, from the memory or from Discord's CDN (the picture of `/dindon map` uses it too). Raises HTTPException(404) when there is none."""
    if (guild, user_id) not in _avatars:
        if len(_avatars) >= _AVATARS_KEPT:
            _avatars.clear()
        _avatars[(guild, user_id)] = _fetch_image(url)
    return _avatars[(guild, user_id)]


@router.get("/avatar/{user_id}")
def avatar(request: Request, user_id: int, guild: int, authorization: str = Header("")) -> Response:
    """The picture of a person, for a member of the server. As for the names: nothing when the admins show no name, and nothing for somebody who asked not to be recorded."""
    _read(request, guild, "30", authorization)
    with request.app.state.pool.connection() as conn:
        cfg = _enabled(conn, guild)
        if cfg["names"] < 1 or user_id in privacy.blocked_ids(conn):
            raise HTTPException(status_code=404, detail="Pas de photo.")
        row = conn.execute("SELECT avatar_url FROM members WHERE guild_id = %s AND user_id = %s", (guild, user_id)).fetchone()
    if row is None or not row["avatar_url"]:
        raise HTTPException(status_code=404, detail="Pas de photo.")
    body, kind = cached_picture(guild, user_id, row["avatar_url"])
    return Response(body, media_type=kind, headers={"Cache-Control": "private, max-age=3600"})
