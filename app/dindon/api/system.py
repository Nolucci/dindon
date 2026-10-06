"""The state of the whole system, for the page « Système »: the database, the bot, the collection, the local AI, the servers that are
followed. Everything needs the session cookie. Only counts, states and the ids of servers: never a message, a name of a person or a token.

`checks` is the list of what deserves a look, written for a person (what is wrong, and what to do about it). The page only shows it.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from dindon import __version__
from dindon.health import BOT_SILENT_AFTER
from dindon.analysis.ollama import OllamaError
from dindon.api.auth import require_session
from dindon.api.common import iso
from dindon.clock import utc_now

router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])



def bot_state(row: dict | None, now: datetime) -> dict:
    """The bot as the interface shows it: never seen, silent, disconnected or connected, from its last sign of life."""
    if row is None:
        return {"state": "unknown", "updated_at": None, "age_seconds": None, "data": {}}
    age = (now - row["updated_at"]).total_seconds()
    data = row["data"] or {}
    state = "silent" if age > BOT_SILENT_AFTER else "connected" if data.get("connected") else "disconnected"
    return {"state": state, "updated_at": iso(row["updated_at"]), "age_seconds": round(age), "data": data}


def _bot_checks(bot: dict, collector: dict, followed: list[dict]) -> list[dict]:
    found: list[dict] = []
    data = bot["data"]
    if bot["state"] == "unknown":
        found.append(_check("warning", "Le bot n'a jamais donné signe de vie : son conteneur n'est peut-être pas lancé (`docker compose --profile bot up -d`)."))
    elif bot["state"] == "silent":
        found.append(_check("error", f"Le bot ne donne plus signe de vie depuis {bot['age_seconds'] // 60} min : il est arrêté ou bloqué (`docker compose logs bot`)."))
    elif bot["state"] == "disconnected":
        found.append(_check("warning", "Le bot est déconnecté de Discord ; il se reconnecte seul. Si cela dure, vérifiez le réseau et le jeton."))
    if bot["state"] in ("connected", "disconnected") and data.get("gaps"):
        if not collector.get("enabled"):
            found.append(_check("warning", f"Le bot a changé de session {data['gaps']} fois : les messages écrits pendant ces coupures ne sont pas reçus, "
                                           "et aucun rattrapage n'est actif. Mettez `DINDON_COLLECTOR=catchup` dans .env pour les récupérer chaque nuit."))
        elif not collector.get("last_catchup_at"):
            found.append(_check("info", f"Le bot a changé de session {data['gaps']} fois : les messages manqués reviendront au prochain rattrapage nocturne."))
    if data.get("dropped") or data.get("rejected"):
        found.append(_check("warning", f"Le bot a dû abandonner {data.get('dropped', 0) + data.get('rejected', 0)} messages (base indisponible ou message illisible) : "
                                       "le rattrapage les ramène."))
    for server in followed:
        if bot["state"] in ("connected", "disconnected") and server["id"] not in data.get("ready", []):
            found.append(_check("warning", f"Le bot ne voit pas le serveur {server['id']} : y a-t-il été invité (page « Inviter le bot ») et l'identifiant est-il juste ?"))
    return found


def _collector_checks(collector: dict) -> list[dict]:
    found: list[dict] = []
    if collector.get("enabled") and collector.get("last_error"):
        found.append(_check("warning", f"La collecte signale une erreur : {collector['last_error']}"))
    if collector.get("enabled") and collector.get("failing_channels"):
        found.append(_check("warning", f"{collector['failing_channels']} salon(s) échouent à l'export : ils sont réessayés avec une attente croissante."))
    if collector.get("token_kind") == "account":
        found.append(_check("warning", "Un compte personnel est utilisé en continu : Discord l'interdit et peut le fermer. Un bot est recommandé."))
    return found


def _ollama_checks(ollama: dict) -> list[dict]:
    if not ollama["reachable"]:
        return [_check("warning", "L'IA locale (Ollama) ne répond pas : l'analyse des thèmes ne peut pas démarrer (`open -a Ollama`, ou `ollama serve`).")]
    missing = [m for m, there in ollama["models_ready"].items() if not there]
    return [_check("warning", "Modèles à installer pour l'analyse : " + ", ".join(f"`ollama pull {m}`" for m in missing))] if missing else []


def _check(level: str, text: str) -> dict:
    return {"level": level, "text": text}


def checks_for(*, followed: list[dict], bot: dict, collector: dict, ollama: dict, inbox: dict, wants_bot: bool) -> list[dict]:
    """What deserves a look. `level`: error (something does not work), warning (it works, with a risk), info (to know)."""
    found = _bot_checks(bot, collector, followed) if wants_bot else []
    for server in followed:
        if not server["in_database"]:
            found.append(_check("info", f"Le serveur {server['id']} est suivi, mais aucun message n'y a encore été enregistré : il apparaîtra dans la liste des serveurs "
                                        "au premier message reçu ; son historique se récupère par « Importer »."))
    found += _collector_checks(collector) + _ollama_checks(ollama)
    if inbox["failed"]:
        found.append(_check("warning", f"{inbox['failed']} fichier(s) illisible(s) dans inbox/failed."))
    return found


def _inbox_counts(inbox_dir) -> dict:
    failed_dir = inbox_dir / "failed"
    return {"pending": len(list(inbox_dir.glob("*.json"))) if inbox_dir.is_dir() else 0,
            "failed": len(list(failed_dir.glob("*.json"))) if failed_dir.is_dir() else 0}


def _ollama_state(analysis) -> dict:
    try:
        installed, reachable = analysis.client.models(timeout=2), True
    except OllamaError:
        installed, reachable = [], False
    wanted = (analysis.embed_model, analysis.name_model)
    return {"reachable": reachable, "models": installed, "models_ready": {m: m in installed or f"{m}:latest" in installed for m in wanted}}


@router.get("/system")
def system(request: Request) -> dict:
    state = request.app.state
    settings = state.settings
    now = utc_now()
    inbox = _inbox_counts(settings.inbox_dir)
    with state.pool.connection() as conn:
        guilds = list(settings.followed())
        db = conn.execute(
            """SELECT (SELECT reltuples::bigint FROM pg_class WHERE oid = 'messages'::regclass) AS messages_estimate,
                      (SELECT count(*) FROM users WHERE NOT is_bot) AS people,
                      (SELECT count(*) FROM channels) AS channels, (SELECT count(*) FROM guilds) AS servers,
                      (SELECT count(*) FROM schema_migrations) AS migrations, pg_database_size(current_database()) AS bytes,
                      (SELECT max(imported_at) FROM ingest_runs) AS last_import_at""").fetchone()
        # The page asks every few seconds: a count over a big table is only made while the table is small (the estimate of the planner,
        # kept up to date by autovacuum, is good enough beyond: it says "about")
        approximate = db["messages_estimate"] >= 100_000
        messages = db["messages_estimate"] if approximate else conn.execute("SELECT count(*) AS n FROM messages").fetchone()["n"]
        known = {r["id"]: r for r in conn.execute(
            """SELECT g.id, g.name, (SELECT count(*) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = g.id) AS messages
               FROM guilds g WHERE g.id = ANY(%s)""", (guilds,))}
        bot = bot_state(conn.execute("SELECT updated_at, data FROM service_status WHERE name = 'bot'").fetchone(), now)
    followed = [{"id": str(g), "name": known[g]["name"] if g in known else None, "in_database": g in known,
                 "messages": known[g]["messages"] if g in known else 0, "seen_by_bot": str(g) in bot["data"].get("ready", [])}
                for g in guilds]
    collector = state.collector.status() if state.collector else {"enabled": False}
    ollama = _ollama_state(state.analysis)
    wants_bot = bool(settings.discord_token and (settings.guild_ids or settings.follow_all))
    return {
        "version": __version__, "now": now.isoformat(), "wants_bot": wants_bot,
        "database": {**{k: db[k] for k in ("people", "channels", "servers", "migrations", "bytes")}, "messages": messages, "messages_approximate": approximate,
                     "last_import_at": iso(db["last_import_at"])},
        "bot": bot, "collector": collector, "ollama": ollama,
        "followed": followed, "inbox": inbox,
        "checks": checks_for(followed=followed, bot=bot, collector=collector, ollama=ollama, inbox=inbox, wants_bot=wants_bot),
    }
