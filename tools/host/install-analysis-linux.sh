#!/usr/bin/env bash
# Standalone installer for an Ollama analysis computer (not the Dindon server).
# The thermal relay below is bundled from ollama_thermal_proxy.py so only this file is needed.
set -euo pipefail
set +x  # Never echo authentication arguments, even when launched with bash -x.

usage() {
  cat <<'HELP'
Usage : sudo bash install-analysis-linux.sh [--auth-key-file FICHIER] [--require-thermal]

Installe Tailscale, Ollama et les deux modèles Dindon sur Linux avec systemd.
Compatible avec apt-get, dnf ou zypper ; processeurs x86_64 et ARM64.
Configure une requête et un modèle chargé à la fois, pour une VM de 8 Go.
Connexion Tailscale par navigateur, ou par clé contenue dans un fichier.
La protection thermique CPU est activée si des capteurs sont reconnus.
--require-thermal : refuser de continuer sans capteur CPU.
HELP
}
fail() { printf '%s\n' "$*" >&2; exit 1; }
auth_file=""
require_thermal=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --auth-key-file)
      [[ $# -ge 2 && -f "$2" ]] || fail "--auth-key-file attend un fichier existant."
      auth_file="$2"; shift 2 ;;
    --require-thermal) require_thermal=true; shift ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$(uname -s)" == Linux ]] || fail "Ce fichier doit être exécuté sur l’ordinateur Linux à ajouter."
[[ "$(id -u)" == 0 ]] || fail "Lancer : sudo bash install-analysis-linux.sh"
[[ -d /run/systemd/system ]] || fail "Une distribution Linux avec systemd est nécessaire (Ubuntu Server ou Debian, par exemple)."
case "$(uname -m)" in
  x86_64|aarch64|arm64) ;;
  *) fail "Ollama nécessite ici un processeur x86_64 ou ARM64." ;;
esac

trap 'printf "Installation interrompue à la ligne %s. Corriger le problème puis relancer le fichier.\n" "$LINENO" >&2' ERR
work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT

printf '\nInstallation des outils nécessaires…\n'
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl python3 zstd
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y ca-certificates curl python3 zstd
elif command -v zypper >/dev/null 2>&1; then
  zypper --non-interactive install ca-certificates curl python3 zstd
else
  fail "Gestionnaire de paquets pris en charge : apt-get, dnf ou zypper."
fi

if ! command -v tailscale >/dev/null 2>&1; then
  curl --fail --show-error --location --proto '=https' --tlsv1.2 https://tailscale.com/install.sh -o "$work_dir/tailscale.sh"
  sh "$work_dir/tailscale.sh"
fi
if ! command -v ollama >/dev/null 2>&1; then
  curl --fail --show-error --location --proto '=https' --tlsv1.2 https://ollama.com/install.sh -o "$work_dir/ollama.sh"
  sh "$work_dir/ollama.sh"
fi

printf '\nConfiguration d’Ollama pour 8 Go de RAM…\n'
install -d -m 755 /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/dindon-worker.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_CONTEXT_LENGTH=8192"
Environment="OLLAMA_KEEP_ALIVE=5m"
EOF
export OLLAMA_HOST=127.0.0.1:11434
systemctl daemon-reload
systemctl enable ollama tailscaled
systemctl restart ollama
systemctl start tailscaled
ready=false
for _ in {1..30}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:11434/api/tags > "$work_dir/tags.json"; then
    ready=true; break
  fi
  sleep 1
done
[[ "$ready" == true ]] || fail "Ollama ne démarre pas. Consulter : journalctl -u ollama -n 40 --no-pager"

printf '\nTéléchargement des modèles (cela peut prendre plusieurs minutes)…\n'
ollama pull qwen3.5:4b
ollama pull leoipulsar/harrier-0.6b
ollama list

printf '\nConnexion au réseau Tailscale de Dindon…\n'
# A rerun keeps the existing account and non-default Tailscale settings.
state="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState", ""))')"
if [[ "$state" != Running ]]; then
  if [[ -n "$auth_file" ]]; then
    auth_file="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$auth_file")"
    tailscale up "--auth-key=file:$auth_file"
  else
    printf 'Ouvrir le lien affiché et choisir le même réseau Tailscale que Dindon.\n'
    tailscale up
  fi
fi

install -d -m 755 /opt/dindon-worker
cat > "$work_dir/ollama_thermal_proxy.py" <<'DINDON_THERMAL_PY'
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
DINDON_THERMAL_PY
install -m 644 "$work_dir/ollama_thermal_proxy.py" /opt/dindon-worker/ollama_thermal_proxy.py

