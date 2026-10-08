"""The check before the bot runs for real on a server: `dindon preflight`.

It answers, in words, one question: **is it reasonable to leave the bot on this server now?** Each check is `ok`, `info`, `warn` (it works, but think about it) or
`fail` (do not go on before this is fixed), with what to do about it. It reads the configuration and asks Discord and the database; it **never writes anything**, never
posts a message, and never prints the token, a password or a message.

Four groups: the configuration (passwords, who to write to, how long data is kept, which servers are followed), Discord (the token, what the bot may do and
see, its permissions in each server, its commands), the database and the machine (migrations, free disk, the files), and what is running now (the bot's sign of life).
"""
from __future__ import annotations

import shutil
import urllib.parse
from dataclasses import dataclass

import psycopg

from dindon.collector.discord_api import DiscordAPI, DiscordError, RateLimited
from dindon.config import Settings
from dindon.health import bot_is_alive

# Discord permission bits (https://discord.com/developers/docs/topics/permissions)
ADMINISTRATOR, VIEW_CHANNEL, READ_MESSAGE_HISTORY = 1 << 3, 1 << 10, 1 << 16
# What `/dindon debat` needs on top of recording (api/invite.py): the bot works without, the debates do not
DEBATE_PERMISSIONS = {1 << 35: "créer des fils publics", 1 << 11: "envoyer des messages", 1 << 38: "envoyer des messages dans les fils", 1 << 14: "intégrer des liens"}
DANGEROUS = {1 << 1: "expulser des membres", 1 << 2: "bannir des membres", 1 << 5: "gérer le serveur", 1 << 28: "gérer les rôles", 1 << 13: "gérer les messages",
             1 << 29: "gérer les webhooks", 1 << 4: "gérer les salons"}
MESSAGE_CONTENT_FLAGS = (1 << 18) | (1 << 19)          # the « Message Content Intent », verified or not yet
WEAK_PASSWORDS = {"", "demo", "test", "password", "motdepasse", "dindon", "postgres", "admin", "changeme", "correct horse", "123456", "azerty"}
MIN_FREE_GB = 5
MAX_CLOCK_OFFSET = 30  # seconds


@dataclass(frozen=True)
class Check:
    level: str          # "ok", "info", "warn" or "fail"
    area: str
    text: str


def _ok(area: str, text: str) -> Check:
    return Check("ok", area, text)


def _info(area: str, text: str) -> Check:
    return Check("info", area, text)


def _warn(area: str, text: str) -> Check:
    return Check("warn", area, text)


def _fail(area: str, text: str) -> Check:
    return Check("fail", area, text)


def _password_checks(label: str, password: str, minimum: int) -> list[Check]:
    if password.strip().lower() in WEAK_PASSWORDS:
        return [_fail("Configuration", f"{label} : c'est un mot de passe d'exemple ou vide. Choisissez-en un long et unique dans .env.")]
    if len(password) < minimum:
        return [_warn("Configuration", f"{label} : {len(password)} caractères, c'est court. {minimum} ou plus, avec des mots différents, c'est mieux.")]
    return [_ok("Configuration", f"{label} : {len(password)} caractères, pas un mot de passe d'exemple.")]


def check_configuration(settings: Settings) -> list[Check]:
    """What .env says: passwords, retention, which servers are followed."""
    found = _password_checks("Mot de passe de l'interface (DINDON_PASSWORD)", settings.password, 12)
    database_password = urllib.parse.urlparse(settings.database_url).password or ""
    found += _password_checks("Mot de passe de la base (POSTGRES_PASSWORD)", urllib.parse.unquote(database_password), 12)
    if not settings.discord_token:
        found.append(_fail("Configuration", "Aucun jeton Discord (DISCORD_TOKEN) : le bot ne peut pas se connecter."))
    if settings.retention_days:
        found.append(_ok("Configuration", f"Durée de conservation : {settings.retention_days} jours, puis les messages sont supprimés."))
    else:
        found.append(_warn("Configuration", "Durée de conservation illimitée (DINDON_RETENTION_DAYS=0) : rien n'est supprimé avec le temps. Décidez d'une durée, et dites-la aux membres."))
    if settings.follow_all:
        found.append(_warn("Configuration", "Le bot suit **tous** les serveurs où il se trouve (DINDON_GUILD_IDS vide ou « all »). En production, listez les identifiants des serveurs voulus : "
                                            "un serveur ajouté par erreur serait enregistré."))
    elif settings.guild_ids:
        found.append(_ok("Configuration", f"Le bot ne suit que {len(settings.guild_ids)} serveur(s) listé(s) : {', '.join(str(g) for g in settings.guild_ids)}."))
    return found


