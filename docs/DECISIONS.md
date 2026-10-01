# Décisions

Une ligne par choix qui s'écarte du prompt d'origine ou qui ajoute une pièce. Les décisions déjà prises dans le [prompt](PROMPT.md) (PostgreSQL + pgvector, FastAPI, Svelte + Sigma.js, Ollama, pas de Redis ni de microservices…) ne sont pas répétées ici.

## Organisation

| Choix | Pourquoi |
| --- | --- |
| `docs/` contient aussi `ARCHITECTURE.md`, `AXES.md`, `PROMPT.md` et `base-de-donnees.md` (l'ancien `database/README.md`) | le kit les plaçait à la racine ou dans `database/` et `.docs/`. Les liens ont été réécrits ; le contenu est inchangé, sauf le nom du projet et les chemins dans `base-de-donnees.md` |
| `contracts/` reçoit les trois fichiers de `.docs/JSON-format*` | arborescence du prompt |
| `tools/load_export.py` et `tools/generate_axes_review.py` | le chargeur de référence sert d'oracle de comportement à l'ingestion ; la page des axes s'écrit maintenant dans `docs/AXES.md` |
| Nom du projet « dindon » partout (base, utilisateur, compose, paquet) à la place de « strategio » | le dossier du projet s'appelle `dindon` |
| `db/*.sql` : **copie exacte** des fichiers du kit (vérifiée octet par octet) | « sans changer le sens des tables » ; les évolutions iront dans `db/migrations/` |

## Pièces ajoutées

| Pièce | Pourquoi elle est nécessaire |
| --- | --- |
| `fastapi`, `uvicorn` | imposés par le prompt (application et serveur) |
| `psycopg[binary]` | pilote PostgreSQL ; le chargeur de référence l'utilise déjà. Version 3, qui sait faire `COPY` pour l'ingestion par lots |
| `pytest` (dev) | tests |
| `httpx2` (dev) | le client de test de Starlette 1.7 le demande ; avec l'ancien `httpx`, un avertissement de dépréciation apparaît |
| `setuptools` (construction) | rien d'exotique : le paquet s'installe avec `pip`. Pas de `uv` ni de `poetry`, qui ne sont pas installés sur la machine |
| Image `python:3.13-slim` | Python 3.13 est la version disponible sur la machine de développement (3.12+ demandé) |

Pas d'ORM, pas de framework de migrations : psycopg et du SQL.

## Migrations ([app/dindon/migrate.py](../app/dindon/migrate.py))

- Les **quatre fichiers du kit forment la base de départ** : rejouables sans effet (c'est testé), ils sont **rejoués dès que leur contenu change** (empreinte SHA-256 dans `schema_migrations`). Ainsi, une correction du fichier de départ s'applique sans migration.
- Les **migrations numérotées** `db/migrations/0001_nom.sql` s'appliquent **une fois chacune, dans l'ordre**, chacune dans une transaction. Modifier une migration déjà appliquée est **refusé** : on en écrit une nouvelle.
- Un verrou de la base (`pg_advisory_lock`) empêche deux processus de migrer en même temps.
- `schema_migrations` n'est **pas comptée** dans les « 37 tables » du critère de fin de phase 0 : ce sont les 37 tables du kit.
- Les migrations sont appliquées **au démarrage de l'application** (`dindon serve`). La base de données de Docker démarre vide ; les fichiers ne sont plus montés dans `docker-entrypoint-initdb.d`. Un seul chemin pour créer la base, le même en test et en production.

## Sécurité

- `/health` **ne demande pas de mot de passe** : il ne renvoie que des comptes (tables, vues, axes) et l'état d'Ollama, jamais de contenu, et il sert de contrôle de santé à Docker. Tous les autres points d'accès seront protégés par le mot de passe (phase 1).
- Une erreur de base renvoie 503 **sans détail** (ni adresse, ni mot de passe) : c'est testé.
- Tous les ports Docker sont publiés sur `127.0.0.1` ; vérifié : l'application n'est pas joignable par l'adresse du réseau local de la machine.
- Ollama : sur Mac, **hors Docker** (Docker ne peut pas utiliser la puce graphique) ; sur Linux, profil `ollama` du compose. Le service n'est pas démarré par défaut.

## Tests

- `make test` démarre sa **propre base jetable** (projet compose `dindontest`, port 55432, volume supprimé à la fin) : elle ne touche jamais à la base de travail. `DINDON_TEST_DATABASE_URL` permet d'en utiliser une autre, jetable elle aussi.
- Données **inventées** uniquement (`tests/synthetic.py`) ; chaque test est annulé (rollback) à la fin.