thermal_available="$(python3 - <<'PY'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('thermal', '/opt/dindon-worker/ollama_thermal_proxy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print('yes' if module.sensors(Path('/sys/class/hwmon'), 85) else 'no')
PY
)"
backend_port=11434
if [[ "$thermal_available" == yes ]]; then
  cat > /etc/systemd/system/dindon-thermal.service <<'EOF'
[Unit]
Description=Ollama avec protection thermique CPU
After=network.target ollama.service

[Service]
DynamicUser=yes
ExecStart=/usr/bin/python3 /opt/dindon-worker/ollama_thermal_proxy.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable dindon-thermal
  systemctl restart dindon-thermal
  backend_port=11435
  printf '\nProtection thermique CPU activée (retrait à 85 °C au plus, reprise après refroidissement).\n'
else
  if [[ "$require_thermal" == true ]]; then
    # Do not leave an existing unguarded forwarding rule active.
    tailscale serve --yes --tcp=11434 off
    fail "Aucun capteur CPU reconnu : protection thermique obligatoire, partage désactivé."
  fi
  if [[ -f /etc/systemd/system/dindon-thermal.service ]]; then
    systemctl disable --now dindon-thermal
  fi
  printf '\nAucun capteur CPU reconnu : protection thermique indisponible (fréquent dans une VM).\n'
fi

# Configure the guarded route before checking it: a hot computer must not keep
# a previous direct Ollama route while installation waits for it to cool down.
tailscale serve --bg --yes --tcp=11434 "tcp://localhost:$backend_port"
api_url="http://127.0.0.1:$backend_port"
ready=false
for _ in {1..30}; do
  if curl --fail --silent --max-time 2 "$api_url/api/tags" > "$work_dir/tags.json"; then
    ready=true; break
  fi
  sleep 1
done
[[ "$ready" == true ]] || fail "Le service ne répond pas ou l’ordinateur est trop chaud. Consulter : journalctl -u dindon-thermal -n 40 --no-pager"

python3 - "$work_dir/tags.json" <<'PY'
import json, sys
models = {m['name'] for m in json.load(open(sys.argv[1]))['models']}
for model in ('qwen3.5:4b', 'leoipulsar/harrier-0.6b'):
    if model not in models and model + ':latest' not in models:
        raise SystemExit('Modèle manquant : ' + model)
PY

printf '\nVérification réelle des vecteurs et de la lecture (le CPU peut prendre quelques minutes)…\n'
curl --fail --show-error --silent --max-time 600 "$api_url/api/embed" \
  -H 'Content-Type: application/json' \
  -d '{"model":"leoipulsar/harrier-0.6b","input":["Vérification de l’ordinateur d’analyse."],"truncate":false}' \
  -o "$work_dir/embed.json"
python3 - "$work_dir/embed.json" <<'PY'
import json, math, sys
vectors = json.load(open(sys.argv[1])).get('embeddings', [])
if len(vectors) != 1 or len(vectors[0]) != 1024 or not all(math.isfinite(v) for v in vectors[0]):
    raise SystemExit('Le modèle de vecteurs ne renvoie pas les 1024 dimensions attendues par Dindon.')
PY
curl --fail --show-error --silent --max-time 600 "$api_url/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:4b","stream":false,"think":false,"format":"json","options":{"num_ctx":8192,"num_predict":32,"temperature":0},"messages":[{"role":"user","content":"Réponds uniquement avec cet objet JSON : {\"ok\":true}"}]}' \
  -o "$work_dir/chat.json"
python3 - "$work_dir/chat.json" <<'PY'
import json, sys
answer = json.load(open(sys.argv[1]))
if not answer.get('done') or json.loads(answer.get('message', {}).get('content', 'null')) != {'ok': True}:
    raise SystemExit('Le modèle de lecture n’a pas terminé la vérification JSON.')
PY

ip="$(tailscale ip -4)"
[[ "$ip" =~ ^100\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Aucune adresse IPv4 Tailscale disponible."
tailscale serve status
printf '\nInstallation terminée. Les services redémarreront automatiquement avec Linux.\n'
printf '\nAdresse à ajouter dans Dindon → Système → Performance → Ordinateurs d’analyse :\nhttp://%s:11434\n' "$ip"
if [[ "$thermal_available" != yes ]]; then
  printf '\nProtection thermique : indisponible sur cette machine.\n'
fi
printf '\nDepuis le serveur Dindon, vérifier l’accès :\ncurl --fail --connect-timeout 10 http://%s:11434/api/tags\n' "$ip"
