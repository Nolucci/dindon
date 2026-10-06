# Rapport d'architecture de Dindon

*État au 4 octobre 2026. Ce rapport décrit ce qui existe dans le code et la base, pas ce qui est prévu. Chaque affirmation sur la qualité dit son niveau de preuve : **implémenté**, **testé** (avec Discord et les modèles simulés), **mesuré** (sur des données inventées), **jamais vu sur le vrai Discord**.*

## 1. En une page

Dindon est une **carte vivante d'un serveur Discord**, entièrement locale : qui parle avec qui, de quoi, et, si l'on active l'analyse, ce que chaque personne pense, avec la citation qui le prouve, et si les rôles d'idées qu'elle s'est donnés collent à ce qu'elle dit.

Il se compose de **quatre choses** :

1. **Une collecte** qui met les messages dans une base : un **bot** (temps réel), un **exportateur** (historique et rattrapage), des **fichiers déposés**. Tout passe par **une seule ingestion**.
2. **Une base PostgreSQL** (44 tables, 9 vues, pgvector) qui est la seule source de vérité.
3. **Une analyse par IA locale** (Ollama) en cascade : conversations → vecteurs → thèmes → positions avec preuves → axes → cohérence des rôles. Le code ne fait jamais confiance au modèle : il vérifie.
4. **Une application** (API FastAPI + interface Svelte/Sigma) et **un cadre de vie privée** (registre d'opposition, effacement, commandes Discord).

| | |
| --- | --- |
| Code | ~6 100 lignes de Python (`app/dindon`), ~6 100 lignes d'interface (`web/src`), 44 fichiers de tests (~344 fonctions de test, ~400 cas), 9 migrations SQL |
| Tourne sur | Docker Compose : `db`, `app`, `bot` (profil), `ollama` (option) ; Ollama sur la machine hôte |
| Données réelles aujourd'hui | 2 petits serveurs, 472 messages, enregistrés par le bot depuis quelques jours |
| Jamais fait | Un essai sur un vrai serveur avec beaucoup de monde ; les commandes `/dindon` utilisées par un vrai membre ; l'IA sur de vrais messages |

## 2. Vue d'ensemble

```
                         ┌─────────────── DISCORD ───────────────┐
                         │                                       │
        Gateway (direct) │                    API REST           │
                         ▼                          ▼            │
              ┌────────────────────┐   ┌─────────────────────┐   │
              │  BOT (discord.py)  │   │  EXPORTATEUR (C#)   │   │
              │  adapter → JSON v2 │   │  backfill / catch-up│   │
              └─────────┬──────────┘   │  / watch            │   │
                        │              └──────────┬──────────┘   │
                        │      inbox/ (fichiers JSON v2) ◄── dépôt à la main
                        ▼                         ▼
              ╔═══════════════════════════════════════════╗
              ║   INGESTION UNIQUE  (ingest/loader.py)    ║   verrou consultatif : un import à la fois
              ║   staging → registre vie privée → upsert  ║   liens du graphe tenus à jour
              ╚═════════════════════╤═════════════════════╝
                                    ▼
                  ┌───────────────────────────────────┐   NOTIFY ──► SSE ──► carte en direct
                  │  PostgreSQL 17 + pgvector         │
                  │  messages · personnes · liens ·   │
                  │  conversations · vecteurs ·       │
                  │  thèmes · positions · axes ·      │
                  │  registre vie privée · réglages   │
                  └──────┬─────────────────────▲──────┘
                         │                     │ écrit (positions, thèmes, scores)
              lit        ▼                     │
        ┌────────────────────────┐    ┌────────┴──────────────────┐
        │ API FastAPI (app)      │    │ ANALYSE (Ollama local)    │
        │ ~35 routes, cookie,    │◄───┤ job unique, cascade,      │
        │ SSE, CSP stricte       │    │ lecture automatique       │
        └───────────┬────────────┘    └───────────────────────────┘
                    ▼
        ┌────────────────────────┐
        │ Interface Svelte+Sigma │  Carte · Thèmes · Positions · Cohérence ·
        └────────────────────────┘  Système · Vie privée · Importer · Inviter
```

Le **contrat unique** entre la collecte et la base est le **JSON version 2** (`contracts/JSON-format.md` et son schéma) : le bot, l'exportateur et les fichiers déposés produisent tous le même document, et un seul code l'écrit en base. C'est ce qui permet de remplacer ou d'ajouter une source sans toucher au reste.

## 3. Les composants

### 3.1 Collecte (`app/dindon/bot`, `collector`, `ingest`)

| Source | Rôle | Fichiers | Ce qui est vrai |
| --- | --- | --- | --- |
| **Bot** (Gateway) | Les nouveaux messages en direct, comme le ferait un export | `bot/gateway.py` (le **seul** module qui importe discord.py), `adapter.py` (payload Discord → JSON v2, pur), `runner.py` (moteur : lots par salon, reprises, battement de cœur), `events.py` | **Testé** (faux Gateway) ; **tourne** sur vos deux serveurs ; 3 202/3 202 messages identiques à l'export sur le serveur de test (**simulé**) ; **mesuré** 300 messages/s sans perte |
| **Exportateur de Dindon** (Python, `app/dindon/export/`) | L'historique complet (`backfill`), le **rattrapage nocturne**, les modifications et suppressions | `export/` (exporter, client, filtres, writer), `collector/watch.py`, `job.py`, `selection.py`, `discord_api.py` | Remplace DiscordChatExporter (supprimé). **Testé contre un faux Discord qui répond comme l'API REST, et essayé en lecture seule sur 474 messages réels** ([EXPORTATEUR.md](EXPORTATEUR.md)) |
| **Dépôt de fichiers** | `inbox/` scruté toutes les 2 s ; les fichiers lus partent dans `archive/` | `ingest/inbox.py` | **Testé** |

Le bot **ne reçoit que les nouveaux messages** (pas les modifications, suppressions ni réactions) ; il le dit dans la page Système, et le rattrapage nocturne répare les trous (reconnexion avec nouvelle session : un trou possible, signalé au journal).

### 3.2 Ingestion (`ingest/loader.py`, 500 lignes, le cœur)

`ingest_document` : verrou consultatif (un import à la fois) → tables temporaires (`stg_*`) → **filtre du registre de vie privée** → écriture par `upsert` (personnes, rôles, membres, messages, pièces jointes, mentions, réactions) → mise à jour **incrémentale des liens** (arêtes pondérées avec demi-vie de 90 jours) → `NOTIFY` pour le temps réel. Un export plus ancien que ce qu'on sait ne fait qu'ajouter ce qui manque ; `only_new` (bot) n'ajoute que des messages nouveaux. **Mesuré** : ~18 900 messages/s (26,5 s pour 500 000), ~640 ms par fichier de 5 000 messages.

### 3.3 Base de données (`db/`, 44 tables, 9 vues)

Schéma de départ (`schema*.sql`, `seed-axes.sql`) puis 9 **migrations numérotées** appliquées au démarrage de l'application (une migration modifiée après coup est refusée).

| Domaine | Tables principales |
| --- | --- |
| Messages et personnes | `guilds`, `channels`, `users`, `members`, `roles`, `member_roles`, `messages`, `attachments`, `mentions`, `reactions`, `reaction_users`, `emojis`, `message_emojis`, `identity_history` (tous les pseudos vus) |
| Liens | `edges` (réponse, mention, réaction, pondérés dans le temps), vues `interactions`, `user_stats` |
| Analyse | `conversations`, `conversation_messages`, `conversation_embeddings`, `topic_runs`, `topics`, `topic_assignments`, `propositions`, `proposition_embeddings`, `proposition_axis`, `claims`, `claim_evidence`, `conversation_extractions`, `person_axis_scores`, `claim_embeddings`, `message_embeddings` |
| Axes et idéologies | `axes` (21, dont 12 actifs), `axis_anchors`, `ideologies`, `ideology_axis_ranges`, `role_rules`, vues `classified_roles`, `claimed_ideologies`, `ideology_concordance`, `claimed_ideology_summary`, `claimed_ideology_conflicts` |
| Vie privée | `privacy_subjects` (registre : identifiant seulement), `privacy_log` (nombres, jamais un contenu) |
| Exploitation | `ingest_runs` (registre des imports), `service_status` (battement du bot), `runtime_settings` (limites de performance, lecture automatique), `scoring_settings`, `jobs`, `schema_migrations`, `profiles`, `cards` |

Choix de conception : identifiants Discord en `bigint` ; texte de recherche français avec `unaccent` ; `forget_user()` en SQL ; les positions des personnes **jamais écrites dans `messages`** ; ce qui se déduit d'une conversation dépend d'elle (`ON DELETE CASCADE`), si bien qu'effacer une personne efface ce qui en a été tiré.

### 3.4 Analyse par IA (`app/dindon/analysis/`, Ollama local)

Cascade, chaque étape **reprenable** (ce qui est fait n'est pas refait), une analyse à la fois (`job.py`) :

| Étape | Module | Ce qui se passe | Niveau |
| --- | --- | --- | --- |
| 1-2. **Conversations** et tri | `conversations.py` (SQL) | Messages d'un salon coupés après 20 min de silence ou 40 messages ; « retenue » si elle dit quelque chose | Testé, mesuré |
| 3. **Vecteurs** | `embeddings.py` | `bge-m3` (1024 nombres), **sans les noms** | Mesuré (16/s) |
| 3. **Thèmes** | `themes.py` | k-moyennes sphériques, nombre choisi par la silhouette, noms par `qwen3:14b` ; vous **validez, renommez, fusionnez, rejetez** | Mesuré : pureté 86-87 % sur le serveur de test (optimiste) |
| 4-5. **Positions avec preuves** | `extraction.py` | Le modèle lit une conversation (P1, P2… sans noms) et écrit des thèses ; **le code refuse** toute position dont la citation n'est pas copiée mot pour mot d'un message **de cette personne dans cette conversation** | **Mesuré** : sens pour/contre juste dans 86 % des cas, mais 67 % de prises de position à tort pour les gens sans avis ; sur ~270 positions inventées |
| 6. **Axes** | `axes.py` + SQL | Le modèle relie **une proposition** (jamais une personne) aux axes ; le SQL calcule la position de chaque personne (moyenne pondérée, doute, incertitude jamais sous 0,35) | Testé ; poids **proposés, non validés** |
| 7. **Cohérence des rôles** | vues SQL | Ce qu'attend chaque rôle sur chaque axe (`ideology_axis_ranges`) comparé à la position : incompatible / confirmé / compatible / insuffisant | **Pas encore mesuré** (trop peu lu sur le serveur de test : 1 mauvais rôle sur 9 repéré) |

**Principe** : le modèle propose, le programme vérifie, **la personne valide**. Aucun thème, aucune proposition, aucun poids n'est validé par le code.

**Modèles** : `bge-m3` (vecteurs), `qwen3:14b` (noms, positions, axes) ; `gemma4:12b` comparé. Ollama tourne **sur la machine hôte** (le GPU d'un Mac n'est pas accessible depuis Docker) ; **rien ne sort de la machine**.

### 3.5 Lecture automatique et limites de performance

- **Lecture automatique** (`automation.py`, `analysis/auto.py`) : boucle de l'application, **éteinte par défaut**, cases *conversations et vecteurs / thèmes / positions*, fréquence, lot, heures. Les **positions** exigent la confirmation que les personnes sont informées ; les messages d'une personne qui a demandé l'arrêt ne sont jamais lus.
- **Performance** (`performance.py`) : part du temps où l'IA travaille (pause proportionnelle après chaque appel), fils de calcul, durée de garde des modèles, taille des lots, **regroupement des écritures du bot**. Trois profils. Relus par le bot (30 s) et par l'analyse (5 s) sans redémarrage.

### 3.6 Application et interface (`api/`, `web/`)

- **API FastAPI** (~35 routes) : carte (`/graph`, `/people`, `/person`), analyse, thèmes, positions, cohérence, vie privée, import, invitation, système, performance, lecture automatique ; **SSE** (`/events`) alimenté par `LISTEN/NOTIFY` de Postgres.
- **Sécurité** : un mot de passe unique → cookie `HttpOnly`/`SameSite=Strict` ; **CSP stricte** (aucune ressource extérieure, pas de script évalué) ; `X-Frame-Options: DENY` ; rien d'écouté hors `127.0.0.1`. Les identifiants Discord circulent en **texte** (ils dépassent ce qu'un nombre JavaScript sait compter).
- **Interface Svelte 5 + Sigma** : *Carte* (points colorés par rôle Discord, survol, fiche de la personne avec **barres par axe** rouge → vert, positions par sujet, avec qui elle en a parlé), *Thèmes*, *Positions*, *Cohérence*, *Système* (santé, bot, collecte, IA, performance, lecture automatique), *Vie privée*, fenêtres *Importer* et *Inviter le bot*. **Recherche et filtres sur chaque page** (accents ignorés, touche `/`). Même style que le projet Poulet.

### 3.7 Vie privée et cadre juridique (`privacy.py`, `bot/privacy_commands.py`, `api/privacy.py`)

- **Registre** `privacy_subjects` (identifiant seulement) lu **avant toute écriture** : le bot jette les messages sans les garder, l'ingestion retire la personne de tout import (export, rattrapage, bot).
- **Effacement complet** sous le même verrou que l'ingestion : personne, messages, réactions, mentions, noms, liens, **conversations dont elles dérivent** (donc vecteurs et positions), ce que d'autres ont cité d'elle, et ses traces dans `inbox/` et `archive/`.
- **Commandes Discord** `/dindon info | mes-donnees | stop | effacer | reprendre` : réponses visibles de la seule personne, **réponse accusée avant le travail** (Discord ne laisse que 3 s), bouton de confirmation pour `effacer`, une demande par personne toutes les 15 s.
- Accès (copie JSON), **conservation limitée** (`DINDON_RETENTION_DAYS`, par lots), journal en nombres, page « Vie privée », CLI `dindon privacy`.
- **Hors périmètre** (dit dans `CONFORMITE.md`) : le consentement explicite pour les opinions politiques (art. 9), les mineurs, l'AIPD, les sauvegardes (14 jours).

## 4. Flux principaux

1. **Temps réel** : Discord → Gateway → `adapter` → lot par salon (0,3 s par défaut) → `ingest_document(only_new)` → base → `NOTIFY` → SSE → la carte s'allume.
2. **Historique** : `dindon backfill` (ou fenêtre *Importer* : salons, personnes, période) → exportateur → fichiers → ingestion. Un import filtré est **partiel** : il ne compte jamais comme un premier import, un `backfill` complet rapporte encore tout.
3. **Rattrapage nocturne** (`DINDON_COLLECTOR=catchup`, recommandé avec le bot) : les derniers jours ré-exportés, ce qui répare les trous du bot et applique modifications et suppressions.
4. **Analyse** : bouton, ligne de commande (`dindon analyze`) ou **lecture automatique** → job unique → étapes de §3.4 → base → pages.
5. **Retrait d'une personne** : `/dindon stop|effacer` ou page *Vie privée* → registre (+ effacement) → plus jamais ré-enregistrée.

## 5. Exploitation

| | |
| --- | --- |
| Compose | `db` (PostgreSQL 17 + pgvector, 127.0.0.1:5432), `app` (127.0.0.1:8000), `bot` (profil `bot`, même image), `ollama` (option Linux/GPU) |
| Hôte | Ollama lancé par `launchd` avec garde-fou ; sauvegarde nocturne de la base (`tools/host/backup.sh`, restauration testée dans une base vide) ; `caffeinate` à prévoir |
| Santé | page **Système** : battement du bot (30 s), reconnexions avec perte, collecte, base, Ollama et modèles, serveurs suivis, « points à voir » |
| Suivi des serveurs | `DINDON_GUILD_IDS` vide ou `all` : **tout serveur où le bot est** ; liste : seulement ceux-là |
| Invitation | lien généré par l'interface (permissions : voir les salons, lire l'historique ; portée `applications.commands` pour `/dindon`) |
| Tests | `make test` : base jetable dans Docker (jamais de réseau hors de la machine), faux Discord, faux Gateway, faux Ollama, navigateur réel (Playwright) |

