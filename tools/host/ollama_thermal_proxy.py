#!/usr/bin/env python3
"""Linux Ollama relay with local CPU temperature protection. See docs/ordinateurs-analyse.md."""
from __future__ import annotations

import argparse
import http.client
import json
import logging
import socket
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("ollama-thermal")
CPU_DRIVERS = {"coretemp", "k10temp", "zenpower", "cpu_thermal", "k8temp"}


class Sensor:
    def __init__(self, path: Path, ceiling: float):
        self.path, self.ceiling = path, ceiling

    def read(self) -> float:
        value = float(self.path.read_text().strip()) / 1000
        if not -20 <= value <= 150:
            raise ValueError("température invalide")
        return value


def sensors(root: Path, ceiling: float) -> list[Sensor]:
    found = []
    for chip in root.glob("hwmon*"):
        try:
            driver = (chip / "name").read_text().strip()
        except OSError:
            continue
        if driver not in CPU_DRIVERS:
            continue
        for path in chip.glob("temp*_input"):
            threshold = ceiling
            critical = path.with_name(path.name.replace("_input", "_crit"))
            try:
                limit = float(critical.read_text().strip()) / 1000
                if 20 < limit <= 150:
                    threshold = min(threshold, limit - 5)
            except (OSError, ValueError):
                pass
            found.append(Sensor(path, threshold))
    return found


class Guard:
    def __init__(self, readings: list[Sensor], resume: float):
        self.readings, self.resume = readings, resume
        self.blocked = threading.Event()
        self._lock = threading.Lock()
        self.reason = ""
        self.refresh()

    def refresh(self) -> None:
        with self._lock:
            before = self.blocked.is_set()
            try:
                values = [(sensor.read(), sensor.ceiling) for sensor in self.readings]
                if not values:
                    raise ValueError("aucun capteur CPU")
                if any(temp >= ceiling for temp, ceiling in values):
                    self.reason = "Ordinateur retiré : température CPU trop élevée"
                    self.blocked.set()
                elif before and any(temp > min(self.resume, ceiling - 10) for temp, ceiling in values):
                    pass  # avoid switching on/off near the threshold
                else:
                    self.reason = ""
                    self.blocked.clear()
            except (OSError, ValueError):
                self.reason = "Ordinateur retiré : température CPU indisponible"
                self.blocked.set()
            if self.blocked.is_set() != before:
                log.warning(self.reason or "Température CPU revenue à un niveau acceptable")

    def monitor(self, stop: threading.Event) -> None:
        while not stop.wait(0.5):
            self.refresh()


class ThermalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, guard: Guard, upstream_port: int):
        self.guard, self.upstream_port = guard, upstream_port
        super().__init__(address, Relay)


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # never log conversation contents

    def reply(self, status: int, raw: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(raw)

    def blocked(self) -> None:
        self.reply(503, json.dumps({"error": self.server.guard.reason}).encode())

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self) -> None:
        # Only the API calls needed by Dindon are exposed.
        if (self.command, self.path) not in {("GET", "/api/tags"), ("POST", "/api/embed"), ("POST", "/api/chat")}:
            self.reply(404, b'{"error":"Endpoint unavailable"}')
            return
        self.server.guard.refresh()
        if self.server.guard.blocked.is_set():
            self.blocked()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.reply(400, b'{"error":"Invalid Content-Length"}')
            return
        if not 0 <= length <= 16 * 1024 * 1024:
            self.reply(413, b'{"error":"Request too large"}')
            return
        self.connection.settimeout(10)
        body = self.rfile.read(length) if length else None
        connection = http.client.HTTPConnection("127.0.0.1", self.server.upstream_port, timeout=5)
        finished, interrupted = threading.Event(), threading.Event()
        transport = [None]

        def watch():
            while not finished.wait(0.1):
                if self.server.guard.blocked.is_set():
                    interrupted.set()
                    with suppress(OSError):
                        active = connection.sock or transport[0]
                        if active:
                            active.shutdown(socket.SHUT_RDWR)
                    connection.close()
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            connection.request(self.command, self.path, body, {"Content-Type": "application/json"})
            transport[0] = connection.sock
            if connection.sock:
                connection.sock.settimeout(600)
            response = connection.getresponse()
            raw = response.read()
            if interrupted.is_set() or self.server.guard.blocked.is_set():
                self.blocked()
            else:
                self.reply(response.status, raw)
        except (OSError, http.client.HTTPException):
            if interrupted.is_set() or self.server.guard.blocked.is_set():
                self.blocked()
            else:
                self.reply(502, b'{"error":"Ollama unavailable"}')
        finally:
            finished.set()
            connection.close()
            watcher.join(timeout=0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--upstream-port", type=int, default=11434)
    parser.add_argument("--max-temperature", type=float, default=85)
    parser.add_argument("--resume-temperature", type=float, default=75)
    args = parser.parse_args()
    if not 20 <= args.resume_temperature < args.max_temperature <= 100:
        parser.error("Les seuils doivent respecter 20 ≤ reprise < arrêt ≤ 100 °C")
    if args.port == args.upstream_port:
        parser.error("Le relais et Ollama doivent utiliser des ports différents")
    logging.basicConfig(level=logging.INFO)
    readings = sensors(Path("/sys/class/hwmon"), args.max_temperature)
    if not readings:
        parser.error("Aucun capteur CPU reconnu. Une VM peut ne pas exposer les capteurs de son hôte.")
    guard = Guard(readings, args.resume_temperature)
    stop = threading.Event()
    monitor = threading.Thread(target=guard.monitor, args=(stop,), daemon=True)
    monitor.start()
    try:
        with ThermalServer(("127.0.0.1", args.port), guard, args.upstream_port) as server:
            log.info("Relais Ollama sur 127.0.0.1:%s ; %s capteurs CPU", args.port, len(readings))
            server.serve_forever()
    finally:
        stop.set()
        monitor.join(timeout=1)


if __name__ == "__main__":
    main()