def check_discord(settings: Settings, api: DiscordAPI | None = None) -> list[Check]:
    """What Discord says about the token, the application and each server (read only)."""
    area = "Discord"
    if not settings.discord_token:
        return []
    api = api or DiscordAPI(settings.discord_api_url, settings.discord_token)
    try:
        kind = api.resolve_kind()
        if kind != "bot":
            return [_fail(area, "Le jeton est celui d'un **compte personnel** : Discord interdit de l'automatiser et peut fermer le compte. Utilisez le jeton d'un bot.")]
        application = api.application_raw()
        servers = api.server_details()
    except DiscordError as error:
        return [_fail(area, str(error))]
    except RateLimited as error:
        return [_warn(area, f"Discord demande d'attendre ({error}) : relancez dans un instant.")]
    except OSError as error:
        return [_fail(area, f"Discord ne répond pas ({type(error).__name__}) : vérifiez le réseau.")]
    found = [_ok(area, f"Le jeton est celui d'un bot (« {application.get('name') or '?'} »).")]
    if int(application.get("flags") or 0) & MESSAGE_CONTENT_FLAGS:
        found.append(_ok(area, "« Message Content Intent » activé : le bot reçoit le texte des messages."))
    else:
        found.append(_fail(area, "« Message Content Intent » **désactivé** : les messages arriveraient vides. Portail développeur > Bot > Privileged Gateway Intents."))
    if application.get("bot_public"):
        found.append(_warn(area, "Le bot est **public** : n'importe qui peut l'ajouter à son serveur (et il serait suivi si tous les serveurs le sont). Portail développeur > Bot > décochez « Public Bot »."))
    else:
        found.append(_ok(area, "Le bot est privé : seul son propriétaire peut l'ajouter à un serveur."))
    found += _server_checks(settings, api, servers)
    found += _command_checks(api, str(application.get("id", "")))
    offset = api.clock_offset()
    if offset is None:
        found.append(_info(area, "L'heure de cette machine n'a pas pu être comparée à celle de Discord."))
    elif abs(offset) > MAX_CLOCK_OFFSET:
        found.append(_warn(area, f"L'horloge de cette machine est décalée de {offset:+.0f} s par rapport à Discord : réglez l'heure automatique."))
    else:
        found.append(_ok(area, "L'horloge de cette machine est à l'heure."))
    return found


def _server_checks(settings: Settings, api: DiscordAPI, servers: list[dict]) -> list[Check]:
    area = "Serveurs"
    if not servers:
        return [_fail(area, "Le bot n'est dans aucun serveur : invitez-le (page « Inviter le bot »).")]
    found: list[Check] = []
    listed = set(settings.guild_ids)
    for server in servers:
        label = f"« {server['name']} » ({server['id']})"
        followed = settings.follow_all or int(server["id"]) in listed
        if not followed:
            found.append(_info(area, f"{label} : le bot y est mais ne le suit pas (pas dans DINDON_GUILD_IDS)."))
            continue
        found.append(_info(area, f"{label} : suivi."))
        found += _permission_checks(label, server)
        try:
            counts = api.server_counts(int(server["id"]))
            found.append(_info(area, f"{label} : environ {counts['members']} membres, {counts['online']} en ligne."))
        except (DiscordError, RateLimited, OSError):
            found.append(_info(area, f"{label} : taille non lue."))
    missing = listed - {int(s["id"]) for s in servers}
    for guild_id in sorted(missing):
        found.append(_fail(area, f"Le serveur {guild_id} est dans DINDON_GUILD_IDS mais le bot n'y est pas : l'a-t-on invité, et l'identifiant est-il juste ?"))
    return found


