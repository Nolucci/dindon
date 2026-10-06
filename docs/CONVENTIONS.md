# Conventions du code

Ce que l'on suit pour que le code reste lisible et que modifier une chose n'en casse pas une autre. À lire avant d'ajouter quelque chose ; `make lint` et `make test` disent si on s'en est écarté.

## Où va quoi (`app/dindon/`)

| Dossier / fichier | Rôle, et rien d'autre |
| --- | --- |
| `config.py` | lire l'environnement (`Settings`) ; aucun autre module ne lit `os.environ` |
| `db.py`, `migrate.py`, `locks.py` | la connexion, les fichiers SQL, **les verrous de la base** (un numéro = un verrou, tous ici) |
| `clock.py` | l'heure courante en UTC (`utc_now()`, `utc_iso()`) : on n'écrit pas `datetime.now(...)` ailleurs, un test peut ainsi la remplacer |
| `ingest/` | **le seul chemin d'écriture des messages** : tout (fichier déposé, relevé, bot) devient un document JSON v2 puis passe par `loader.py` |
| `export/` | lire l'API REST de Discord et écrire du JSON v2 (client HTTP, limites, filtres, mise en page) |
| `bot/` | la passerelle Gateway (`gateway.py` est le **seul** fichier qui importe `discord.py`), la conversion en JSON v2 (`adapter.py`, partagée avec l'exportateur), le moteur (`runner.py`), les commandes `/dindon` |
| `collector/` | décider quoi exporter et quand (relevé, rattrapage, premier import, import partiel) |
| `analysis/` | la cascade IA, une étape par fichier : `conversations` → `embeddings` → `themes` → `extraction` → `stances` → `axes` ; `ollama.py` est le seul client du modèle |
| `privacy.py` | arrêter, effacer, exporter, purger une personne |
| `performance.py`, `automation.py` | les réglages d'économie de la machine et de lecture automatique |
| `api/` | l'interface HTTP, **un routeur par sujet** (`routes`, `positions`, `analysis`, `privacy`, `system`, `imports`, `invite`, `performance`, `automation`) ; ce qui sert à plusieurs est dans `common.py` ; `main.py` ne fait qu'assembler ; `background.py` lance les tâches de fond |
| `__main__.py` | la ligne de commande : un parseur, une fonction par commande, un tableau `COMMANDS` |

Une dépendance ne remonte jamais : `api/` peut importer `analysis/`, jamais l'inverse ; `ingest/` n'importe ni `api/` ni `bot/`.

## Principes

- **Une fonction, une chose.** Au-delà de ~15 branches (`make lint` le signale), on découpe : une petite fonction par cas, nommée pour ce qu'elle fait (voir `bot/adapter.py` : `_reactions_entry`, `_reference_entry`…).
- **Pas de nombre magique, pas de copie.** Une constante a un nom et un commentaire qui dit *pourquoi* cette valeur ; une règle qui existe deux fois sera un jour fausse une fois (le même numéro de verrou utilisé deux fois par hasard en est le cas d'école : `locks.py`).
- **On ne fait pas confiance au modèle.** Tout ce que l'IA rend est vérifié par le code avant d'être gardé (citation exacte, pôle qui appartient à l'axe, forme de la réponse) ; une réponse inutilisable ne change rien et sera réessayée.
- **Une erreur se dit en mots à la personne** (en français), sans jamais contenir un jeton, un mot de passe ou un message.
- **Un `except Exception` dit pourquoi** (« le dernier réglage connu reste ») ou n'existe pas ; un échec sans importance s'écrit `contextlib.suppress(...)`.
- **Les données sont inventées dans les tests**, la base est jetable, et rien n'y sort du poste (`conftest.py` refuse tout réseau non local).
- **Un défaut corrigé = un test qui échouait avant.**

## Tests

`make test` (toute la suite, ~25 min avec les tests de navigateur ; `pytest tests/test_axes.py` pour une partie). Les tests de navigateur (`test_ui_*`) sont facultatifs : ils se sautent sans Playwright. Un test qui dépend de la durée (la carte qui se stabilise) attend un état stable, jamais un `sleep` fixe.

## Style

`ruff` (réglé dans `pyproject.toml`) : imports triés, pas de code mort, idiomes de Python 3.12 (`datetime.UTC`, `contextlib.suppress`, `zip(strict=True)`). Les lignes peuvent être longues (180) si elles disent une seule chose. Code et commentaires en anglais, documentation et textes montrés à la personne en français.
