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
    )
