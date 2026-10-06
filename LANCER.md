# Lancer Dindon

Exécuter les commandes depuis la racine du projet. Le parcours recommandé utilise Docker Compose pour PostgreSQL et l'application. L'IA locale (Ollama) est nécessaire pour analyser les thèmes et les positions, mais pas pour ouvrir la carte ni importer des données.

## Installation rapide sur un serveur Debian 12 ou 13

Une fois les scripts publiés sur la branche `main` du dépôt Git, lancer sur le serveur :

```sh
sudo apt-get update && sudo apt-get install -y curl
curl -fsSLo /tmp/install-debian.sh https://raw.githubusercontent.com/Nolucci/dindon/main/tools/host/install-debian.sh
sudo bash /tmp/install-debian.sh
```

Le script installe Git et, si nécessaire, Docker depuis son dépôt officiel, clone le projet dans `/opt/dindon`, crée `.env`, démarre PostgreSQL, Ollama, l'application et le bot, puis exécute le contrôle final. Il génère les deux mots de passe locaux, configure l'adresse d'Ollama et utilise les ports du projet. À partir du jeton, il récupère auprès de Discord l'identifiant de l'application et les identifiants des serveurs où le bot est déjà invité. S'il n'est encore dans aucun serveur, il suivra les serveurs où il sera invité. Le mode `DINDON_COLLECTOR=catchup` évite une seconde collecte permanente. Le téléchargement des modèles peut être long. Un `.env` existant est conservé ; le script ne supprime pas les données existantes.

**Seul le jeton du bot Discord doit être fourni à la première installation.** Le script le demande dans le terminal sans l'afficher ni l'écrire dans l'historique du shell. Créer et inviter le bot depuis le [portail des développeurs Discord](https://discord.com/developers/applications), copier son jeton et activer **Message Content Intent** avant de lancer l'installateur. Ce jeton ne peut pas être déduit de la machine ni du serveur Discord. Si vous voulez installer d'abord l'application sans le bot, utiliser `sudo bash /tmp/install-debian.sh --no-bot` ; une exécution ultérieure avec `--with-bot` demandera le jeton.

Le script récupère `DISCORD_CLIENT_ID` automatiquement. Seul `DISCORD_CLIENT_SECRET` reste à copier depuis le portail Discord si vous voulez l'Activity dans un salon vocal. Pour l'activer après l'installation :

```sh
cd /opt/dindon
sudoedit .env                 # ajouter DISCORD_CLIENT_SECRET=...
sudo docker compose --profile bot up -d --build
sudo bash tools/host/check-debian.sh
```

Pour importer l'historique du serveur après avoir invité le bot :

```sh
cd /opt/dindon
sudo docker compose exec app dindon backfill
```

Pour retrouver le mot de passe de l'interface sans l'afficher dans les journaux d'installation :

```sh
sudo grep '^DINDON_PASSWORD=' /opt/dindon/.env
```

Pour voir les valeurs découvertes sans afficher le jeton ni les secrets :

```sh
sudo grep -E '^(DISCORD_CLIENT_ID|DINDON_GUILD_IDS|DINDON_COLLECTOR|OLLAMA_URL)=' /opt/dindon/.env
```

Pour vérifier les services à tout moment, notamment après un redémarrage :

```sh
sudo bash /opt/dindon/tools/host/check-debian.sh
```

Le contrôle doit finir par « Dindon est lancé ». Il vérifie les conteneurs, la base, l'interface HTTP, les modèles Ollama et, si le bot tourne, sa configuration et ses permissions Discord. Si le bot n'est encore invité dans aucun serveur, le contrôle l'indique ; invitez-le puis relancez le script d'installation pour enregistrer automatiquement son identifiant. La page reste vide tant qu'aucun serveur Discord ou fichier JSON n'a été importé.

Depuis votre ordinateur, ouvrir un tunnel SSH vers l'interface locale du serveur :

