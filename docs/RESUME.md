# Dindon en résumé

> Mise à jour : 2 octobre 2026. Vue d'ensemble de l'application, de la collecte Discord (le « bot ») et de l'architecture. Les détails sont dans les pages listées à la fin.

## 1. L'idée

Dindon est une **carte vivante d'un serveur Discord**, entièrement **locale**. Il récupère les messages, les range dans une base, puis (à partir de la phase 2) les fait analyser par une IA locale pour savoir **de quoi parle chaque personne et ce qu'elle défend**, avec **les messages qui le prouvent**. Il relie les personnes selon leurs échanges, compare ce qu'elles disent aux **rôles d'idéologie qu'elles se sont donnés elles-mêmes**, et affiche le tout sur une carte dynamique.

Il est fait pour une seule personne (francophone), sur un serveur dont on est membre. Les données sont sensibles (opinions politiques de personnes identifiables, présence de mineurs) : tout reste sur la machine, derrière un mot de passe, et l'âge et le genre ne sont **jamais** analysés ni affichés.

## 2. Où on en est

| Phase | Contenu | État |
| --- | --- | --- |
| 0. Socle | base PostgreSQL, migrations, `/health`, tests | **fait** |
| 1. Carte des échanges, sans IA | import, surveillance, liens du graphe, API, direct, interface, démonstration | **fait** |
| 2. Découverte des thèmes | banc d'essai du modèle, vecteurs, regroupement, validation | à faire (Ollama pas installé) |
| 3. Affirmations et preuves | extraction par l'IA, propositions, citations cliquables | à faire |
| 4. Classement et vérification | scores sur les axes, vérification avec les rôles, file « à revoir » | à faire (le calcul existe déjà en SQL) |
| 5. Finitions | rejeu dans le temps, cartes de divertissement, pseudonymes, effacement, bot en direct | à faire |

« Fait » veut dire construit et testé (78 tests) **avec un faux Discord** : **rien n'a encore tourné contre le vrai Discord** (pas de jeton). Tout ce travail est dans `dindon/`, un dépôt Git local sans aucun dépôt distant ; la dernière étape (interface, documentation, outils) n'est pas encore commitée.

## 3. L'application

### Ce qu'on voit

- **La carte** : un point par personne (taille : poids de ses échanges ; couleur : activité récente), une ligne par paire de personnes qui se parlent. Une case **« Personnes sans lien »** (cochée au départ) ajoute toutes celles qui ont déjà écrit mais n'ont aucun lien affiché, en petits points, quelle que soit la période. Les noms sont lisibles ; les liens forment une toile discrète qui devient nette, avec le nom des interlocuteurs principaux, quand on **survole ou clique** une personne. Quand un nouvel échange arrive, **son lien s'illumine**.
- **La fiche d'une personne** (au clic) : activité, échanges envoyés et reçus, liens principaux, salons les plus fréquentés, et les rôles d'idéologie qu'elle s'est donnés (présentés comme **non vérifiés**). Les positions sur les idées et leur vérification arrivent avec les phases 3 et 4.
- **Filtres** : période (tout, 90 / 30 / 7 jours, dates), types d'échanges (réponses, mentions, réactions), nombre de liens affichés, recherche d'une personne.
- **Bandeau et bas de page** : un **bandeau d'avertissement** en haut si un compte personnel est automatisé ; en bas, l'état du direct, le nombre de personnes et de liens, le dernier échange et l'état de la surveillance.

### Comment l'utiliser

| Besoin | Commande |
| --- | --- |
| Essayer tout de suite, sans Discord | `make setup && make web && make demo`, puis http://127.0.0.1:8011 (mot de passe : `demo`) |
| Lancer pour de bon | `cp .env.example .env` (choisir les deux mots de passe), `docker compose up -d --build`, puis http://127.0.0.1:8000 |
| Importer des exports à la main | les déposer dans `inbox/` (importés, puis rangés dans `archive/`) |
| Lancer les tests | `make test` |
| Vérifier la page dans un vrai navigateur | `make check-ui` (facultatif, demande Playwright) |

## 4. Le « bot » : comment les messages arrivent

**Le bot en direct existe mais n'a jamais tourné sur le vrai Discord.** Les messages arrivent par trois portes qui mènent à la **même ingestion** :

