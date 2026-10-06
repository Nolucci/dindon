"""The installer keeps the token private and preserves automatic server following."""
import importlib.util
import stat
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "host" / "discover-discord.py"
spec = importlib.util.spec_from_file_location("discover_discord", SCRIPT)
discover_discord = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discover_discord)


def test_installer_discovers_application_and_servers_without_printing_the_token(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("DISCORD_TOKEN=secret-token\nDINDON_GUILD_IDS=all\nDISCORD_CLIENT_SECRET=keep-me\n")
    monkeypatch.setattr(discover_discord, "discover", lambda base, token: ("123456", ["456789", "987654"]))

    assert discover_discord.main(env) == 0
    content = env.read_text()
    assert "DISCORD_CLIENT_ID=123456\n" in content
    assert "DINDON_GUILD_IDS=all\n" in content
    assert "DISCORD_CLIENT_SECRET=keep-me\n" in content
    assert content.count("DISCORD_TOKEN=secret-token") == 1
    assert "secret-token" not in capsys.readouterr().out
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_installer_preserves_an_explicit_server_selection(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DISCORD_TOKEN=secret-token\nDINDON_GUILD_IDS=112233\n")
    monkeypatch.setattr(discover_discord, "discover", lambda base, token: ("123456", ["112233", "445566"]))

    assert discover_discord.main(env) == 0
    assert "DINDON_GUILD_IDS=112233\n" in env.read_text()


def test_installer_preserves_an_empty_automatic_server_selection(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DISCORD_TOKEN=secret-token\nDINDON_GUILD_IDS=\n")
    monkeypatch.setattr(discover_discord, "discover", lambda base, token: ("123456", ["112233"]))

    assert discover_discord.main(env) == 0
    assert "DINDON_GUILD_IDS=\n" in env.read_text()


def test_installer_refuses_an_invalid_token_without_echoing_it(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("DISCORD_TOKEN=bad-secret\n")
    def fail(base, token):
        raise ValueError("bad-secret")
    monkeypatch.setattr(discover_discord, "discover", fail)

    assert discover_discord.main(env) == 1
    assert "bad-secret" not in capsys.readouterr().err
    assert env.read_text() == "DISCORD_TOKEN=bad-secret\n"
