# Collecter les messages

Dindon ne lit jamais Discord lui-même : il s'appuie sur l'**exportateur** (DiscordChatExporter) et sur le format JSON version 2 ([contracts/JSON-format.md](../contracts/JSON-format.md)). Trois façons d'alimenter la base, qui passent toutes par la même ingestion :

| Mode | Délai | Ce qu'il faut |
| --- | --- | --- |
| **A. Export à la main** : déposer des fichiers JSON dans `inbox/` | à la demande | rien (l'application graphique de l'exportateur suffit) |
| **B. Surveillance** : l'application regarde ce qui a bougé et lance l'exportateur | environ la moitié de l'intervalle de relevé (15 s par défaut) | un jeton, l'identifiant du serveur, l'exportateur |
| **C. Bot en direct** | moins d'une seconde | pas encore fait (phase 5) : l'ingestion est prête à le recevoir |

## Avertissement : compte personnel ou bot

**Automatiser un compte personnel (jeton utilisateur) est interdit par les conditions d'utilisation de Discord et peut faire fermer le compte.** La surveillance tourne en continu : le risque est plus grand que pour un export ponctuel. Un **bot** est recommandé. Dindon détecte le type de jeton comme l'exportateur (compte d'abord, puis bot) et **affiche un bandeau d'avertissement dans l'interface** tant qu'un compte personnel est utilisé.

Le jeton se met dans `.env` (`DISCORD_TOKEN`). Il passe à l'exportateur par l'environnement, jamais sur la ligne de commande, et n'apparaît dans aucun journal. `.env` est ignoré par Git.

## A. À la main : le dossier `inbox/`

Tout fichier `.json` déposé dans `inbox/` est importé dans les secondes qui suivent, puis rangé dans `archive/AAAA-MM/`. Rien n'est perdu et rien n'est dupliqué :

- un fichier déjà importé (même empreinte) est ignoré ; deux exports qui se chevauchent ne créent aucun doublon ;
- un message modifié est mis à jour, avec ses pièces jointes, mentions, émojis et réactions ;
- un export plus ancien que ce que la base sait déjà n'écrase jamais rien (l'ordre des fichiers n'a pas d'importance) ;
- l'exportateur laisse son fichier **vide pendant le travail** et l'écrit à la fin : un fichier vide attend ; un fichier illisible depuis plus d'une minute est mis de côté dans `inbox/failed/` avec la raison (`.error.txt`).

Sans application : `dindon ingest dossier/ fichier.json …`.

## B. La surveillance

Dans `.env` :

```
DISCORD_TOKEN=...            # un jeton de bot de préférence
DINDON_GUILD_IDS=123456789   # un ou plusieurs serveurs, séparés par des virgules
DINDON_POLL_SECONDS=30       # 30 à 60 est poli
```

et l'exportateur dans `exporter/bin/` (voir [exporter/README.md](../exporter/README.md)).

**Premier import, une fois, à la main.** Rien n'est exporté tant qu'il n'a pas eu lieu : démarrer la surveillance sur un gros serveur ne lance jamais un export gigantesque par surprise (l'interface le rappelle).

```console
dindon backfill                  # tous les serveurs de DINDON_GUILD_IDS ; --parallel 2 salons à la fois par défaut
```

Il se **reprend** là où il s'est arrêté : un salon à jour est sauté, un salon à moitié importé continue après son message le plus récent. Chaque salon est coupé en fichiers de 50 000 messages, complets chacun. **Les réactions coûtent une requête chacune** (la liste de qui a réagi) : c'est le poste le plus lent d'un premier import. L'exportateur n'a pas d'option pour les différer ; le temps d'un gros serveur est une **estimation** (voir [MESURES.md](MESURES.md)), pas une mesure.

**Ensuite, en continu** (`docker compose up`, ou `dindon serve`) :

1. toutes les `DINDON_POLL_SECONDS`, **une requête par serveur** (`GET /guilds/{id}/channels`) donne l'identifiant du dernier message de chaque salon ; avec un bot, une deuxième liste les fils actifs ;
2. un salon dont le dernier message est plus récent que celui de la base est exporté avec `--after <dernier identifiant connu>` : seul ce qui est nouveau est téléchargé. Les autres ne coûtent rien ;
3. le fichier est importé, archivé, et le lien concerné s'illumine dans l'interface (délai : environ la moitié de l'intervalle, plus une fraction de seconde) ;
4. un **salon créé après le premier import** est exporté en entier ; un ancien salon qui manquait au premier import (accès refusé ?) n'est pas repris par la surveillance : c'est `dindon backfill` qui décide.

**Rattrapage nocturne.** Une fois par jour (à 3 h UTC, `DINDON_CATCHUP_HOUR`), les 7 derniers jours (`DINDON_CATCHUP_DAYS`) sont exportés à nouveau : c'est la seule façon de voir les **modifications et les suppressions** sans bot. Un message de la base que l'export n'a plus dans cette fenêtre est supprimé (ses liens sont recalculés exactement). Garde-fou : si l'export semble manquer de **plus de 30 %** de la fenêtre (et d'au moins 50 messages), on le croit défectueux et **rien n'est supprimé**. On peut le lancer à la main : `dindon catchup`.

**En cas de problème** : un salon qui échoue est laissé de côté 30 s, puis deux fois plus longtemps, jusqu'à 15 minutes ; une limitation de débit de Discord (429) met tout en pause aussi longtemps que Discord le demande ; la dernière erreur s'affiche en bas de l'interface (sans jeton ni contenu de message).

### Limites connues

- **Fils de discussion avec un compte** : un compte ne peut pas lister les fils actifs d'un serveur (l'exportateur passe par une recherche salon par salon, trop de requêtes pour un relevé toutes les 30 s). Les fils sont donc exportés **avec leur salon parent** (`--include-threads`, réglable avec `DINDON_THREADS`) quand celui-ci bouge, et par le rattrapage nocturne. Un message dans un ancien fil peut attendre la nuit. Avec un **bot**, les fils actifs sont surveillés un par un.
- **Fils archivés** : ils ne sont pris que par un `backfill` avec `DINDON_THREADS=all`.
- **Un message supprimé en dernier** reste en base jusqu'à ce qu'un message plus récent arrive dans le salon (le rattrapage ne juge rien de plus récent que le dernier message de l'export).
- **Reproduction réelle** : tout ceci est testé contre un faux Discord et un faux exportateur. **Rien n'a encore tourné contre le vrai Discord** (pas de jeton). Les arguments passés à l'exportateur ont été vérifiés contre le vrai programme (il les accepte), pas son comportement sur un vrai serveur.

## Essayer sans Discord

```console
make setup && make web
make demo        # http://127.0.0.1:8011, mot de passe : demo
```

Un faux Discord (serveur inventé de 60 personnes) répond comme le vrai, le premier import se fait avec `dindon backfill`, puis les personnes inventées continuent à parler : on voit les liens s'illuminer.