| Mode | Fonctionnement | Délai | État |
| --- | --- | --- | --- |
| **A. À la main** | on dépose des exports JSON dans `inbox/` (par exemple faits avec l'application graphique de l'exportateur) | à la demande | fait |
| **B. Surveillance** | l'application regarde ce qui a bougé et lance l'exportateur pour ces seuls salons | environ la moitié de l'intervalle de relevé (15 s par défaut) | fait, testé contre un faux Discord |
| **C. Bot en direct** | un bot reçoit chaque nouveau message au moment où il est écrit (accès « Gateway »). Modifications, suppressions et réactions : **pas encore appliquées** | moins d'une seconde | écrit, **testé avec un faux Gateway seulement** ; jamais essayé sur le vrai Discord ([COLLECTE.md](COLLECTE.md)) |

### La surveillance (mode B)

1. **Premier import, une fois, à la main** : `dindon backfill`. Rien n'est exporté avant, pour ne jamais lancer un export gigantesque par surprise. Il se reprend là où il s'est arrêté ; les réactions coûtent une requête chacune, c'est le poste le plus lent.
2. **Ensuite, en continu** : toutes les 30 s (réglable), **une seule requête par serveur** donne le dernier message de chaque salon. Seuls les salons qui ont bougé sont exportés, avec `--after` : on ne télécharge que ce qui est nouveau.
3. **Rattrapage nocturne** : une fois par jour, les 7 derniers jours sont exportés à nouveau pour voir ce qui a été **modifié ou supprimé**. Un garde-fou refuse de supprimer si l'export semble manquer de plus de 30 % de la fenêtre.
4. En cas de souci : un salon qui échoue est laissé de côté un moment (30 s, puis plus longtemps), et une limitation de débit de Discord met tout en pause aussi longtemps que Discord le demande.

### Jeton : bot ou compte personnel

- Un **bot** est recommandé (il faut qu'un administrateur l'ajoute au serveur et active l'accès au contenu des messages).
- Un **compte personnel** fonctionne aussi, mais **Discord l'interdit en automatique** et peut fermer le compte. Dindon détecte le type de jeton comme l'exportateur et **affiche un bandeau d'avertissement** tant qu'un compte est utilisé.
- Le jeton et l'identifiant du serveur vont dans **`.env`** (`DISCORD_TOKEN`, `DINDON_GUILD_IDS`), jamais dans Git. Le jeton passe à l'exportateur par l'environnement, jamais sur la ligne de commande, et n'apparaît dans aucun journal.

### Le bot en direct (mode C), plus tard

L'ingestion est faite pour le recevoir : elle prend des messages décrits dans le format JSON version 2 et met à jour la base, les liens et les notifications de la même façon quelle que soit l'origine. Le bot n'est **pas** écrit, et il n'y a pas encore de classe `Source` dédiée : il faudra qu'il produise les mêmes écritures, sans toucher à l'ingestion.

### Limites connues

- **Fils de discussion avec un compte** : un compte ne peut pas les lister d'un coup ; ils sont exportés avec leur salon parent et par le rattrapage nocturne. Avec un bot, ils sont surveillés un par un.
- **Rien n'a tourné contre le vrai Discord.** L'exportateur a été compilé pour Linux ARM64 : il démarre dans l'image et accepte les arguments de la surveillance, rien de plus n'est vérifié.

## 5. L'architecture

```
 Discord ──(A) export à la main ───────────► inbox/ ──┐
         ──(B) surveillance ─► exportateur ───────────┼─► ingestion ─► PostgreSQL 17 (+ pgvector)
         ──(C) bot en direct  (à faire) ──────────────┘                  │         ▲
                                                                          │ NOTIFY  │ lectures
                                                                          ▼         │
                                                       API FastAPI + flux en direct (SSE) ──► carte web (Svelte + Sigma.js)

   (à faire, phases 2 à 5)   ouvriers d'analyse ⇄ Ollama (modèle de langue + vecteurs) ◄──► PostgreSQL
```

**Cinq principes**

1. **Un seul contrat avec Discord** : le JSON version 2 de l'exportateur. Le bot en direct doit en reproduire la mise en forme du texte (adaptateur `app/dindon/bot/adapter.py`, d'après le code de l'exportateur) : c'est la seule partie de la lecture de Discord que Dindon réécrit, et elle se vérifie avec `tools/compare_with_export.py`.
2. **Une seule base** : PostgreSQL sert à la fois de stockage, de file de tâches, de bus d'événements (`LISTEN/NOTIFY`), de recherche en français, de base de vecteurs et de graphe. Ni Redis, ni Kafka, ni Neo4j, ni Elasticsearch, ni microservices.
3. **Pas de classement sans preuve** : une position n'existe que si elle cite des messages, et s'affiche avec son nombre de preuves et son incertitude.
4. **Deux vitesses** : les liens entre personnes (réponses, mentions, réactions) se mettent à jour tout de suite, sans IA ; les idées passent par l'IA et arrivent en quelques minutes.
5. **Tout en local** : aucune requête vers l'extérieur hors Discord (via l'exportateur), aucune police ou bibliothèque chargée depuis Internet.