def _permission_checks(label: str, server: dict) -> list[Check]:
    area = "Serveurs"
    if not server["has_permissions"]:
        return [_info(area, f"{label} : permissions non communiquées par Discord.")]
    bits = server["permissions"]
    found: list[Check] = []
    if bits & ADMINISTRATOR:
        found.append(_warn(area, f"{label} : le bot est **administrateur**. Il n'a besoin que de voir les salons et lire l'historique : retirez-lui ce rôle."))
    else:
        if not bits & VIEW_CHANNEL:
            found.append(_fail(area, f"{label} : le bot n'a pas le droit de **voir les salons**."))
        if not bits & READ_MESSAGE_HISTORY:
            found.append(_fail(area, f"{label} : le bot n'a pas le droit de **lire l'historique** (le rattrapage nocturne en a besoin)."))
        extra = [name for bit, name in DANGEROUS.items() if bits & bit]
        if extra:
            found.append(_warn(area, f"{label} : le bot peut aussi {', '.join(extra)}. Il n'en a pas besoin : retirez ces droits."))
        if bits & VIEW_CHANNEL and bits & READ_MESSAGE_HISTORY and not extra:
            found.append(_ok(area, f"{label} : droits justes (voir les salons, lire l'historique, rien d'autre de sensible)."))
        if not bits & (1 << 49):
            found.append(_info(area, f"{label} : autorisez « Envoyer des sondages » pour publier les sondages des débats."))
        cannot = [name for bit, name in DEBATE_PERMISSIONS.items() if not bits & bit]
        if cannot:
            found.append(_info(area, f"{label} : `/dindon debat` ne marchera pas, le bot ne peut pas {', ni '.join(cannot)}. Pour les débats, invitez-le de nouveau avec le lien de l'interface."))
        else:
            found.append(_ok(area, f"{label} : le bot peut ouvrir des débats (fils, messages)."))
    return found


def _command_checks(api: DiscordAPI, application_id: str) -> list[Check]:
    area = "Discord"
    try:
        names = api.commands(application_id)
    except (DiscordError, RateLimited, OSError):
        return [_info(area, "La liste des commandes `/dindon` n'a pas pu être lue.")]
    if "dindon" in names:
        return [_ok(area, "La commande `/dindon` (info, stop, effacer…) est enregistrée : les membres peuvent exercer leurs droits.")]
    return [_fail(area, "La commande `/dindon` n'est pas enregistrée : les membres ne pourraient pas s'arrêter ni se faire effacer. Le bot l'enregistre à son démarrage "
                        "(il faut le scope `applications.commands` à l'invitation).")]


def check_database(settings: Settings, conn: psycopg.Connection) -> list[Check]:
    """The database, the machine's disk, and the folders of files."""
    area = "Données"
    found: list[Check] = []
    from dindon.migrate import pending

    waiting = pending(conn, settings.db_dir)
    found.append(_ok(area, "La base est à jour (toutes les migrations sont appliquées).") if not waiting
                 else _fail(area, f"Migrations pas encore appliquées : {', '.join(waiting)}. Elles s'appliquent au démarrage de l'application."))
    row = conn.execute("SELECT (SELECT count(*) FROM messages), (SELECT count(*) FROM privacy_subjects), (SELECT count(*) FROM claims)").fetchone()
    found.append(_info(area, f"{row[0]} messages enregistrés ; {row[1]} personne(s) ont demandé à ne plus l'être ; {row[2]} positions déduites par l'IA."))
    if row[2]:
        found.append(_warn(area, "Des positions politiques de personnes sont déjà déduites : donnée sensible (RGPD, art. 9). Vérifiez que ces personnes sont informées."))
    free = shutil.disk_usage(settings.archive_dir if settings.archive_dir.exists() else ".").free / 1e9
    found.append(_ok(area, f"Place libre : {free:.0f} Go.") if free >= MIN_FREE_GB else _warn(area, f"Il ne reste que {free:.1f} Go de libre : un gros serveur les remplit vite."))
    for name, folder in (("inbox", settings.inbox_dir), ("archive", settings.archive_dir)):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".preflight"
            probe.write_text("")
            probe.unlink()
        except OSError:
            found.append(_fail(area, f"Le dossier {name} ({folder}) n'est pas inscriptible : l'application ne pourrait pas y ranger les fichiers."))
        else:
            found.append(_ok(area, f"Le dossier {name} est inscriptible."))
    return found


def check_runtime(settings: Settings, conn: psycopg.Connection) -> list[Check]:
    """What is running now: the bot's sign of life."""
    area = "Marche"
    if bot_is_alive(conn):
        data = conn.execute("SELECT data FROM service_status WHERE name = 'bot'").fetchone()[0] or {}
        found = [_ok(area, f"Le bot est vivant et connecté à Discord ({data.get('sessions', '?')} session(s), {data.get('gaps', 0)} coupure(s)).")]
        if data.get("gaps"):
            found.append(_info(area, "Des coupures ont eu lieu : les messages écrits pendant ce temps reviennent au prochain rattrapage nocturne (DINDON_COLLECTOR=catchup)."))
        return found
    return [_warn(area, "Le bot ne donne pas signe de vie (arrêté, ou pas encore lancé). C'est normal avant la première mise en route : `docker compose --profile bot up -d`.")]


