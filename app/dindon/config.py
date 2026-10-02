"""Settings, read from environment variables (and from a .env file when running outside Docker)."""
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=value lines. Variables that are already set win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
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
    exporter_path: str
    exporter_threads: str
    poll_seconds: float
    catchup_hour_utc: int
    catchup_days: int
    web_dir: Path


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
        guild_ids=tuple(int(g) for g in env.get("DINDON_GUILD_IDS", "").replace(" ", "").split(",") if g),
        discord_api_url=env.get("DINDON_DISCORD_API", "https://discord.com/api/v10").rstrip("/"),
        exporter_path=env.get("DINDON_EXPORTER", str(REPO_ROOT / "exporter" / "bin" / "DiscordChatExporter.Cli")),
        exporter_threads=env.get("DINDON_THREADS", "active"),
        poll_seconds=float(env.get("DINDON_POLL_SECONDS", "30")),
        catchup_hour_utc=int(env.get("DINDON_CATCHUP_HOUR", "3")),
        catchup_days=int(env.get("DINDON_CATCHUP_DAYS", "7")),
        web_dir=Path(env.get("DINDON_WEB_DIR", REPO_ROOT / "web" / "dist")),
    )
