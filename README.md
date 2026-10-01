# Dindon

Une carte vivante d'un serveur Discord : qui parle à qui, de quoi, avec quelles idées, et les preuves de chaque position. **Tout reste en local** : aucun service extérieur, hors Discord lui-même.

> **État : phase 0 (socle).** La base, l'application et les tests tournent. Il n'y a pas encore de collecte, de carte ni d'analyse : voir la [feuille de route](docs/ARCHITECTURE.md#11-feuille-de-route).

## Lire avant de s'en servir

- **Données sensibles.** Ce projet traite les messages de personnes identifiables, dont leurs **opinions politiques**. Le serveur compte des **mineurs**. Un usage strictement personnel est hors du champ du RGPD ; **ce n'est plus le cas dès que les fiches sont montrées à d'autres**. Ne partagez ni la base, ni les fiches, ni les cartes. Chiffrez le disque de la machine.
- **Conditions d'utilisation de Discord.** Automatiser un **compte personnel** (jeton utilisateur) est interdit par Discord et peut le faire fermer. La surveillance continue (phase 1) doit utiliser un **bot** ; avec un compte, c'est à vos risques.
- **Classements = hypothèses.** Une position n'existe que si elle cite des messages ; elle s'affiche avec son nombre de preuves et son incertitude, jamais comme un fait. « Discordant » est une alerte à regarder, pas une accusation. L'âge et le genre ne sont jamais analysés ni affichés.
- **Rien de réel dans le dépôt.** Les exports, archives, sauvegardes, fichiers `.env` et jetons sont ignorés par Git ; les tests n'utilisent que des données inventées.

## Installer

Il faut Docker (avec `docker compose`). Pour travailler sur le code, il faut aussi Python 3.13.

```console
cp .env.example .env     # puis choisissez les deux mots de passe (POSTGRES_PASSWORD, DINDON_PASSWORD)
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

`/health` doit répondre `"status":"ok"` avec **37 tables, 9 vues, 21 axes dont 12 actifs**. Les fichiers SQL sont appliqués au démarrage de l'application (voir [docs/DECISIONS.md](docs/DECISIONS.md)). Aucun port n'est ouvert sur le réseau : tout est publié sur `127.0.0.1` seulement.

### L'IA locale (Ollama)

Pas nécessaire avant la phase 2. Sur un Mac, installez Ollama directement (`brew install ollama`) : dans Docker, il ne peut pas utiliser la puce graphique. Sur un serveur Linux, `docker compose --profile ollama up -d` le lance dans Docker. Réglez `OLLAMA_URL` dans `.env` ; `/health` indique si Ollama répond et quels modèles il a.

## Utiliser

| Commande | Effet |
| --- | --- |
| `make up` / `make down` | démarrer / arrêter (les données sont gardées) |
| `make test` | tous les tests (voir plus bas) |
| `make check` | ce que contient la base (tables, vues, axes) |
| `make axes` | réécrit [docs/AXES.md](docs/AXES.md) depuis la base : la page où relire les axes et idéologies |
| `make backup` | sauvegarde compressée dans `backups/` |

Activer un axe après relecture : `UPDATE axes SET is_active = true WHERE code = 'europe';`. **Les axes, idéologies, plages et règles de rôles sont les vôtres à relire** ; le code ne les modifie jamais.

## Sauvegarder et restaurer

```console
make backup                                  # crée backups/dindon-AAAA-MM-JJ-HHMM.sql.gz
```

Restaurer sur une installation neuve (base vide : seul `db` est démarré, l'application n'a donc rien créé) :

```console
docker compose up -d --wait db
gunzip -c backups/dindon-2026-10-01-2128.sql.gz | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U dindon dindon
docker compose up -d --build                 # les migrations voient que tout est déjà là
```

La sauvegarde contient **tous les messages** : traitez-la comme la base elle-même (ne la partagez pas, chiffrez le disque).

## Mettre à jour

```console
git pull
docker compose up -d --build
```

Les nouvelles migrations (`db/migrations/`) sont appliquées au démarrage, une seule fois chacune, dans l'ordre.

## Dépanner

| Symptôme | Piste |
| --- | --- |
| `docker compose up` : « Choose a password in .env » | `.env` n'existe pas ou la variable est vide : `cp .env.example .env` |
| `/health` répond 503 | la base n'est pas prête ou le mot de passe de `.env` a changé après la création du volume : `docker compose logs db app` |
| Le mot de passe de la base a changé dans `.env` | il n'est pris en compte qu'à la création du volume. Soit remettre l'ancien, soit restaurer une sauvegarde dans un volume neuf (`docker compose down -v` **efface les données**) |
| Port 5432 ou 8000 déjà pris | changer `POSTGRES_PORT` ou `DINDON_PORT` dans `.env` |
| `/health` : `"ollama":{"reachable":false}` | normal tant qu'Ollama n'est pas installé ; vérifier `OLLAMA_URL` ensuite |
| Le build Docker échoue sur « no such host » | pas de réseau au moment du téléchargement des images : relancer |

## Tests

`make test` démarre une base jetable (projet Docker `dindontest`, port 55432), applique le schéma, lance les tests, puis supprime la base. Ils couvrent pour l'instant : la création de la base (37 tables, 9 vues, 21 axes dont 12 actifs), les migrations (rejouables, ordre, refus d'une migration modifiée, échec sans reste), le calcul des scores (les deux valeurs de référence : −0,692 ± 0,381 et −0,662 ± 0,399), la vérification avec les rôles (concordant, discordant, non vérifiable, rôles contradictoires, preuve rejetée) et `/health`.

## Organisation

| Dossier | Contenu |
| --- | --- |
| `contracts/` | le contrat de données : JSON version 2 (description, JSON Schema, modèle) |
| `db/` | les fichiers SQL (`schema*.sql`, `seed-axes.sql`) et les migrations |
| `app/dindon/` | l'application Python (FastAPI) |
| `web/` | l'interface (Svelte), à partir de la phase 1 |
| `tools/` | outils : chargeur de référence, page de relecture des axes |
| `tests/` | tests (données inventées uniquement) |
| `docs/` | [architecture](docs/ARCHITECTURE.md), [décisions](docs/DECISIONS.md), [axes à relire](docs/AXES.md), [la base](docs/base-de-donnees.md), le prompt d'origine |
| `exporter/` | [comment obtenir l'exportateur](exporter/README.md) |