```sh
ssh -L 8000:127.0.0.1:8000 utilisateur@serveur
```

Puis ouvrir <http://127.0.0.1:8000> sur votre ordinateur. Remplacer le port dans la commande si `DINDON_PORT` a été modifié.

Pour activer le bot après une installation avec `--no-bot`, lancer (le jeton sera demandé) :

```sh
sudo bash /opt/dindon/tools/host/install-debian.sh --with-bot
```

La procédure d'installation Docker suit la [documentation officielle Docker pour Debian](https://docs.docker.com/engine/install/debian/).

## Première installation

Prérequis : Docker avec Compose. Installer aussi Ollama sur la machine si vous voulez utiliser l'analyse locale.

```sh
cp .env.example .env
nano .env
```

Dans `.env`, remplacer au minimum `POSTGRES_PASSWORD` et `DINDON_PASSWORD` par deux mots de passe distincts. Garder ce fichier privé. Pour importer depuis Discord, renseigner également `DISCORD_TOKEN` et, si vous souhaitez limiter les serveurs suivis, `DINDON_GUILD_IDS`.

### Ollama sur la machine (Mac ou autre installation native)

Dans un premier terminal, lancer Ollama si le service ne tourne pas déjà :

```sh
ollama serve
```

Dans un second terminal, installer les deux modèles :

```sh
ollama pull bge-m3
ollama pull qwen3:14b
```

Laisser `OLLAMA_URL=http://host.docker.internal:11434` dans `.env` pour que l'application Docker joigne Ollama sur la machine.

### Démarrer l'application

```sh
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

Ouvrir <http://127.0.0.1:8000> et saisir le mot de passe `DINDON_PASSWORD`. Les migrations de la base sont appliquées au démarrage. Si `DINDON_PORT` a été modifié dans `.env`, utiliser ce port à la place de `8000`.

La page est vide avant le premier import. Déposer un export JSON v2 dans `inbox/`, ou renseigner `DISCORD_TOKEN` dans `.env` puis utiliser **Importer** dans l'interface. Un premier import complet peut aussi se lancer ainsi :

```sh
docker compose exec app dindon backfill
```

## Démarrages suivants et arrêt

```sh
docker compose up -d
docker compose ps
docker compose logs -f app
```

`Ctrl-C` quitte l'affichage des journaux sans arrêter l'application. Pour arrêter les services en conservant les données :

```sh
docker compose down
```

Après une modification du code ou une mise à jour :

```sh
docker compose up -d --build
```

## Bot Discord en direct (facultatif)

Renseigner `DISCORD_TOKEN` dans `.env`, activer **Message Content Intent** pour le bot dans le portail Discord, puis lancer :

```sh
docker compose --profile bot up -d --build
docker compose ps
docker compose logs -f bot
```

La collecte de l'application peut aussi fonctionner sans ce service. Voir [les règles du bot](docs/regles-du-bot.md) pour ses permissions et ses commandes.

## Ollama dans Docker sur Linux (variante)

À la place d'Ollama installé sur la machine, mettre `OLLAMA_URL=http://ollama:11434` dans `.env`, puis lancer :

```sh
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama pull bge-m3
docker compose exec ollama ollama pull qwen3:14b
docker compose up -d --build
```

Sur Mac, privilégier Ollama installé sur la machine pour utiliser le GPU.

## Démonstration sans Discord (facultatif)

Cette variante demande Python 3.13 (valeur par défaut du `Makefile`), Node.js 20.19+ ou 22.12+, Docker et un `.env` configuré. Elle crée un serveur fictif sur le port 8011 ; `Ctrl-C` arrête la démonstration. Avec Python 3.12, utiliser `make setup PYTHON=python3.12` avant `make web` et `make demo`.

```sh
make setup web
make demo
```

Ouvrir <http://127.0.0.1:8011> avec le mot de passe `demo`.

Pour les autres commandes d'administration, voir [docs/commandes.md](docs/commandes.md).
