# Collecter les messages

Dindon ne lit jamais Discord lui-même : il s'appuie sur l'**exportateur** (DiscordChatExporter) et sur le format JSON version 2 ([contracts/JSON-format.md](../contracts/JSON-format.md)). Trois façons d'alimenter la base, qui passent toutes par la même ingestion :

| Mode | Délai | Ce qu'il faut |
| --- | --- | --- |
| **A. Export à la main** : déposer des fichiers JSON dans `inbox/` | à la demande | rien (l'application graphique de l'exportateur suffit) |
| **B. Surveillance** : l'application regarde ce qui a bougé et lance l'exportateur | environ la moitié de l'intervalle de relevé (15 s par défaut) | un jeton, l'identifiant du serveur, l'exportateur |
| **C. Bot en direct** | moins d'une seconde | un jeton de **bot**, l'identifiant du serveur, l'option « Message Content Intent » du bot. **Écrit et testé avec un faux Gateway ; jamais essayé sur le vrai Discord** |

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

## Importer une partie de l'historique

`dindon backfill` seul importe **tout** l'historique de tous les salons. On peut le restreindre, en ligne de commande ou depuis l'interface (bouton **Importer…**, en haut de la page) :

```console
docker compose exec app dindon backfill --channel général --channel sql            # ces salons, en entier
docker compose exec app dindon backfill --channel général --from 123456789012345678 # seulement les messages de cette personne
docker compose exec app dindon backfill --mentioning 123456789012345678 --after 2025-09-01 --before 2025-09-30
```

| Option | Effet |
| --- | --- |
| `--channel NOM_OU_ID` (répétable) | seulement ces salons, par nom (casse et accents sans importance) ou par identifiant. **Ils sont importés en entier** |
| `--from ID` (répétable) | seulement les messages **écrits par** ces personnes (identifiant Discord : clic droit sur la personne, mode développeur, « Copier l'identifiant ») |
| `--mentioning ID` (répétable) | seulement les messages qui **mentionnent** ces personnes. Avec `--from`, il faut les deux (les personnes d'un même groupe sont un « ou ») |
| `--after JJ`, `--before JJ` | seulement cette période, **premier et dernier jour inclus** (UTC) |

**Un import restreint par personnes ou par période est « partiel ».** Il ne ramène qu'une partie de ce que contient un salon, donc :
- il **ne compte pas comme un premier import** (la surveillance attend toujours un `dindon backfill` complet) ;
- il ne marque pas le salon « à jour » : un import complet fait plus tard rapporte tout, y compris ce que l'import partiel avait déjà pris (rien n'est dupliqué) ;
- le graphe qu'il produit est incomplet (seuls les messages choisis, donc seulement les liens qu'ils portent).

Choisir seulement des salons n'est **pas** partiel : ils sont importés complètement.

C'est l'exportateur qui filtre (`--filter`, `--after`, `--before`) : ce qui ne correspond pas n'est même pas téléchargé. L'expression de filtre produite a été vérifiée contre l'analyseur du **vrai** exportateur, sans connexion. Une copie JSON de chaque export est gardée dans `archive/` comme pour les autres imports.

**Depuis l'interface**, la fenêtre liste les salons tels que Discord les montre maintenant (même ceux jamais importés), demande les filtres, lance l'import en arrière-plan avec sa progression, et permet de l'**annuler** (l'exportateur est arrêté ; ce qu'il n'avait pas fini n'est pas importé). On peut la fermer : l'import continue. Un seul import à la fois ; seuls les serveurs de `DINDON_GUILD_IDS` peuvent être importés. **Testé avec un faux Discord seulement, jamais sur le vrai.**

## C. Le bot en direct

Un processus à part (`dindon bot`, service `bot` de Docker Compose, même image que l'application) reste connecté au Gateway de Discord et reçoit chaque **nouveau message** au moment où il est écrit. Il ne contient aucune logique d'analyse : il transforme l'événement en document JSON version 2 et le confie à **la même ingestion** que les deux autres modes (voir [DECISIONS.md](DECISIONS.md)). L'application affiche le lien de la même façon (NOTIFY puis SSE).

**Ce qu'il demande à Discord** : les serveurs (rôles, salons, fils) et les messages avec leur contenu. Ni la liste des membres, ni les présences, ni les réactions. Il ne suit **que** les serveurs de `DINDON_GUILD_IDS` (liste obligatoire) et ignore le reste sans le regarder. Ses journaux disent combien de messages, jamais lesquels.

**Ce qu'il fait (étape M1)** : les nouveaux messages, avec leurs réponses et mentions. **Ce qu'il ne fait pas encore** : les modifications, les suppressions et les réactions arrivent sur la même connexion, sont comptées, **mais ne sont pas appliquées**. Le rattrapage nocturne (et la surveillance, si elle tourne) les apportent, comme avant.

Pour l'essayer seul, couper la surveillance (`DINDON_COLLECTOR=off`), puis :

```console
docker compose up -d --build
docker compose --profile bot up -d --build
docker compose logs -f bot
```

**Limites connues**

- **Un message supprimé reste en base** jusqu'au rattrapage nocturne (3 h UTC par défaut), et une modification n'est pas vue avant.
- **Ce que le bot ne sait pas décrire** (le rattrapage le complète) : aperçus de liens (Discord les ajoute après coup), sondages, messages transférés, émojis Unicode du texte (l'exportateur les repère avec sa table complète).
- **Reconnexion** : une coupure courte est reprise sans rien perdre. Si Discord invalide la session, une **nouvelle session** démarre et ce qui s'est écrit entre-temps n'est pas reçu : le bot le signale (« reconnected with a new session »). **Seul le rattrapage nocturne comble ce trou** (il ré-exporte les 7 derniers jours ; à la main : `dindon catchup`). **La surveillance ne le voit pas** : elle ne cherche que ce qui est plus récent que le dernier message connu (c'est testé). Il n'y a pas encore de rattrapage automatique déclenché par le bot.
- **Le bot n'est pas un premier import** : ce qu'il écrit ne compte ni pour la surveillance (« premier import fait ») ni pour `dindon backfill` (« reprendre après le message le plus récent connu »). `dindon backfill` apporte tout l'historique, que le bot ait tourné avant ou après.
- **Un événement reçu pendant que la base est indisponible ou pas encore migrée** attend et est réessayé ; au-delà de 5 000 messages en attente, les plus récents sont abandonnés (et comptés) ; le rattrapage les rapporte.
- **Texte des messages** : le bot reproduit la mise en forme de l'exportateur (mentions en noms, émojis personnalisés, dates), d'après la lecture de son code. La comparaison avec la sortie réelle de l'exportateur se fait sur un vrai serveur avec `tools/compare_with_export.py`. Les dates écrites dans un message (`<t:…>`) sont mises en forme en UTC, culture invariante.
- **Rien n'est archivé** : le bot n'écrit aucun fichier dans `archive/` ; la base est sa seule trace.
- **Jamais essayé sur le vrai Discord.** Tout ce qui précède est testé avec un faux Gateway.

## Essayer sans Discord

```console
make setup && make web
make demo        # http://127.0.0.1:8011, mot de passe : demo
```

Un faux Discord (serveur inventé de 60 personnes) répond comme le vrai, le premier import se fait avec `dindon backfill`, puis les personnes inventées continuent à parler : on voit les liens s'illuminer.
