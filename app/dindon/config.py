"""Settings, read from environment variables (and from a .env file when running outside Docker)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=value lines. Variables that are already set win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    database_url: str
    db_dir: Path
    host: str
    port: int
    ollama_url: str
    password: str
    inbox_dir: Path
    archive_dir: Path
    # Collection from Discord (off unless there is a token and at least one server)
    discord_token: str
    guild_ids: tuple[int, ...]
    discord_api_url: str
    exporter_threads: str
    poll_seconds: float
    catchup_hour_utc: int
    catchup_days: int
    web_dir: Path
    # The watcher (mode B) can be switched off, to run the live bot (mode C) alone: DINDON_COLLECTOR=off. DINDON_COLLECTOR=catchup keeps
    # only its nightly catch-up (the last days exported again: it fills what a Gateway reconnection missed and shows edits and
    # deletions) and never polls Discord: the right companion of the live bot.
    collector_enabled: bool = True
    collector_catchup_only: bool = False
    # DINDON_GUILD_IDS empty or "all": the bot follows every server that it is in (being invited is the decision). Only with a BOT token:
    # an account is in all the servers of a person, and never follows them all.
    follow_all: bool = False
    # The local models of the analysis (see docs/fonctionnement.md): the vectors of the conversations, and the names of the topics
    embed_model: str = "bge-m3"
    naming_model: str = "qwen3:14b"
    # Who the members can write to about their data (shown by /dindon info and in docs/regles-du-bot.md), and how long messages are
    # kept (DINDON_RETENTION_DAYS, 0 = no limit; see docs/regles-du-bot.md)
    # Dindon's own exporter (export/exporter.py): requests in parallel, and who reacted (one request per reaction): `recent` (the last
    # DINDON_EXPORT_REACTIONS_DAYS days), `all` or `none` (the count of each reaction is always kept)
    export_workers: int = 6
    export_reactions: str = "recent"
    export_reactions_days: int = 30
    retention_days: int = 0
    # The Activity (the map inside a voice channel, api/activity.py): the identifiers of the Discord application. Both empty: no Activity.
    discord_client_id: str = ""
    discord_client_secret: str = field(default="", repr=False)      # a password: never in a log or a trace that prints the settings
    erase_on_removal: bool = False   # the bot is removed from a server: everything held of it is deleted
    # The debates (docs/regles-du-bot.md). DINDON_DEBATE_CHECKS: `off` (default: nothing is read, nothing leaves the machine) or `observe` (the claims of the messages of a debate are checked on the
    # Internet and written to the database, nothing is published). The search services: the key of Google's Fact Check Tools API, and/or the address of a SearXNG that you run.
    debate_checks: str = "off"                # off | observe | answer | live (answer: Dindon answers first and the participants judge; live: + the corrections that sources make by themselves, which need a measured precision: debate/checker.resolve_mode)
    debate_precision: float | None = None     # the precision of « contredit » that tools/measure_claims.py measured: the owner copies it here, it is what unlocks `live`
    debate_min_precision: float = 0.90
    debate_model: str = "qwen3:14b"
    factcheck_api_key: str = field(default="", repr=False)   # a secret: never in a log or a repr
    searxng_url: str = ""


_FOLLOWED: dict = {}  # (api url, token) -> (when, ids): Discord is asked at most once a minute


def _followed(self: "Settings") -> tuple[int, ...]:
    """The servers that Dindon follows: the listed ones, or with `follow_all` every server that the bot is in (asked of Discord, kept a
    minute). An account token never follows all: it gives nothing."""
    if not self.follow_all:
        return self.guild_ids
    import time

    key = (self.discord_api_url, self.discord_token)
    when, ids = _FOLLOWED.get(key, (0.0, ()))
    if time.monotonic() - when > 60:
        from dindon.collector.discord_api import DiscordAPI

        try:
            api = DiscordAPI(self.discord_api_url, self.discord_token)
            ids = tuple(int(s["id"]) for s in api.servers()) if api.resolve_kind() == "bot" else ()
        except Exception:                                  # Discord away: the last answer stands
            pass
        _FOLLOWED[key] = (time.monotonic(), ids)
    return ids


Settings.followed = _followed


def _number(raw: str | None) -> float | None:
    try:
        return float(str(raw).replace(",", ".")) if raw not in (None, "") else None
    except ValueError:
        return None


def load_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    env = os.environ
    database_url = env.get("DATABASE_URL")
    if not database_url:
        # Outside Docker: the database published on 127.0.0.1 by docker-compose.yml
        password = env.get("POSTGRES_PASSWORD", "")
        port = env.get("POSTGRES_PORT", "5432")
        database_url = f"postgresql://dindon:{password}@127.0.0.1:{port}/dindon"
    return Settings(
        database_url=database_url,
        db_dir=Path(env.get("DINDON_DB_DIR", REPO_ROOT / "db")),
        host=env.get("DINDON_HOST", "127.0.0.1"),
        port=int(env.get("DINDON_PORT", "8000")),
        ollama_url=env.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        password=env.get("DINDON_PASSWORD", ""),
        inbox_dir=Path(env.get("DINDON_INBOX", REPO_ROOT / "inbox")),
        archive_dir=Path(env.get("DINDON_ARCHIVE", REPO_ROOT / "archive")),
        discord_token=env.get("DISCORD_TOKEN", ""),
        guild_ids=tuple(int(g) for g in env.get("DINDON_GUILD_IDS", "").replace(" ", "").split(",") if g.isdigit()),
        discord_api_url=env.get("DINDON_DISCORD_API", "https://discord.com/api/v10").rstrip("/"),
        exporter_threads=env.get("DINDON_THREADS", "active"),
        poll_seconds=float(env.get("DINDON_POLL_SECONDS", "30")),
        catchup_hour_utc=int(env.get("DINDON_CATCHUP_HOUR", "3")),
        catchup_days=int(env.get("DINDON_CATCHUP_DAYS", "7")),
        web_dir=Path(env.get("DINDON_WEB_DIR", REPO_ROOT / "web" / "dist")),
        collector_enabled=env.get("DINDON_COLLECTOR", "on").strip().lower() not in ("off", "false", "no", "0"),
        collector_catchup_only=env.get("DINDON_COLLECTOR", "on").strip().lower() == "catchup",
        follow_all=bool(env.get("DISCORD_TOKEN")) and env.get("DINDON_GUILD_IDS", "").strip().lower() in ("", "all", "*"),
        embed_model=env.get("DINDON_EMBED_MODEL", "bge-m3").strip(),
        naming_model=env.get("DINDON_NAMING_MODEL", "qwen3:14b").strip(),
        export_workers=max(1, int(env.get("DINDON_EXPORT_WORKERS", "6") or 6)),
        export_reactions=env.get("DINDON_EXPORT_REACTIONS", "recent").strip().lower() if env.get("DINDON_EXPORT_REACTIONS", "recent").strip().lower() in ("all", "recent", "none") else "recent",
        export_reactions_days=max(1, int(env.get("DINDON_EXPORT_REACTIONS_DAYS", "30") or 30)),
        discord_client_id=env.get("DISCORD_CLIENT_ID", "").strip(),
        discord_client_secret=env.get("DISCORD_CLIENT_SECRET", "").strip(),
        retention_days=max(0, int(env.get("DINDON_RETENTION_DAYS", "0") or 0)),
        erase_on_removal=env.get("DINDON_ERASE_ON_REMOVAL", "").strip().lower() in ("1", "true", "yes", "on", "oui"),
        debate_checks=env.get("DINDON_DEBATE_CHECKS", "").strip().lower() if env.get("DINDON_DEBATE_CHECKS", "").strip().lower() in ("observe", "answer", "live") else "off",
        debate_precision=_number(env.get("DINDON_DEBATE_PRECISION")),
        debate_min_precision=min(1.0, max(0.5, _number(env.get("DINDON_DEBATE_MIN_PRECISION")) or 0.90)),
        debate_model=env.get("DINDON_DEBATE_MODEL", "qwen3:14b").strip() or "qwen3:14b",
        factcheck_api_key=env.get("DINDON_FACTCHECK_API_KEY", "").strip(),
        searxng_url=env.get("DINDON_SEARXNG_URL", "").strip().rstrip("/"),
    )
