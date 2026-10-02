"""Runs the exporter (DiscordChatExporter, an external program) for one channel and returns the files it wrote."""
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path


class ExporterError(Exception):
    pass


class ExporterCancelled(Exception):
    """Somebody asked to stop: the exporter was ended and what it had not finished writing is lost (nothing was imported)."""


class Exporter:
    def __init__(self, command: str, token: str, timeout: float = 3600):
        self.argv = shlex.split(command)
        self.token = token
        self.timeout = timeout

    def export(self, channel_id: int, out_dir: Path, after: int | None = None, threads: str = "none", partition: int | None = None,
               before: int | None = None, message_filter: str | None = None, cancel: threading.Event | None = None) -> list[Path]:
        """Exports one channel in JSON v2 into `out_dir`. `after` and `before` are message ids (only the messages between them),
        `message_filter` is the exporter's filter expression. Setting `cancel` ends the exporter."""
        args = [*self.argv, "export", "-c", str(channel_id), "-f", "Json", "-o", f"{out_dir}/"]
        if after:
            args += ["--after", str(after)]
        if before:
            args += ["--before", str(before)]
        if message_filter:
            args += ["--filter", message_filter]
        if threads != "none":
            args += ["--include-threads", threads]
        if partition:
            args += ["--partition", str(partition)]
        # The token goes through the environment, never on the command line (where `ps` would show it)
        env = {**os.environ, "DISCORD_TOKEN": self.token}
        try:
            process = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError:
            raise ExporterError(f"the exporter was not found: {self.argv[0]} (see exporter/README.md)") from None
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    self._end(process)
                    raise ExporterCancelled() from None
                if time.monotonic() > deadline:
                    self._end(process)
                    raise ExporterError(f"the exporter took more than {self.timeout:.0f}s") from None
        if process.returncode != 0:
            tail = (stderr or stdout or "").strip().replace(self.token, "***")[-300:]
            raise ExporterError(f"the exporter stopped with code {process.returncode}: {tail}")
        return sorted(out_dir.glob("*.json"))

    @staticmethod
    def _end(process: subprocess.Popen) -> None:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