## 6. Décisions qui structurent le projet

| Décision | Pourquoi |
| --- | --- |
| **Un seul contrat (JSON v2) et une seule ingestion** | Remplacer une source (le futur exportateur maison) sans toucher au reste ; un message identique, d'où qu'il vienne |
| **PostgreSQL seulement** (file d'attente, notifications, vecteurs, graphe) | Une seule pièce à exploiter ; mesuré suffisant (liens reconstruits en 183 ms, `NOTIFY` 1,2 ms) |
| **Le modèle propose, le code vérifie, la personne valide** | Une citation fausse ne passe jamais ; aucune étiquette sur une personne sans relecture |
| **Les personnes sont P1, P2… pour le modèle** | La position vient de ce qu'on écrit, pas de qui on est |
| **Rien ne sort de la machine** | IA locale ; aucune API payante ; données personnelles et opinions |
| **Les liens sont tenus à jour au fil de l'eau** | La carte est vivante sans tout recalculer ; vérifié égal à une reconstruction |
| **Effacement en cascade depuis les messages** | Effacer une personne efface ce qui en dérive |
| **Éteint par défaut** (lecture automatique des positions, filtres de saisie) | La prudence est le réglage de base |

## 7. Ce qui est prouvé, et ce qui ne l'est pas

| Niveau | Quoi |
| --- | --- |
| **Vu en vrai** | Le bot connecté à deux vrais serveurs, des heures de suite, sans perte ni erreur ; l'authentification et le listage réels des salons par l'ancien exportateur ; l'enregistrement de la commande `/dindon` auprès de Discord |
| **Testé, Discord simulé** | L'adaptateur, le moteur, l'ingestion, les commandes `/dindon` (réponse accusée, bouton, effacement), l'import filtré, l'invitation, le rattrapage |
| **Mesuré sur données inventées** | Débits (import, bot 300 msg/s, effacement 0,2-1,5 s, purge de 300 000 messages en 6 s), vecteurs, noms de thèmes, qualité des thèmes (86 %), des positions (86 % de bon sens, 67 % de faux positifs sans avis) |
| **Jamais vu** | Les commandes `/dindon` entre les mains d'un vrai membre ; un vrai gros serveur ; l'IA sur de vrais messages ; la cohérence des rôles (non mesurée) ; la lecture réelle de messages par l'exportateur |

## 8. Risques et dettes (franchement)

1. **L'hôte.** Un Mac portable : veille, batterie, saturation par d'autres conteneurs. PostgreSQL s'y est arrêté **deux fois** en une journée (récupération automatique, données intactes), le bot s'est reconnecté. Pour beaucoup de monde : une machine toujours branchée, idéalement Linux.
2. **L'exportateur maison n'a été essayé que sur 474 messages réels** (identiques à l'ancien, petites lacunes connues), pas sur un gros serveur ni sous les vraies limites de débit. Il remplace l'exportateur C# d'origine (supprimé ; sa source est dans la branche locale `archive/avant-nettoyage` de `strategio`).
3. **Le bot applique les nouveaux messages, les modifications et les suppressions en direct** (pas les réactions : le rattrapage nocturne). Un trou après une reconnexion ou un redémarrage du bot est comblé par un tour du relevé tout de suite (mode `catchup`).
4. **La lecture des positions est lourde** (~15 s par conversation) et son **éparpillement** est fort : ~250 propositions précises pour 10 sujets (rangées sous leur thème).
5. **Les poids proposition → axe doivent être validés par une personne** (sur la base de test, c'est fait ; sur un vrai serveur, non : voir [VALIDATION-AXES.md](VALIDATION-AXES.md)) et le **tableau « ce qu'attend chaque rôle »** est celui du projet, **à relire par vous** ; les 21 axes (dont Europe, Écologie, Genre…) sont actifs depuis le 4 octobre.
6. **Pas de validation des propositions** par une personne dans l'interface (état « proposée » seulement), ni de relations entre réponses (accord/désaccord entre deux personnes).
7. **Accès** : un mot de passe unique, un flux SSE pour tous ; pas de comptes ni de droits par personne.
8. **Vie privée** : pas de consentement préalable, pas de vérification d'âge, pas d'AIPD ; les **sauvegardes** gardent une personne effacée jusqu'à leur expiration (restauration : relancer les effacements du registre).
9. **Dépôt** : tout le travail récent n'est **pas commité** dans le dépôt de Dindon (plus de 116 fichiers). Un test navigateur (`test_ui_isolated`) est instable quand toute la suite tourne.

## 9. Où lire quoi

| Pour… | Document |
| --- | --- |
| Entrée, vue d'ensemble | `README.md`, `docs/RESUME.md` |
| Décisions et leurs raisons | `docs/DECISIONS.md`, `docs/ARCHITECTURE.md` |
| Collecte, bot, exportateur | `docs/COLLECTE.md`, `docs/EXPORTATEUR.md` |
| IA : étapes, qualité | `docs/ANALYSE.md`, `docs/AXES.md`, `docs/SERVEUR-DE-TEST.md`, `docs/MESURES.md` |
| Lecture automatique, performance | `docs/LECTURE-AUTOMATIQUE.md`, `docs/PERFORMANCE.md` |
| Vie privée | `docs/CONFORMITE.md`, `docs/INFORMATION-MEMBRES.md`, `docs/DINDON_JURIDIQUE_ET_AMELIORATIONS.md` |
| Le format d'échange | `contracts/JSON-format.md` (+ schéma et modèle) |
| Tester sans Discord | `make demo`, `make politique` (serveur politique inventé) |
