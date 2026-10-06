"""Tests never leave this machine: no automated test can contact the real Discord, or anything else on the internet."""
import socket
import subprocess
import sys


def test_the_tests_cannot_reach_anything_but_this_machine(blocked_attempts):
    for host in ("gateway.discord.gg", "discord.com"):
        try:
            socket.getaddrinfo(host, 443)
            raise AssertionError(f"the name {host} was resolved")
        except OSError as error:
            assert "blocked" in str(error)
    try:
        socket.create_connection(("192.0.2.1", 443), timeout=1)  # a documentation address: nobody lives there
        raise AssertionError("a connection to another machine was attempted")
    except OSError as error:
        assert "blocked" in str(error)
    assert len(blocked_attempts) == 3
    blocked_attempts.clear()  # these were expected: the rule below must not count them against this test
    with socket.socket() as server:  # this machine is still reachable
        server.bind(("127.0.0.1", 0))
        server.listen()
        socket.create_connection(server.getsockname(), timeout=2).close()


def test_the_core_of_the_bot_does_not_import_discord_py():
    """discord.py is isolated in one module (the connection): the adapter and the engine work without it."""
    code = ("import sys, dindon.bot.adapter, dindon.bot.runner; "
            "bad = sorted(m for m in sys.modules if m == 'discord' or m.startswith('discord.')); "
            "assert not bad, 'imported: ' + ', '.join(bad[:3])")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[-300:]
