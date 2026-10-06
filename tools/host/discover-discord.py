"""Fill public Discord IDs in .env from a bot token, without printing the token."""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def values(lines: list[str]) -> dict[str, str]:
    return dict(line.rstrip("\n").split("=", 1) for line in lines if line and not line.startswith("#") and "=" in line)


def request(base: str, token: str, route: str):
    call = urllib.request.Request(base + route, headers={"Authorization": f"Bot {token}", "User-Agent": "dindon-installer"})
    with urllib.request.urlopen(call, timeout=15) as response:
        return json.load(response)


def discover(base: str, token: str) -> tuple[str, list[str]]:
    application = request(base, token, "/oauth2/applications/@me")
    app_id = str(application.get("id", ""))
    if not app_id.isdigit():
        raise ValueError("Discord n’a pas renvoyé d’identifiant d’application valide")
    guilds: list[str] = []
    after = ""
    for _ in range(25):
        page = request(base, token, f"/users/@me/guilds?limit=200{after}")
        if not isinstance(page, list):
            raise ValueError("Discord n’a pas renvoyé la liste des serveurs")
        ids = [str(g.get("id", "")) for g in page]
        if any(not guild_id.isdigit() for guild_id in ids):
            raise ValueError("Discord a renvoyé un identifiant de serveur invalide")
        guilds.extend(ids)
        if len(page) < 200:
            break
        after = f"&after={ids[-1]}"
    return app_id, guilds


def set_values(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text().splitlines(keepends=True)
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else ""
        if key in updates:
            if key not in seen:
                out.append(f"{key}={updates[key]}\n")
                seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}\n")
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".dindon-env-", delete=False) as tmp:
        os.chmod(tmp.name, 0o600)
        tmp.writelines(out)
        name = tmp.name
    os.replace(name, path)


def main(path: Path) -> int:
    lines = path.read_text().splitlines(keepends=True)
    env = values(lines)
    token = env.get("DISCORD_TOKEN", "")
    if not token:
        print("Jeton Discord absent dans .env.", file=sys.stderr)
        return 1
    base = env.get("DINDON_DISCORD_API", "https://discord.com/api/v10").rstrip("/")
    try:
        app_id, guilds = discover(base, token)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as error:
        print(f"Impossible de lire la configuration du bot sur Discord ({type(error).__name__}). Vérifiez le jeton et le réseau.", file=sys.stderr)
        return 1
    updates = {}
    if not env.get("DISCORD_CLIENT_ID"):
        updates["DISCORD_CLIENT_ID"] = app_id
    if env.get("DINDON_GUILD_IDS", "") in ("", "all"):
        updates["DINDON_GUILD_IDS"] = ",".join(guilds) if guilds else "all"
    if updates:
        set_values(path, updates)
    print(f"Application Discord identifiée ; {len(guilds)} serveur(s) actuellement accessibles au bot.")
    if not guilds:
        print("Aucun serveur pour l’instant : le bot suivra les serveurs où il sera invité.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
