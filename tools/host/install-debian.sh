#!/usr/bin/env bash
# Install a fresh Dindon checkout and its Docker services on Debian 12/13.
# Usage: sudo bash install-debian.sh [--env-file /path/to/source.env] [--no-bot]
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Lancer ce script avec sudo (installation des paquets et de Docker)." >&2
  exit 1
fi

with_bot=true
env_source=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      if [[ $# -lt 2 || ! -f "$2" ]]; then
        echo "--env-file demande un fichier existant." >&2
        exit 2
      fi
      env_source="$2"
      shift 2
      ;;
    --with-bot) with_bot=true; shift ;;
    --no-bot) with_bot=false; shift ;;
    *)
      echo "Usage : sudo bash install-debian.sh [--env-file /path/to/source.env] [--with-bot|--no-bot]" >&2
      exit 2
      ;;
  esac
done

# DINDON_DIR and DINDON_REPO_URL may be set for a different location/fork.
project_dir="${DINDON_DIR:-/opt/dindon}"
repo_url="${DINDON_REPO_URL:-https://github.com/Nolucci/dindon.git}"
if [[ "$project_dir" != /* || "$project_dir" == / ]]; then
  echo "DINDON_DIR doit être un dossier absolu autre que /." >&2
  exit 2
fi

. /etc/os-release
if [[ "$ID" != debian || ( "$VERSION_ID" != 12 && "$VERSION_ID" != 13 ) ]]; then
  echo "Ce script prend en charge Debian 12 et 13 uniquement." >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git openssl python3

if ! command -v docker >/dev/null 2>&1; then
  # Official Docker apt repository: https://docs.docker.com/engine/install/debian/
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $VERSION_CODENAME
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker est présent, mais le plugin Compose manque. Installer docker-compose-plugin puis relancer." >&2
  exit 1
fi
systemctl enable --now docker
docker info >/dev/null

if [[ -d "$project_dir/.git" ]]; then
  existing_remote="$(git -C "$project_dir" remote get-url origin)"
  if [[ "$existing_remote" != "$repo_url" ]]; then
    echo "Le dépôt existant utilise $existing_remote, attendu : $repo_url. Aucun dépôt modifié." >&2
    exit 1
  fi
  echo "Mise à jour du dépôt dans $project_dir"
  git -C "$project_dir" pull --ff-only
elif [[ -e "$project_dir" ]]; then
  echo "$project_dir existe déjà et n’est pas un dépôt Git. Aucun fichier supprimé." >&2
  exit 1
else
  git clone "$repo_url" "$project_dir"
fi
cd "$project_dir"

if [[ ! -f .env ]]; then
  if [[ -n "$env_source" ]]; then
    install -m 0600 "$env_source" .env
    echo "Configuration existante copiée depuis le fichier fourni."
  else
    cp .env.example .env
    db_password="$(openssl rand -hex 24)"
    web_password="$(openssl rand -hex 24)"
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$db_password/" .env
    sed -i "s/^DINDON_PASSWORD=.*/DINDON_PASSWORD=$web_password/" .env
    echo "Nouveau fichier .env créé avec des mots de passe aléatoires."
  fi
  # This installation runs Ollama in Docker. Preserve every other setting from the source server.
  if grep -q '^OLLAMA_URL=' .env; then
    sed -i 's|^OLLAMA_URL=.*|OLLAMA_URL=http://ollama:11434|' .env
  else
    printf '\nOLLAMA_URL=http://ollama:11434\n' >> .env
  fi
else
  echo "Fichier .env existant conservé (le fichier source n’est utilisé que pour une première installation)."
fi
chmod 600 .env

if grep -Eq '^(POSTGRES_PASSWORD=change-me|DINDON_PASSWORD=change-me-too)$' .env; then
  echo "Remplacer les mots de passe d’exemple dans $project_dir/.env avant de continuer." >&2
  exit 1
fi
if ! grep -Eq '^OLLAMA_URL=http://ollama:11434$' .env; then
  echo "Mettre OLLAMA_URL=http://ollama:11434 dans $project_dir/.env puis relancer ce script." >&2
  exit 1
fi
if [[ "$with_bot" == true ]] && ! grep -Eq '^DISCORD_TOKEN=[^#[:space:]]+' .env; then
  discord_token=""
  if ! read -r -s -p 'Jeton du bot Discord : ' discord_token </dev/tty; then
    echo "Le bot demande un jeton Discord. Relancer dans un terminal interactif ou fournir --env-file." >&2
    exit 1
  fi
  printf '\n'
  if [[ ! "$discord_token" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Jeton vide ou au format inattendu ; rien n’a été enregistré." >&2
    exit 1
  fi
  if grep -q '^DISCORD_TOKEN=' .env; then
    sed -i "s|^DISCORD_TOKEN=.*|DISCORD_TOKEN=$discord_token|" .env
  else
    printf '\nDISCORD_TOKEN=%s\n' "$discord_token" >> .env
  fi
  unset discord_token
  chmod 600 .env
fi
if [[ "$with_bot" == true ]]; then
  if ! grep -q '^DINDON_GUILD_IDS=' .env; then
    printf 'DINDON_GUILD_IDS=all\n' >> .env
  fi
  if ! grep -q '^DINDON_COLLECTOR=' .env; then
    printf 'DINDON_COLLECTOR=catchup\n' >> .env
  fi
  python3 tools/host/discover-discord.py .env
fi

docker compose config --quiet
docker compose --profile ollama up -d ollama
embed_model="$(sed -n 's/^DINDON_EMBED_MODEL=//p' .env | tail -n 1)"
naming_model="$(sed -n 's/^DINDON_NAMING_MODEL=//p' .env | tail -n 1)"
debate_model="$(sed -n 's/^DINDON_DEBATE_MODEL=//p' .env | tail -n 1)"
docker compose exec -T ollama ollama pull "${embed_model:-bge-m3}"
docker compose exec -T ollama ollama pull "${naming_model:-qwen3:14b}"
if [[ -n "$debate_model" && "$debate_model" != "${naming_model:-qwen3:14b}" ]]; then
  docker compose exec -T ollama ollama pull "$debate_model"
fi

profiles=(--profile ollama)
if [[ "$with_bot" == true ]]; then
  profiles+=(--profile bot)
fi
if grep -Eq '^DINDON_SEARXNG_URL=http://searxng:8080/?$' .env; then
  profiles+=(--profile search)
fi
docker compose "${profiles[@]}" up -d --build --wait --wait-timeout 180
bash tools/host/check-debian.sh "$project_dir"

echo
echo "Installation terminée dans $project_dir."
echo "Mot de passe de l’interface : consulter DINDON_PASSWORD dans $project_dir/.env (accès root)."
echo "Depuis votre poste : ssh -L 8000:127.0.0.1:8000 utilisateur@serveur"
echo "Puis ouvrir http://127.0.0.1:8000 (adapter si DINDON_PORT a changé)."
