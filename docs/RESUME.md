# Dindon en résumé

> Mise à jour : 4 octobre 2026. Vue d'ensemble de l'application, de la collecte Discord (le « bot ») et de l'architecture. Les détails sont dans les pages listées à la fin ; **l'état pièce par pièce, avec le niveau de preuve de chaque affirmation, est dans [RAPPORT-COMPLET.md](RAPPORT-COMPLET.md)**.

## 1. L'idée

Dindon est une **carte vivante d'un serveur Discord**, entièrement **locale**. Il récupère les messages, les range dans une base, puis (à partir de la phase 2) les fait analyser par une IA locale pour savoir **de quoi parle chaque personne et ce qu'elle défend**, avec **les messages qui le prouvent**. Il relie les personnes selon leurs échanges, compare ce qu'elles disent aux **rôles d'idéologie qu'elles se sont donnés elles-mêmes**, et affiche le tout sur une carte dynamique.

Il est fait pour une seule personne (francophone), sur un serveur dont on est membre. Les données sont sensibles (opinions politiques de personnes identifiables, présence de mineurs) : tout reste sur la machine, derrière un mot de passe, et l'âge et le genre ne sont **jamais** analysés ni affichés.

## 2. Où on en est

| Phase | Contenu | État |
| --- | --- | --- |
| 0. Socle | base PostgreSQL, migrations, `/health`, tests | **fait** |
| 1. Carte des échanges, sans IA | import, surveillance, liens du graphe, API, direct, interface, démonstration | **fait** |
| 2. Découverte des thèmes | conversations, tri, vecteurs, regroupement, noms par un modèle local, **validation par vous** (page Thèmes) | **fait**, testé avec un faux Ollama et **mesuré** avec les vrais modèles sur des données inventées ; jamais lancé sur un vrai serveur ([ANALYSE.md](ANALYSE.md)) |
| 3. Affirmations et preuves | extraction par l'IA (avec la citation exacte, sinon refusée), propositions, citations cliquables (page Positions) | **fait**, **mesuré** sur données inventées ; jamais lancé sur un vrai serveur |
| 4. Classement et vérification | 21 axes, scores par personne, vérification des rôles d'idées (page Cohérence), validation des poids par une personne | **fait**, **mesuré** sur données inventées ([VALIDATION-AXES.md](VALIDATION-AXES.md)) |
| 5. Bot en direct, vie privée, exportateur, performance | bot Gateway, commandes `/dindon`, effacement, exportateur Python, limites de performance, lecture automatique | **fait** ; le bot et l'exportateur ont tourné sur le vrai Discord (en partie), le reste est testé avec des faux |
| 6. Débats | `/dindon debat` : fil, positions, minuteur, vote, statistiques, **vérification des affirmations sur Internet** (lecture à l'aveugle, sources de confiance, citations vérifiées), **corrections publiques** verrouillées par une précision mesurée, page Débats ([DEBAT.md](DEBAT.md)) | **fait**, testé avec un Discord, un modèle et un Internet simulés ; **lecture mesurée** avec le vrai modèle ; jamais sur un vrai Discord |
| À faire | modifications/suppressions/réactions en direct, rattrapage des trous après reconnexion, consentement préalable, pseudonymisation, rejeu dans le temps | voir [RAPPORT-COMPLET.md](RAPPORT-COMPLET.md) §16 |

« Fait » veut dire construit et testé (872 tests) avec des **faux** (Discord, Gateway, Ollama). **Sur le vrai Discord** ont tourné : la connexion du bot, la lecture de deux serveurs, l'ingestion de leurs messages, la lecture REST de l'exportateur et le rattrapage nocturne. **Jamais sur du vrai** : l'analyse par l'IA, les commandes `/dindon` utilisées par un membre, la fenêtre « Importer », un gros salon. Tout ce travail est dans `dindon/`, un dépôt Git local sans aucun dépôt distant ; la plus grande partie n'est pas commitée.

## 3. L'application

### Ce qu'on voit

- **La carte** : un point par personne (taille : poids de ses échanges ; couleur : activité récente), une ligne par paire de personnes qui se parlent. Une case **« Personnes sans lien »** (cochée au départ) ajoute toutes celles qui ont déjà écrit mais n'ont aucun lien affiché, en petits points, quelle que soit la période. Les noms sont lisibles ; les liens forment une toile discrète qui devient nette, avec le nom des interlocuteurs principaux, quand on **survole ou clique** une personne. Quand un nouvel échange arrive, **son lien s'illumine**.
- **La fiche d'une personne** (au clic) : activité, échanges envoyés et reçus, liens principaux, salons les plus fréquentés, et les rôles d'idéologie qu'elle s'est donnés (présentés comme **non vérifiés**). Ses **positions sur les idées** (avec la citation), **une barre par axe** (21 axes) avec la marge d'incertitude et ce qu'attendent les rôles qu'elle s'est donnés, ses thèmes et **avec qui elle en a parlé** (d'accord ou non).
- **Filtres** : période (tout, 90 / 30 / 7 jours, dates), types d'échanges (réponses, mentions, réactions), nombre de liens affichés, recherche d'une personne.
- **Bandeau et bas de page** : un **bandeau d'avertissement** en haut si un compte personnel est automatisé ; en bas, l'état du direct, le nombre de personnes et de liens, le dernier échange et l'état de la surveillance.

### Comment l'utiliser

| Besoin | Commande |
| --- | --- |
| Essayer tout de suite, sans Discord | `make setup && make web && make demo`, puis http://127.0.0.1:8011 (mot de passe : `demo`) |
| Lancer pour de bon | `cp .env.example .env` (choisir les deux mots de passe), `docker compose up -d --build`, puis http://127.0.0.1:8000 |
| Importer des exports à la main | les déposer dans `inbox/` (importés, puis rangés dans `archive/`) |
| Importer seulement une partie de l'historique | entrée **Importer** de la barre de gauche, ou `dindon backfill --channel … --from … --mentioning … --after … --before …` ([COLLECTE.md](COLLECTE.md)) : salons, personnes (par identifiant), période. Un import restreint par personnes ou par période est **partiel** : il ne compte pas comme un premier import. Testé avec un faux Discord |
| Inviter le bot sur un serveur | entrée **Inviter le bot** de l'interface : lien d'invitation (voir les salons, lire l'historique, rien d'autre) et serveurs où le bot est, suivis ou non. Inviter n'enregistre rien : seuls les serveurs de `DINDON_GUILD_IDS` sont suivis. Testé avec un faux Discord, jamais sur le vrai |
| Voir l'état de tout (bot, collecte, base, IA, serveurs suivis) | page **Système** : ce qui va bien, ce qui mérite un coup d'œil et le geste à faire. Le bot donne un signe de vie toutes les 30 s. Testé avec données simulées |
| Lancer les tests | `make test` |
| Vérifier la page dans un vrai navigateur | `make check-ui` (facultatif, demande Playwright) |

## 4. Le « bot » : comment les messages arrivent

**Le bot en direct tourne** (connecté à deux serveurs, il enregistre les nouveaux messages). Il n'a jamais été éprouvé en conditions réelles de charge ni de reconnexion. Les messages arrivent par trois portes qui mènent à la **même ingestion** :

| Mode | Fonctionnement | Délai | État |
| --- | --- | --- | --- |
| **A. À la main** | on dépose des exports JSON dans `inbox/` (par exemple faits par `dindon export`) | à la demande | fait |
| **B. Surveillance** | l'application regarde ce qui a bougé et fait lire ces seuls salons par l'exportateur de Dindon | environ la moitié de l'intervalle de relevé (15 s par défaut) | fait, testé contre un faux Discord |
| **C. Bot en direct** | un bot reçoit chaque nouveau message au moment où il est écrit (accès « Gateway »). Modifications et suppressions : **appliquées en direct** ; les réactions viennent au rattrapage nocturne | moins d'une seconde | fait ; **vrai Discord** : connexion, deux serveurs, un message ingéré en 69 ms ; charge **mesurée** avec un faux Gateway (300 messages/s sans perte) ([COLLECTE.md](COLLECTE.md)) |

### La surveillance (mode B)

1. **Premier import, une fois, à la main** : `dindon backfill`. Rien n'est exporté avant, pour ne jamais lancer un export gigantesque par surprise. Il se reprend là où il s'est arrêté ; les réactions coûtent une requête chacune, c'est le poste le plus lent.
2. **Ensuite, en continu** : toutes les 30 s (réglable), **une seule requête par serveur** donne le dernier message de chaque salon. Seuls les salons qui ont bougé sont exportés, avec `--after` : on ne télécharge que ce qui est nouveau.
3. **Rattrapage nocturne** : une fois par jour, les 7 derniers jours sont exportés à nouveau pour voir ce qui a été **modifié ou supprimé**. Un garde-fou refuse de supprimer si l'export semble manquer de plus de 30 % de la fenêtre.
4. En cas de souci : un salon qui échoue est laissé de côté un moment (30 s, puis plus longtemps), et une limitation de débit de Discord met tout en pause aussi longtemps que Discord le demande.

### Jeton : bot ou compte personnel

- Un **bot** est recommandé (il faut qu'un administrateur l'ajoute au serveur et active l'accès au contenu des messages).
- Un **compte personnel** fonctionne aussi, mais **Discord l'interdit en automatique** et peut fermer le compte. Dindon détecte le type de jeton et **affiche un bandeau d'avertissement** tant qu'un compte est utilisé.
- Le jeton et l'identifiant du serveur vont dans **`.env`** (`DISCORD_TOKEN`, `DINDON_GUILD_IDS`), jamais dans Git. Le jeton ne part que dans l'en-tête des requêtes à Discord, et n'apparaît dans aucun journal.

### Le bot en direct (mode C)

`app/dindon/bot/` : `gateway.py` (le seul fichier qui importe `discord.py`), `adapter.py` (un message du Gateway devient le même JSON v2 que celui de l'exportateur), `runner.py` (lots, signe de vie toutes les 30 s), `privacy_commands.py` (les commandes `/dindon`). Il suit les serveurs de `DINDON_GUILD_IDS`, ou **tous** ceux où il se trouve avec `DINDON_GUILD_IDS=all`. Modifications, suppressions et réactions ne sont pas reçues en direct : le rattrapage nocturne les corrige sur 7 jours ([COLLECTE.md](COLLECTE.md)).

### Limites connues

- **Fils de discussion avec un compte** : un compte ne peut pas les lister d'un coup ; ils sont exportés avec leur salon parent et par le rattrapage nocturne. Avec un bot, ils sont surveillés un par un.
- **L'exportateur de Dindon (Python, `app/dindon/export/`)** : testé contre un faux Discord qui répond comme l'API REST, et **essayé en lecture seule sur 474 messages réels** (identiques à ce que l'ancien exportateur avait écrit, à de petites lacunes connues près) ; jamais sur un gros serveur ([EXPORTATEUR.md](EXPORTATEUR.md)).

## 5. L'architecture

```
 Discord ──(A) export à la main ───────────► inbox/ ──┐
         ──(B) surveillance ─► exportateur Dindon ──┼─► ingestion ─► PostgreSQL 17 (+ pgvector)
         ──(C) bot en direct ─────────────────────────┘                  │         ▲
                                                                          │ NOTIFY  │ lectures
                                                                          ▼         │
                                                       API FastAPI + flux en direct (SSE) ──► carte web (Svelte + Sigma.js)

   analyse (conversations, thèmes, positions, axes)   ouvriers d'analyse ⇄ Ollama (hôte) ◄──► PostgreSQL
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
| `db` (PostgreSQL 17 + pgvector) | toute la donnée : 52 tables (37 du kit de départ, 2 de l'analyse, 1 des services, 2 de la vie privée, 1 des réglages, 8 des débats) et 9 vues, dont 21 axes (tous actifs) et leurs idéologies |
| `app` (Python, FastAPI) | un seul processus : ingestion, boîte `inbox/`, surveillance, API, flux en direct, et service de l'interface |
| exportateur de Dindon (`app/dindon/export/`, Python) | lit Discord et écrit les fichiers JSON v2, dans le même processus que l'application |
| interface (Svelte 5, Vite, Sigma.js, graphology) | carte WebGL, placement des points (ForceAtlas2) dans un thread à part |
| `ollama` (profil optionnel) | l'IA locale pour un serveur Linux ; sur un Mac, Ollama tourne directement sur la machine (GPU) et l'application le joint par `host.docker.internal` |

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
  tests/           872 tests, données inventées uniquement
  docs/            la documentation, en français
```

## 6. L'analyse par IA (étapes 1 à 7 faites, jamais lancées sur de vraies données)

L'IA ne lit pas tout : c'est une **cascade** qui garde le coûteux pour la fin. **Les étapes 1 à 7 sont faites** et mesurées sur des données inventées : voir [ANALYSE.md](ANALYSE.md) pour l'installation, l'usage et les mesures, et [VALIDATION-AXES.md](VALIDATION-AXES.md) pour les axes. L'étape 6 (nature des réponses : accord, désaccord…) est remplacée par le calcul « avec qui elle en a parlé et d'accord ou non » à partir des positions.

1. **Conversations** (SQL) : regrouper les messages en discussions (coupure après 20 min de silence, 40 messages au plus).
2. **Tri** (SQL) : écarter robots, messages vides, « mdr » ; noter l'importance.
3. **Vecteurs** puis **thèmes**, découverts automatiquement, **sans tenir compte des personnes**, validés ensuite par l'utilisateur.
4. **Extraction** : le modèle liste ce que chaque personne affirme, avec les identifiants des messages qui le prouvent. Sans preuve, pas d'affirmation.
5. **Normalisation** : chaque affirmation est rattachée à une proposition (« il faut augmenter le SMIC ») ; position pour, contre ou nuancée.
6. **Relations** : nature de chaque réponse (accord, désaccord, soutien, moquerie, information).
7. **Scores** par axe, calculés en SQL (déjà fait et testé), puis **vérification avec les rôles** : verdict par axe, puis par rôle (concordant, discordant, non vérifiable). « Discordant » est une alerte à regarder, pas une accusation.

**Les axes** : les 21 axes (12 du modèle « 12 Axes » + 9 ajoutés) sont **tous actifs** depuis le 4 octobre 2026 ([AXES.md](AXES.md) ; mesuré : l'IA range 37 % des phrases sur un mauvais axe avec 12 axes, 13 % avec 21). Les axes, idéologies, plages et règles de rôles sont à relire par l'utilisateur : le code ne les modifie jamais.

**Les modèles « System One »** (Laya, Kev, mini-jev…) répondent à des questions à choix en une seule passe. Mon avis : **utiles plus tard** pour les étapes à choix fermé et très nombreuses (nature d'une réponse, position, thème), **pas** pour l'extraction ni les résumés, et **pas maintenant**. Test sur ce Mac, 52 exemples français écrits à la main (petit jeu, sans réglage) : Laya multilingue réussit 66 % de la prise de position (33 % au hasard) et 60 % de la nature d'une réponse (20 % au hasard), à 20-26 ms par décision. Trop peu fiable sans réglage ; Kev est en anglais seulement. Plan : d'abord la chaîne avec le modèle de langue, puis comparer sur 200 exemples annotés.

## 7. Garde-fous

- Local seulement, mot de passe, jamais exposé sur Internet ; journaux sans contenu de messages ni jetons.
- **Âge et genre écartés** partout (les rôles de ces types sont reconnus pour être ignorés ; un test vérifie qu'aucune fiche ne les montre).
- **Aucune inférence indirecte** (style, horaires, fréquentations) ; étiquettes toujours avec preuves et incertitude.
- Aucune donnée réelle dans le dépôt ; les tests n'utilisent que des données inventées.
- **Effacement durable : fait** (registre des personnes qui ont demandé l'arrêt : un export ultérieur ne les réimporte pas ; commandes `/dindon`, page « Vie privée », [CONFORMITE.md](CONFORMITE.md)). **À faire** : mode pseudonymisé, consentement préalable.
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

1. **Renseigner le contact, la durée de conservation et les serveurs suivis** (`.env`), informer les membres : voir [RAPPORT-COMPLET.md](RAPPORT-COMPLET.md) §0 et §16.
2. Valider les fourchettes d'idéologie ([AXES.md](AXES.md)) : c'est ce qui décide le plus de la qualité de la vérification des rôles.
3. Lancer l'analyse sur un serveur dont les membres sont informés, puis **valider les poids des axes** avant de lire les scores.
4. **Essayer les débats** sur un serveur de test avec des participants informés : voir « Comment l'activer » dans [DEBAT.md](DEBAT.md) (réinviter le bot, un service de recherche, `DINDON_DEBATE_CHECKS=observe`), puis mesurer avec `tools/measure_claims.py` avant tout `live`.
5. Appliquer aussi les réactions en direct (le reste, modifications, suppressions et tour du relevé après une coupure, est fait).

## 10. Pour en savoir plus

| Page | Contenu |
| --- | --- |
| [README](../README.md) | installer, utiliser, sauvegarder, dépanner |
| [COLLECTE.md](COLLECTE.md) | exports à la main, surveillance, premier import, limites |
| [ARCHITECTURE.md](ARCHITECTURE.md) | l'architecture complète d'origine, avec ses mesures |
| [DECISIONS.md](DECISIONS.md) | chaque choix, et pourquoi |
| [MESURES.md](MESURES.md) | ce qui est mesuré et ce qui est estimé |
| [AXES.md](AXES.md) | les axes et idéologies à relire |
| [EXPORTATEUR.md](EXPORTATEUR.md) | l'exportateur de Dindon : ce qu'il fait, ses réglages, le premier essai réel |
| [DEBAT.md](DEBAT.md) | `/dindon debat` : le débat encadré (fil, positions, minuteur, vote de fin, vérification des faits) : décisions, règles, état par fonction |
| [RAPPORT-COMPLET.md](RAPPORT-COMPLET.md) | l'état de chaque pièce, avec le niveau de preuve |
| [VALIDATION-AXES.md](VALIDATION-AXES.md) | les axes de l'IA : mesures, validation, ce qui reste |