def check_debates(settings: Settings) -> list[Check]:
    """The checking of claims in the debates (docs/regles-du-bot.md): what is configured, whether the local model is there, and whether the public corrections are really allowed. Read only: the
    only thing asked is the list of the local model's models, on this machine."""
    area = "Débats"
    if settings.debate_checks == "off":
        return [_info(area, "La vérification des affirmations est désactivée (DINDON_DEBATE_CHECKS=off) : aucun message de débat n'est lu pour une vérification.")]
    from dindon.analysis.ollama import Ollama, OllamaError
    from dindon.debate.checker import resolve_mode

    found: list[Check] = []
    mode, why = resolve_mode(settings)
    services = [name for name, on in (("l'API Fact Check Tools de Google", bool(settings.factcheck_api_key)), ("un SearXNG", bool(settings.searxng_url))) if on]
    if not services and settings.debate_checks == "observe":
        found.append(_fail(area, "DINDON_DEBATE_CHECKS=observe est activé mais aucun service de recherche n'est donné (DINDON_FACTCHECK_API_KEY ou DINDON_SEARXNG_URL) : rien ne sera vérifié."))
    elif not services:
        found.append(_warn(area, "Dindon répond avec son IA locale seulement : aucun service de recherche n'est donné (DINDON_FACTCHECK_API_KEY ou DINDON_SEARXNG_URL), il ne pourra pas chercher sur "
                                 "Internet quand les participants jugeront sa réponse invalide. La vérification n'envoie rien à Internet."))
    else:
        found.append(_warn(area, f"La vérification est ACTIVE : une phrase de recherche neutre sera envoyée à {' et à '.join(services)}, et des pages de sources de confiance seront lues. "
                                 "Les membres en sont informés par /dindon info et dans chaque débat vérifié. La vérification n'envoie rien d'autre à Internet."))
    try:
        if not Ollama(settings.ollama_url).has(settings.debate_model):
            found.append(_fail(area, f"Le modèle {settings.debate_model} n'est pas installé dans Ollama : `ollama pull {settings.debate_model}`."))
        else:
            found.append(_ok(area, f"Le modèle {settings.debate_model} est installé (c'est lui qui lit les messages, sur cette machine)."))
    except OllamaError:
        found.append(_fail(area, f"Ollama ne répond pas à {settings.ollama_url} : sans lui, les messages ne sont pas lus (ils attendent)."))
    if mode == "live":
        found.append(_warn(area, f"Les CORRECTIONS PUBLIQUES sont actives (précision mesurée {settings.debate_precision:.2f}, seuil {settings.debate_min_precision:.2f}) : Dindon répond en public quand des sources de confiance "
                                 "contredisent une affirmation, en plus de ses réponses sans Internet."))
    elif mode == "answer":
        found.append(_warn(area, "Dindon RÉPOND D'ABORD, sans Internet, quand il est certain qu'une affirmation est fausse : sa réponse est publique, sans source, et peut être fausse ; les participants la jugent "
                                 "(Valide / Invalide) et il ne cherche sur Internet que s'il y a plus d'Invalide." + (f" Les corrections par les sources seules ne sont PAS actives : {why}." if why else "")))
    else:
        found.append(_ok(area, "Mode observation : les vérifications sont notées dans la base (`dindon debate-report`), rien n'est publié."))
    return found


def run_preflight(settings: Settings) -> list[Check]:
    """Every check, in the order that a person reads them. A part that cannot run becomes a `fail` of its own instead of stopping the others."""
    found = check_configuration(settings) + check_debates(settings)
    found += check_discord(settings)
    try:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            found += check_database(settings, conn)
            found += check_runtime(settings, conn)
    except psycopg.OperationalError:
        found.append(_fail("Données", "La base de données ne répond pas : est-elle démarrée (`docker compose up -d db`) et le mot de passe est-il le bon ?"))
    return found


def render(checks: list[Check]) -> str:
    marks = {"ok": "[ok]  ", "info": "[info]", "warn": "[à voir]", "fail": "[BLOQUANT]"}
    lines, area = [], None
    for check in checks:
        if check.area != area:
            area = check.area
            lines += ["", f"== {area}"]
        lines.append(f"  {marks[check.level]} {check.text}")
    fails, warns = sum(c.level == "fail" for c in checks), sum(c.level == "warn" for c in checks)
    if fails:
        verdict = f"NON : {fails} point(s) bloquant(s) à régler avant la mise en production."
    elif warns:
        verdict = f"PRESQUE : rien de bloquant, {warns} point(s) à décider."
    else:
        verdict = "OUI : tout est en ordre."
    return "\n".join(lines) + f"\n\nVerdict : {verdict}\n"
