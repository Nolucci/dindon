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

## Relecture des positions

La relecture est **à part de l'analyse** (page Analyse, onglet « Relecture ») : elle ne tourne jamais en même temps qu'elle, et c'est le propriétaire qui la lance, quand il le veut. Elle relit chaque position de chaque personne avec les messages qui la précèdent (huit à dix messages avant la preuve, tout ce qui se trouve entre les preuves, et le message auquel la personne répond ; les auteurs y sont anonymes, jamais un nom), et demande au modèle, sans lui dire ce que l'analyse avait conclu :

- si la personne exprime **sa propre opinion** (pas une citation, une ironie, une question, un fait sans avis) ;
- quelle est sa **position** vis-à-vis de la proposition (accord, désaccord, nuance), en lisant les négations et le sens d'une réponse contre ce qui précède ;
- si la **proposition** est bien la thèse défendue ou combattue (sinon, la thèse exacte) ;
- quel **thème** convient le mieux, parmi le sien et les plus proches.

Le code ne fait pas confiance au modèle : rien ne change sous une certitude de 70 ; une position qu'une personne a confirmée ou rejetée n'est jamais relue ; chaque correction garde ce qu'elle était (`claim_rereads`, `claims.stance_before`) et s'annule d'un clic ; une proposition nouvelle est rapprochée des existantes par son vecteur avant d'être créée, puis seulement *proposée* et reliée aux axes. Après la relecture, les scores des personnes sont recalculés puis **contrôlés** : chacun est recalculé à part, hors de la fonction SQL, et comparé (`audit_scores`) ; un écart est signalé, et les scores sont recalculés.

**Ironie.** Partout où une position ou une affirmation est retenue (analyse des positions, relecture, vérification des débats), une question à part est posée au modèle sur le message qui la prouve, avec le message auquel il répond : l'auteur le pense-t-il vraiment (`analysis/irony.py`) ? Une ironie, un sarcasme, une blague, une citation ou une simple question ne sont pas ce que la personne affirme : la position reste avec sa preuve, en `humour`, et ne compte pour rien dans les scores. Le code ne décide que sur une réponse nette (certitude d'au moins 90) ; une hésitation laisse le message tel qu'il est. Les mots habituels de l'ironie (« bien sûr », « évidemment », « mdr ») ne sont que des indices : « Bien sûr que non, il finance les services publics » est sérieux. Mesure : `python tools/measure_irony.py --model qwen3:14b` sur `tools/irony_reference.json` (52 messages inventés) : avec `qwen3:14b`, 22 ironies sur 22 repérées et aucun message sincère pris pour de l'ironie ; avec `qwen3:8b`, 20 sur 22 et aucun à tort.

Ce qui a déjà été relu avec la méthode actuelle n'est pas relu, sauf si l'on coche « relire aussi ce que la méthode actuelle a déjà relu » ; quand la méthode change (`reread.VERSION`), tout redevient à relire. Le modèle est `DINDON_REREAD_MODEL` (par défaut le modèle de nommage) : un modèle plus fort vaut la peine, la relecture étant rare. Mesure : `python tools/measure_reread.py --model qwen3:14b` sur `tools/reread_reference.json` (17 positions inventées : avec `qwen3:14b`, les 4 positions justes sont laissées telles quelles et 10 des 13 fausses sont corrigées ; avec `qwen3:8b`, 8 sur 13).

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
