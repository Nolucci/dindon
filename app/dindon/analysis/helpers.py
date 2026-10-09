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


SHARES_KEY = "analysis_shares"
LOCAL = "local"                                   # the server itself, in the shares
NAMES_KEY = "analysis_worker_names"


def load_names(conn: Connection) -> dict[str, str]:
    with conn.cursor(row_factory=tuple_row) as cursor:
        row = cursor.execute("SELECT value FROM runtime_settings WHERE key = %s", (NAMES_KEY,)).fetchone()
    return dict(row[0]) if row else {}


def save_name(conn: Connection, key: str, name: str, known: list[str]) -> tuple[str, str]:
    """Change a label without recreating the pool or changing its work shares."""
    key = LOCAL if key == LOCAL else validate(key)
    if key not in {LOCAL, *known}:
        raise ValueError("Cet ordinateur n’est pas configuré")
    name = " ".join(name.split())
    if len(name) > 80:
        raise ValueError("Le nom doit contenir au maximum 80 caractères")
    if name:
        conn.execute("""INSERT INTO runtime_settings (key, value) VALUES (%s, %s::jsonb)
                        ON CONFLICT (key) DO UPDATE SET value = runtime_settings.value || excluded.value, updated_at = now()""",
                     (NAMES_KEY, json.dumps({key: name})))
    else:
        conn.execute("UPDATE runtime_settings SET value = value - %s, updated_at = now() WHERE key = %s", (key, NAMES_KEY))
    return key, name


def with_names(rows: list[dict], names: dict[str, str]) -> list[dict]:
    return [{**row, "name": names[key]} if (key := LOCAL if row.get("local") else row["url"]) in names else dict(row) for row in rows]


def load_shares(conn: Connection) -> dict[str, int] | None:
    """The percentage of the work given to each computer ("local" is the server); None: split equally."""
    with conn.cursor(row_factory=tuple_row) as cursor:
        row = cursor.execute("SELECT value FROM runtime_settings WHERE key = %s", (SHARES_KEY,)).fetchone()
    return None if row is None else dict(row[0])


def clear_shares(conn: Connection) -> None:
    conn.execute("DELETE FROM runtime_settings WHERE key = %s", (SHARES_KEY,))


def save_shares(conn: Connection, shares: dict[str, int], known: list[str]) -> dict[str, int]:
    """Percentages for the server and the computers in `known`; they must add up to 100."""
    if set(shares) != {LOCAL, *known}:
        raise ValueError("La répartition doit nommer le serveur et chaque ordinateur configuré")
    if any(not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100 for v in shares.values()):
        raise ValueError("Chaque part est un nombre entier de 0 à 100")
    if sum(shares.values()) != 100:
        raise ValueError("Le total des parts doit faire 100 %")
    conn.execute("""INSERT INTO runtime_settings (key, value) VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""", (SHARES_KEY, json.dumps(shares)))
    return shares
