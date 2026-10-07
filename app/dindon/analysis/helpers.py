"""The administrator's list of private Ollama helpers, stored without credentials."""
import ipaddress
import json
from urllib.parse import urlsplit

from psycopg import Connection
from psycopg.rows import tuple_row

KEY = "analysis_workers"


def validate(url: str) -> str:
    """Only a Tailscale IPv4 address is accepted; the admin UI cannot proxy arbitrary URLs."""
    parsed = urlsplit(url.strip())
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise ValueError("Utilisez une adresse Tailscale IPv4, par exemple http://100.x.y.z:11434") from None
    if (parsed.scheme != "http" or address.version != 4 or address not in ipaddress.ip_network("100.64.0.0/10")
            or not port or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Utilisez uniquement http://<adresse Tailscale IPv4>:<port>, sans chemin ni identifiants")
    return f"http://{address}:{port}"


def load(conn: Connection) -> tuple[str, ...] | None:
    with conn.cursor(row_factory=tuple_row) as cursor:
        row = cursor.execute("SELECT value FROM runtime_settings WHERE key = %s", (KEY,)).fetchone()
    if row is None:
        return None
    return tuple(row[0])


def save(conn: Connection, urls: list[str]) -> tuple[str, ...]:
    if len(urls) > 8:
        raise ValueError("Huit ordinateurs auxiliaires au maximum")
    cleaned = tuple(dict.fromkeys(validate(url) for url in urls))
    conn.execute("""INSERT INTO runtime_settings (key, value) VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""", (KEY, json.dumps(cleaned)))
    return cleaned
