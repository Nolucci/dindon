"""Where Dindon's code can reach out of the machine. The rule (docs/regles-du-bot.md): **nothing leaves except what is posted on the Discord server where the bot is connected,
and, to check what a person says, a short neutral search sentence and the reading of the pages that the search returned.**

This test reads the source (it runs nothing) and lists every module that can open a network connection or run a program. The list must be exactly the one below, each with
its purpose. A new module that reaches out fails this test until somebody adds it here on purpose, which is the moment to ask whether it should.

Level of proof: the structure of the code (what is imported), not its behaviour: a module on the list could still send something it should not; the tests of each say what it sends.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app" / "dindon"

# Modules whose import gives the means to reach out: connections, HTTP clients, mail, files transfer, other programs, and Discord's own library
REACHING = {"socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "httpx", "aiohttp", "websockets", "smtplib", "ftplib", "telnetlib", "xmlrpc.client",
            "subprocess", "pexpect", "paramiko", "discord"}
CALLS = {"urlopen", "create_connection", "open_connection", "create_datagram_endpoint"}

ALLOWED = {
    "analysis/ollama.py": "the AI on this machine or an explicitly configured private helper (DINDON_ANALYSIS_WORKERS)",
    "health.py": "asks the local AI whether it answers",
    "bot/gateway.py": "Discord (Gateway)",
    "bot/rest.py": "Discord (what the bot posts in the thread of a debate)",
    "bot/privacy_commands.py": "Discord (answers to /dindon)",
    "api/activity.py": "Discord (the Activity: trades the code of a member for a token, asks which servers they are in, fetches the pictures of the people the map names from its CDN)",
    "collector/discord_api.py": "Discord (reading the servers it follows)",
    "export/client.py": "Discord (reading the history)",
    "debate/search.py": "THE EXCEPTION: the search services, only to check a claim, with a neutral cleaned sentence",
    "debate/web.py": "THE EXCEPTION: the pages that a search returned, only to check a claim",
}


def reaching(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Attribute | ast.Name):
            name = node.attr if isinstance(node, ast.Attribute) else node.id
            if name in CALLS:
                found.add(f"call:{name}")
            continue
        else:
            continue
        for name in names:
            if any(name == module or name.startswith(module + ".") for module in REACHING):
                found.add(name)
    return found


def test_only_the_modules_on_the_list_can_reach_out_of_the_machine():
    reach = {str(p.relative_to(APP)): sorted(found) for p in sorted(APP.rglob("*.py")) if (found := reaching(p))}
    assert set(reach) == set(ALLOWED), (
        f"modules that can reach out and are not on the list: {sorted(set(reach) - set(ALLOWED))}; "
        f"on the list but no longer reaching out: {sorted(set(ALLOWED) - set(reach))}. See the docstring of this test.")


def test_the_engine_of_the_debates_and_their_rules_reach_nothing_themselves():
    """The part that decides (who may vote, what is a claim, what a verdict is) and the part that talks to Discord are not the part that talks to the Internet."""
    for name in ("debate/rules.py", "debate/store.py", "debate/texts.py", "debate/trust.py", "debate/scope.py", "bot/debate_commands.py"):
        assert reaching(APP / name) == set(), name


def test_the_web_of_the_debates_is_reached_from_one_place_only():
    """The debate code that is allowed to reach the Internet is these two files, and what they offer is used through `scope.Lookup` (which has the budget)."""
    in_debate = {p.name for p in (APP / "debate").glob("*.py") if reaching(p)}
    assert in_debate == {"search.py", "web.py"}
