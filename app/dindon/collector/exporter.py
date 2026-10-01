"""Runs the exporter (DiscordChatExporter, an external program) for one channel and returns the files it wrote."""
import os
import shlex
import subprocess
from pathlib import Path


class ExporterError(Exception):
    pass


class Exporter:
    def __init__(self, command: str, token: str, timeout: float = 3600):
        self.argv = shlex.split(command)
        self.token = token
        self.timeout = timeout

    def export(self, channel_id: int, out_dir: Path, after: int | None = None, threads: str = "none", partition: int | None = None) -> list[Path]:
        """Exports one channel in JSON v2 into `out_dir`. `after` is a message id: only newer messages."""
        args = [*self.argv, "export", "-c", str(channel_id), "-f", "Json", "-o", f"{out_dir}/"]
        if after:
            args += ["--after", str(after)]
        if threads != "none":
            args += ["--include-threads", threads]
        if partition:
            args += ["--partition", str(partition)]
        # The token goes through the environment, never on the command line (where `ps` would show it)
        env = {**os.environ, "DISCORD_TOKEN": self.token}
        try:
            done = subprocess.run(args, env=env, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            raise ExporterError(f"the exporter was not found: {self.argv[0]} (see exporter/README.md)") from None
        except subprocess.TimeoutExpired:
            raise ExporterError(f"the exporter took more than {self.timeout:.0f}s") from None
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or "").strip().replace(self.token, "***")[-300:]
            raise ExporterError(f"the exporter stopped with code {done.returncode}: {tail}")
        return sorted(out_dir.glob("*.json"))
