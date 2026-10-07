# Commandes et configuration

Les commandes `dindon` s'exécutent dans le conteneur (`docker compose exec app dindon …`, ou `exec bot` pour les rapports du bot) ou dans l'environnement Python local après `make setup`. `dindon --help` et `dindon COMMANDE --help` donnent les options acceptées par le code.

## Mise en route et maintenance

| Commande | Effet |
| --- | --- |
| `make setup`, `make web` | installe Python en local, construit l'interface avec Node.js |
| `make up`, `make down`, `make db` | démarre l'ensemble, l'arrête en gardant les volumes, ou démarre seulement PostgreSQL |
| `dindon serve` | applique les migrations puis lance FastAPI et ses tâches de fond |
| `dindon migrate`, `dindon check` | applique les fichiers SQL ; affiche la composition actuelle de la base |
| `dindon preflight [--json]` | vérifie en lecture seule la configuration avant l'emploi du bot |
| `dindon bot`, `dindon bot-health` | lance le Gateway ; vérifie sa présence et sa connexion pour Compose |
| `dindon rebuild-edges` | recalcule les liens de la carte depuis les messages |
| `make backup` | écrit une sauvegarde SQL compressée dans `backups/` |
| `make lint`, `make test`, `make check-ui` | Ruff, Pytest, vérification facultative de l'interface avec Playwright |
| `make demo`, `make politique` | serveurs de démonstration inventés, ports 8011 et 8012 |
| `dindon digest [--guild ID] [--limit N] [--json]` | synthèse courte d'un serveur : thèmes, positions (pour/contre/nuancé) et contradictions, en Markdown ou en JSON ; lecture seule, sans les personnes qui ont demandé à ne pas être enregistrées |
| `make axes` | génère `political/axes-review.txt` depuis la base pour relire les axes et idéologies |

`make test` utilise une base Docker jetable. `make check-ui` demande Playwright et son navigateur. `tools/host/install.sh` peut installer sur Mac le redémarrage d'Ollama et une sauvegarde nocturne ; sa propre aide précise les options.

## Données et analyse

| Commande | Effet |
| --- | --- |
| `dindon export CHANNEL_ID --out dossier/` | lit un salon Discord et produit du JSON v2 ; options `--after`, `--before`, `--threads`, `--reactions`, `--partition`, `--filter` |
| `dindon ingest fichier.json [autres…] [--prune]` | importe un ou plusieurs fichiers ou dossiers JSON v2 ; `--prune` suppose un ré-export complet de la fenêtre |
| `dindon backfill [--guild ID] [--parallel N]` | premier import d'un ou plusieurs serveurs ; filtres répétables `--channel`, `--from`, `--mentioning`, et dates incluses `--after`, `--before` |
| `dindon catchup [--guild ID]` | relit les derniers jours pour retrouver modifications et suppressions |
| `dindon analyze [--guild ID] [--stage ÉTAPE] [--limit N] [--topics N] [--rebuild]` | analyse locale ; étapes `conversations`, `embeddings`, `themes`, `claims`, `axes` ; sans `--stage`, les trois premières |
| `dindon privacy list\|stop\|erase\|release\|export\|purge [ID] [--reason TEXTE]` | registre, arrêt, effacement, reprise, accès ou purge |
| `dindon forget-server GUILD_ID` | efface définitivement toutes les données d'un serveur |
| `dindon debate-report [--debate ID]` | affiche les affirmations, sources et répartitions des débats |

Exemples :

```sh
docker compose exec app dindon backfill --guild 123456789 --channel general --after 2026-09-01
docker compose exec app dindon analyze --stage claims --limit 40
docker compose exec bot dindon debate-report
```

Un import filtré par personne ou période est partiel : il ne remplace pas le premier import complet nécessaire au suivi automatique.

## Variables principales de `.env`

| Variables | Usage |
| --- | --- |
| `POSTGRES_PASSWORD`, `DINDON_PASSWORD` | mots de passe obligatoires de la base et de l'interface |
| `POSTGRES_PORT`, `DINDON_PORT` | ports locaux de Compose, 5432 et 8000 par défaut |
| `DISCORD_TOKEN`, `DINDON_GUILD_IDS` | jeton et liste des serveurs ; `all` ou vide suit tous les serveurs du bot |
| `DINDON_COLLECTOR` | `on` (surveillance et rattrapage), `catchup` (rattrapage seul), `off` |
| `DINDON_POLL_SECONDS`, `DINDON_CATCHUP_DAYS`, `DINDON_CATCHUP_HOUR` | cadence de surveillance, fenêtre et heure UTC du rattrapage ; les deux derniers ne sont pas transmis par Compose sauf ajout explicite |
| `DINDON_THREADS`, `DINDON_EXPORT_WORKERS`, `DINDON_EXPORT_REACTIONS`, `DINDON_EXPORT_REACTIONS_DAYS` | fils et coût de l'exportateur ; défauts `active`, 6, `recent`, 30 jours |
| `OLLAMA_URL`, `DINDON_EMBED_MODEL`, `DINDON_NAMING_MODEL` | IA locale, modèles `bge-m3` et `qwen3:14b` par défaut |
| `DINDON_RETENTION_DAYS`, `DINDON_ERASE_ON_REMOVAL` | rétention (0 : aucune purge) et effacement optionnel après retrait du bot |
| `DINDON_DEBATE_CHECKS`, `DINDON_DEBATE_MODEL`, `DINDON_DEBATE_PRECISION`, `DINDON_DEBATE_MIN_PRECISION` | niveaux et verrou des vérifications de débats |
| `DINDON_FACTCHECK_API_KEY`, `DINDON_SEARXNG_URL`, `SEARXNG_SECRET` | services de recherche facultatifs |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | Activity Discord |

Les chemins `DINDON_INBOX_DIR` et `DINDON_ARCHIVE_DIR` règlent les montages Compose ; hors Docker, `DINDON_INBOX` et `DINDON_ARCHIVE` règlent les chemins lus par Python. Voir aussi [.env.example](../.env.example) et [Import des données](import-des-donnees.md).