**Les pièces**

| Pièce | Rôle |
| --- | --- |
| `db` (PostgreSQL 17 + pgvector) | toute la donnée : 37 tables et 9 vues du kit de départ, dont 21 axes (12 actifs) et leurs idéologies |
| `app` (Python, FastAPI) | un seul processus : ingestion, boîte `inbox/`, surveillance, API, flux en direct, et service de l'interface |
| exportateur (programme C#) | lit Discord et écrit les fichiers JSON ; monté depuis `exporter/bin/` |
| interface (Svelte 5, Vite, Sigma.js, graphology) | carte WebGL, placement des points (ForceAtlas2) dans un thread à part |
| `ollama` (profil optionnel) | l'IA locale ; pas encore utilisée |

**Ce que fait l'ingestion** (`app/dindon/ingest/`) : un fichier = une transaction ; **idempotente** (un fichier déjà importé est ignoré, deux exports qui se chevauchent ne créent aucun doublon) ; un message modifié est mis à jour avec ses pièces jointes, mentions, émojis et réactions ; un export plus ancien que ce que la base sait n'écrase jamais rien ; l'identité d'une personne est son **identifiant**, jamais son nom.

**Les liens du graphe** : une ligne par paire de personnes et par type de lien (réponse, mention, réaction), avec un poids qui **décroît avec le temps** (demi-vie de 90 jours). Ils sont mis à jour à chaque import par la différence entre ce que la base savait et ce que le fichier dit, donc exacts même si un message est modifié ou si un export arrive en retard. Un test vérifie qu'ils sont identiques à ceux recalculés depuis zéro.

**Le direct** : à la fin d'un import, PostgreSQL émet un `NOTIFY` ; l'application le relaie par Server-Sent Events à la page ; la page allume le lien concerné.

**Sécurité** : l'interface écoute sur `127.0.0.1`, derrière un mot de passe (cookie signé, `HttpOnly`, `SameSite=Strict`) ; l'application **refuse de démarrer sans mot de passe** ; une politique de sécurité de contenu interdit au navigateur de charger quoi que ce soit hors de l'application (donc aucun avatar Discord, aucune police externe).

```
dindon/
  app/dindon/      application : ingest/, collector/, api/, migrate.py, config.py
  db/              fichiers SQL du kit (inchangés) et migrations
  web/             interface (Svelte + Sigma.js)
  contracts/       le contrat de données (JSON version 2)
  tools/           démonstration, faux Discord, vérification de la page, mesures
  tests/           78 tests, données inventées uniquement
  exporter/        l'exportateur (binaire non versionné)
  docs/            la documentation, en français
```

## 6. L'analyse par IA (prévue, phases 2 à 5)

L'IA ne lit pas tout : c'est une **cascade** qui garde le coûteux pour la fin.

1. **Conversations** (SQL) : regrouper les messages en discussions (coupure après 20 min de silence, 40 messages au plus).
2. **Tri** (SQL) : écarter robots, messages vides, « mdr » ; noter l'importance.
3. **Vecteurs** puis **thèmes**, découverts automatiquement, **sans tenir compte des personnes**, validés ensuite par l'utilisateur.
4. **Extraction** : le modèle liste ce que chaque personne affirme, avec les identifiants des messages qui le prouvent. Sans preuve, pas d'affirmation.
5. **Normalisation** : chaque affirmation est rattachée à une proposition (« il faut augmenter le SMIC ») ; position pour, contre ou nuancée.
6. **Relations** : nature de chaque réponse (accord, désaccord, soutien, moquerie, information).
7. **Scores** par axe, calculés en SQL (déjà fait et testé), puis **vérification avec les rôles** : verdict par axe, puis par rôle (concordant, discordant, non vérifiable). « Discordant » est une alerte à regarder, pas une accusation.

**Les axes** : les 12 axes du modèle « 12 Axes » sont actifs ; 9 axes ajoutés restent inactifs tant que l'utilisateur ne les a pas relus ([AXES.md](AXES.md)). Les axes, idéologies, plages et règles de rôles sont à relire par l'utilisateur : le code ne les modifie jamais.

**Les modèles « System One »** (Laya, Kev, mini-jev…) répondent à des questions à choix en une seule passe. Mon avis : **utiles plus tard** pour les étapes à choix fermé et très nombreuses (nature d'une réponse, position, thème), **pas** pour l'extraction ni les résumés, et **pas maintenant**. Test sur ce Mac, 52 exemples français écrits à la main (petit jeu, sans réglage) : Laya multilingue réussit 66 % de la prise de position (33 % au hasard) et 60 % de la nature d'une réponse (20 % au hasard), à 20-26 ms par décision. Trop peu fiable sans réglage ; Kev est en anglais seulement. Plan : d'abord la chaîne avec le modèle de langue, puis comparer sur 200 exemples annotés.

## 7. Garde-fous

- Local seulement, mot de passe, jamais exposé sur Internet ; journaux sans contenu de messages ni jetons.
- **Âge et genre écartés** partout (les rôles de ces types sont reconnus pour être ignorés ; un test vérifie qu'aucune fiche ne les montre).
- **Aucune inférence indirecte** (style, horaires, fréquentations) ; étiquettes toujours avec preuves et incertitude.
- Aucune donnée réelle dans le dépôt ; les tests n'utilisent que des données inventées.
- **À faire (phase 5)** : mode pseudonymisé, et effacement durable : `forget_user()` supprime une personne, mais un export ultérieur la réimporterait ; il faudra une liste de personnes oubliées.
- Rappel : un usage strictement personnel est hors du champ du RGPD, **plus dès que les fiches sont montrées à d'autres**.

## 8. Chiffres mesurés

Mac M4 Pro 24 Go, PostgreSQL dans Docker, données inventées ([MESURES.md](MESURES.md)).

| Mesure | Résultat |
| --- | --- |
| Import de 500 000 messages | 26,5 s, 149 Mo de mémoire |
| Taille de la base | 428 octets par message |
| Petit lot en direct (10 / 1 000 messages) | 84 ms / 153 ms |
| Graphe de 400 personnes (20 000 liens) | 200 à 300 ms ; affiché en 1,8 s |
| Un échange → le lien s'allume (relevé toutes les 2 s) | de 0,10 à 1,96 s ; avec 30 s, comptez 15 s en moyenne |

**Limites** : un seul gros fichier demande environ 10 fois sa taille en mémoire (le premier import coupe en fichiers de 50 000 messages) ; l'interface n'a pas été mesurée au-delà de 400 personnes ; tout ce qui touche à Discord réel et à l'IA locale est **estimé**, pas mesuré.

## 9. Ce qui vient ensuite

1. Fournir un jeton et l'identifiant du serveur pour un premier essai réel (voir la section « Collecter » du [README](../README.md)).
2. Installer Ollama et comparer deux ou trois modèles (phase 2). Le téléchargement de Laya (1,3 Go) a pris 21 minutes : prévoir plusieurs heures pour des modèles de 5 à 9 Go.
3. Relire les axes et idéologies ([AXES.md](AXES.md)) : c'est ce qui décide le plus de la qualité du classement.
4. Phases 3 à 5, puis le bot en direct.

## 10. Pour en savoir plus

| Page | Contenu |
| --- | --- |
| [README](../README.md) | installer, utiliser, sauvegarder, dépanner |
| [COLLECTE.md](COLLECTE.md) | exports à la main, surveillance, premier import, limites |
| [ARCHITECTURE.md](ARCHITECTURE.md) | l'architecture complète d'origine, avec ses mesures |
| [DECISIONS.md](DECISIONS.md) | chaque choix, et pourquoi |
| [MESURES.md](MESURES.md) | ce qui est mesuré et ce qui est estimé |
| [AXES.md](AXES.md) | les axes et idéologies à relire |
| [../exporter/README.md](../exporter/README.md) | obtenir l'exportateur |
