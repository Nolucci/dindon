> *Copie du prompt d'origine, gardée telle quelle. Ses chemins (`database/`, `.docs/`) correspondent ici à `db/` et `tools/`, `contracts/` et `docs/` : voir [DECISIONS.md](DECISIONS.md).*

# Prompt : créer le projet « Strategio », une carte vivante d'un serveur Discord

> **Mode d'emploi.** À donner à l'IA de développement (par exemple Claude Code) dans un **dossier de projet vide**, avec le **kit de départ** (voir §3). Il contient toutes les décisions déjà prises : elle n'a pas à les redécouvrir, seulement à construire. Le projet s'appelle provisoirement « Strategio ».

---

## 1. Ta mission

Tu construis, **de zéro et en entier**, un projet autonome qui :

1. **récupère** les messages d'un serveur Discord, à la main (exports ponctuels) et **automatiquement au fil de l'eau** ;
2. les **stocke** dans une base locale ;
3. les **analyse** avec une IA locale : de quoi parle chaque personne, ce qu'elle défend, ce qu'elle fait ;
4. **classe les personnes** sur des axes précis (idées) et selon leurs actions, **avec les preuves** (messages cités) ;
5. **vérifie** ce classement avec les rôles que les personnes se sont donnés elles-mêmes ;
6. **relie** les personnes selon leurs interactions ;
7. **affiche** le tout sur une **carte dynamique en direct**, simple, réaliste et belle, et génère des **cartes de divertissement**.

Tout est **local** (aucun service extérieur, hors Discord lui-même), **compact** (le moins de pièces possible) et **puissant**.

## 2. Contexte et utilisateur

- Utilisateur **francophone**, **seul** pour l'instant. Interface et documentation **en français**. Code, identifiants et commentaires **en anglais**.
- Machine de développement : **Mac Apple M4 Pro, 24 Go**. Serveur d'installation : **inconnu** pour l'instant (suppose un Linux avec Docker, et ne dépends de rien d'autre).
- Il est **membre** du serveur Discord (pas administrateur). Plus tard, il créera **un bot sur son serveur**. Prévois dès maintenant les deux modes (voir §7.1).
- Les données sont les messages de **personnes identifiables** dont les **opinions politiques** : données sensibles. Le serveur compte des **mineurs** (rôles d'âge du type « Entre 16 et 20 ans »). Les garde-fous du §7.9 sont **des exigences**, pas des options.
- On en est à **la construction** : l'architecture est décidée et en partie testée. Le dépôt d'origine est un fork de DiscordChatExporter (programme C#) qui sert d'**outil externe**.

## 3. Kit de départ (fichiers fournis, point de départ à reprendre tel quel)

Lis **tout** avant d'écrire du code. Le kit reprend les chemins du dépôt d'origine (les liens entre fichiers restent valables).

| Fichier | Contenu |
| --- | --- |
| `ARCHITECTURE.md` | l'architecture complète, avec ses mesures. **Document de référence.** |
| `.docs/JSON-format.md`, `.docs/JSON-format.schema.json`, `.docs/JSON-format.template.json` | **le contrat de données** : le format JSON version 2 que produit l'exportateur (description, JSON Schema, modèle sans données) |
| `database/schema.sql` | la base : serveurs, salons, personnes, rôles, messages, réactions… (testé) |
| `database/schema-analysis.sql` | thèmes, axes, idéologies, rôles, propositions, affirmations et preuves, scores, vérification, graphe, file de tâches (testé) |
| `database/seed-axes.sql` | données de départ : **21 axes** (les 12 du modèle 12 Axes + 9 inactifs), 28 idéologies avec leurs plages, 37 règles de reconnaissance des rôles |
| `database/schema-vector.sql` | recherche par le sens (pgvector) |
| `database/docker-compose.yml`, `.env.example` | PostgreSQL 17 + pgvector, local (testé) |
| `database/load_export.py` | **chargeur de référence** : montre comment chaque propriété du JSON v2 devient des lignes (idempotent) |
| `database/generate_axes_review.py`, `database/AXES.md` | page de relecture des axes et idéologies, générée depuis la base |
| `database/README.md` | choix de la base, mesures |

**L'exportateur (programme externe).** Sources dans le dépôt d'origine ; il se compile en binaire autonome : `dotnet publish DiscordChatExporter.Cli -c Release -r linux-x64 --self-contained -o <dossier>` (vérifié ; remplace `linux-x64` par `osx-arm64` sur Mac). Ligne de commande utile : `export -c <salon...>`, `exportguild -g <serveur>`, `-t <jeton>` (ou variable `DISCORD_TOKEN`), `-f Json`, `-o <dossier>/`, `--after <date ou identifiant de message>`, `--before`, `--parallel <n>`, `--include-threads none|active|all`, `--filter`, `--partition`, `--utc`. Les forums sont exportés automatiquement post par post. Une application graphique permet aussi des exports manuels.

**Règle d'or : l'exportateur et le JSON v2 sont le seul contrat avec Discord.** Ne réimplémente ni l'analyse des messages Discord ni leur mise en forme.

## 4. La vision, avec les mots de l'utilisateur

- « Représenter une **carte visuelle des interactions** de mon serveur, avec les **personnes, leurs idées et les liens des personnes entre elles**. »
- « Une **banque d'information pour justifier les positions** de chaque personne. »
- « **Des axes clairs et précis en base de données, et leurs idéologies**, pour classer les personnes selon ces axes, et **ensuite une vérification selon les rôles que la personne s'est auto-attribués** pour vérifier la concordance avec ses propos, **à afficher sur la carte en cliquant sur une personne**. »
- « **D'abord découverte automatique** des thèmes, **indépendamment des personnes**, ensuite précision et ajout d'autres. »
- « Exporter les données d'un serveur **manuellement ET automatiquement au fur et à mesure** pour avoir une **carte temps réel**, analyser les données et les **classer précisément**, classer les personnes **selon leurs idéologies et leurs actions**, les relier aux autres selon leurs interactions, afficher le résultat sous une forme **dynamique, simple, réaliste, jolie**. »
- « Le système **le plus compact et puissant possible**. » « **Tout doit être géré en local.** » « L'application est **pour moi seul** au départ. » « L'IA locale : oui. »
- Des **cartes de divertissement** (une carte par personne) générées à partir de leur fiche.

## 5. Décisions déjà prises (ne les remets pas en cause sans me demander)

| Sujet | Décision |
| --- | --- |
| Contrat de données | JSON v2 (voir `.docs/JSON-format.md`), produit par l'exportateur |
| Base | **PostgreSQL 17 + pgvector**, en Docker, seule base du projet. File de tâches, notifications, recherche en français, vecteurs et graphe y vivent aussi |
| Ce que je n'ajoute pas | Redis, Kafka, Neo4j, Elasticsearch, Kubernetes, microservices |
| Application | **Python 3.12+**, **FastAPI**, un seul processus qui fait ingestion, ouvriers d'analyse, API et flux en direct (SSE) |
| Interface | **Svelte + Vite**, graphe avec **Sigma.js (WebGL) + graphology**, placement des nœuds (ForceAtlas2) dans un thread à part. Servie par l'application |
| IA locale | **Ollama** (modèle de langue + modèle d'embeddings multilingue, 1024 dimensions pour correspondre à `vector(1024)`) |
| Collecte automatique | surveillance : relever les salons qui ont bougé (`last_message_id`) puis lancer l'exportateur avec `--after`. Bot en direct plus tard |
| Idées | affirmations → propositions → positions → score par axe, **toujours avec preuves** |
| Axes | les 12 axes de [12 Axes](https://12axes.vercel.app) actifs ; 9 axes ajoutés **inactifs** tant que l'utilisateur ne les a pas relus ([AXES.md](database/AXES.md)). −1 = pôle de gauche du modèle, +1 = pôle de droite |
| Vérification | verdicts par axe (confirmé, compatible, incompatible, insuffisant) puis par rôle (concordant, discordant, non vérifiable), plus les rôles qui se contredisent. Tout est déjà en SQL |
| Rôles | reconnus par leur nom ; seuls les rôles d'idéologie servent. **Âge et genre : reconnus pour être écartés** |
| Thèmes | découverte automatique d'abord, puis validation par l'utilisateur, puis ajouts manuels |

## 6. Architecture cible

```
 Discord ──(A) export manuel (appli ou ligne de commande) ──► dossier inbox/ ─┐
         ──(B) surveillance : relève les nouveautés ──► exportateur ──────────┼─► ingestion
         ──(C) bot en direct (plus tard) ─────────────────────────────────────┘      │
                                                                                      ▼
   ┌───────────────────────────  PostgreSQL 17 + pgvector  ─────────────────────────────┐
   │ messages · personnes · rôles · axes · idéologies · affirmations · scores · arêtes   │
   │ vecteurs · file de tâches (SKIP LOCKED) · NOTIFY                                    │
   └──────┬──────────────────────────────┬────────────────────────────────┬─────────────┘
          │ jobs                          │ résultats                      │ NOTIFY
          ▼                               ▼                                ▼
   ouvriers d'analyse  ◄──────►  Ollama (LLM + embeddings)        API FastAPI + SSE ──► carte web
```

Arborescence proposée (tu peux l'ajuster, en le justifiant dans `docs/DECISIONS.md`) :

```
strategio/
  docker-compose.yml  .env.example  Makefile  README.md
  contracts/        (le contrat JSON v2 : documents, schéma, modèle)
  db/               (schema.sql, schema-analysis.sql, seed-axes.sql, schema-vector.sql, migrations/)
  app/strategio/    (config, db, ingest, collector, analysis/, graph/, api/, jobs/)
  web/              (Svelte + Vite)
  tools/            (generate_axes_review.py, bench_llm.py, make_demo_server.py)
  tests/  docs/  exporter/ (comment obtenir le binaire)
```

## 7. Spécifications

### 7.1 Collecte

- **A. Manuel.** Un dossier `inbox/` surveillé : tout JSON v2 qui y arrive est ingéré (les exports faits avec l'application graphique, par exemple).
- **B. Surveillance (à faire en premier).** Toutes les 30 à 60 s : une requête `GET /guilds/{id}/channels` pour lire `last_message_id` de chaque salon ; comparaison avec le plus récent message connu en base ; pour chaque salon qui a bougé, lancer l'exportateur avec `--after <dernier id connu>` vers `inbox/`. Fils et posts de forum : `--include-threads active`. **Rattrapage nocturne** : ré-exporter les 7 derniers jours pour capter modifications et suppressions. Respecter les limites de débit de Discord (reculer en cas de limitation).
- **Premier import d'un serveur entier** : `exportguild` avec `--parallel`, avec reprise possible. Les **réactions** coûtent une requête chacune (la liste de qui a réagi) : c'est le poste le plus lent ; signale-le, et propose (sans l'imposer) une option d'exportateur pour les différer.
- **C. Bot en direct (plus tard).** Une abstraction `Source` doit permettre d'ajouter un bot (Gateway, intention « contenu des messages ») sans toucher à l'ingestion : mêmes écritures en base, mêmes notifications.
- **Jeton** : variable d'environnement, jamais écrit dans un journal, jamais dans le dépôt. Accepte un jeton de bot ou de compte. **Avertis dans le README et dans l'interface** que l'automatisation continue d'un compte personnel est interdite par les conditions d'utilisation de Discord et peut le faire fermer ; un bot est recommandé.

### 7.2 Ingestion

- **Idempotente** : un fichier déjà importé (empreinte `sha256`) est ignoré ; deux exports qui se chevauchent ne créent aucun doublon ; un message modifié est mis à jour ; ses enfants (pièces jointes, mentions, réactions) sont remplacés d'un bloc. `database/load_export.py` en est la **référence de comportement**, mais il va ligne par ligne : fais une version **par lots (COPY ou `execute_values`)**.
- **Aucune perte** : un test automatique compare chaque message de la base avec le fichier d'origine (le chargeur de référence a déjà été vérifié ainsi).
- À chaque ingestion : mise à jour **incrémentale** de `edges`, création des tâches d'analyse, `NOTIFY`.
- L'historique des noms (`identity_history`) garde ancien et nouveau pseudo : l'identité d'une personne est son **identifiant**, jamais son nom.

### 7.3 Base

- Reprends `db/*.sql` tels quels, **sans changer le sens des tables**. Pour les évolutions, ajoute un petit outil de migrations (fichiers numérotés ; pas de framework lourd). Tous les fichiers SQL sont rejouables sans effet.
- Les identifiants Discord sont des `bigint`. Les dates sont en UTC (`timestamptz`).
- Index des embeddings : à créer **après** le chargement en masse (voir §8).

### 7.4 Analyse par l'IA locale : une cascade

L'IA ne lit pas tout. Étapes (jobs, dans l'ordre) :

1. **Conversations** (SQL) : regrouper les messages par salon en discussions : chaînes de réponses, coupure après **20 min** de silence, **40 messages** au plus. Le texte du message auquel on répond est déjà dans le JSON v2 (`reference.content`) : utilise-le comme contexte.
2. **Tri** (SQL) : écarter bots, messages vides, « mdr », liens seuls ; calculer une **importance** (longueur, réponses reçues, réactions). Traiter **par ordre d'importance** : les premiers résultats utiles arrivent avant la fin.
3. **Vecteurs** : embeddings des discussions retenues (Ollama).
4. **Thèmes, sans tenir compte des personnes** : regroupement des discussions par proximité de sens (HDBSCAN ou équivalent), nommage de chaque groupe par le modèle → `topics` au statut `proposed`, trace dans `topic_runs`. Relancer plus tard **ne touche jamais** à ce qui est validé.
5. **Extraction** : par discussion, le modèle liste les affirmations de **chaque personne** dans un **format imposé** (JSON contraint par schéma) : type (`opinion`, `fait`, `proposition`…), texte clair en français, **identifiants des messages qui la prouvent** avec citation. → `claims` et `claim_evidence`. Sans preuve, pas d'affirmation.
6. **Normalisation** : rattacher chaque affirmation à une **proposition** existante (vecteur le plus proche, puis vérification par le modèle) ou en créer une (« Il faut augmenter le SMIC »). **Une seule fois par proposition**, le modèle propose son poids sur chaque axe actif (`proposition_axis`, `is_validated = false`) en s'appuyant sur la question, la définition, ce que l'axe ne couvre pas et les repères −1/0/+1 de l'axe. Position de la personne : `stance` −1, 0 ou +1 envers la proposition, avec une confiance.
7. **Relations** : pour chaque réponse, nature du lien envers le message d'origine (accord, désaccord, soutien, moquerie, information), qui alimente `edges`.
8. **Scores** : `SELECT refresh_person_axis_scores(<serveur>)`, puis les vues de vérification (§7.5).

Règles pour le modèle : température basse, sortie contrainte par schéma, consignes **versionnées** (`prompt_version`) et modèle enregistré dans chaque ligne produite, consignes en français, **aucune inférence à partir de signaux indirects** (style, horaires, fréquentations), **jamais d'âge ni de genre**. Tout résumé écrit pour une fiche ne contient que des phrases **adossées à des affirmations citées**.

**Avant d'écrire le pipeline, mesure** : `tools/bench_llm.py` compare 2 ou 3 modèles (familles Qwen, Mistral, Gemma, Llama récentes, 7 à 14 milliards de paramètres, quantifiés) sur la vitesse (tokens par seconde) **et sur la qualité** (petite série annotée à la main). **Aucune IA locale n'est installée** sur la machine de l'utilisateur : les durées du §8 sont des estimations, à remplacer par tes mesures.

### 7.5 Axes, idéologies, rôles, scores, vérification (déjà en SQL, à brancher)

- `axes` / `axis_anchors` : question, définition, ce que l'axe ne couvre pas, repères. Seuls les axes **actifs** sont calculés. L'écran de réglages permet de les activer ou désactiver et de relire les définitions.
- `ideologies` / `ideology_axis_ranges` : ce qu'implique chaque idéologie (plages **larges**), marquées non validées jusqu'à relecture de l'utilisateur. **Tu ne modifies jamais ces données de fond** : c'est lui qui les relit (`database/AXES.md`).
- `role_rules`, vues `classified_roles`, `claimed_ideologies` : reconnaissance des rôles par leur nom. Seuls les rôles de type `ideologie` servent. **Les rôles d'âge et de genre ne sont jamais analysés ni affichés.**
- Score : `refresh_person_axis_scores()` (moyenne pondérée par la confiance et le poids de la proposition, tirée vers 0 par une part de doute, incertitude plancher). Réglages dans `scoring_settings`.
- Vérification : vues `ideology_concordance`, `claimed_ideology_summary`, `claimed_ideology_conflicts`. **Constat réel** : les gens se donnent beaucoup de rôles à la légère (en moyenne 14 sur 27 dans l'échantillon) et certains se contredisent (Protectionniste + Mondialiste, Gaulliste + Multiculturaliste) : c'est pourquoi la vérification est faite rôle par rôle.
- « Discordant » est **une alerte à regarder, pas une accusation** : à dire ainsi dans l'interface.

### 7.6 Graphe

- `edges` : une ligne par paire de personnes et par type de lien (réponse, mention, réaction ; plus tard accord ou désaccord), avec un **poids à décroissance temporelle** (demi-vie de 90 jours par défaut, réglable), mise à jour **incrémentale** à chaque message.
- **Communautés** : méthode de Leiden (igraph), recalculées chaque nuit et à la demande, avec des **identifiants stables** d'un calcul à l'autre (rattacher chaque nouveau groupe à l'ancien qui lui ressemble le plus).
- **Actions** (ce que font les personnes), en SQL et sans IA : part de messages qui lancent une discussion ou qui répondent, longueur et régularité, diversité des thèmes, réponses et réactions reçues, modération (sanctions de bots, messages épinglés, sondages), centralité.

### 7.7 API et temps réel

- FastAPI, **lié à 127.0.0.1**, mot de passe même pour un seul utilisateur. Points d'accès : graphe (nœuds, arêtes, filtres par thème, période, communauté), fiche d'une personne, preuves d'une position (message dans son contexte), thèmes, axes et idéologies, file « à revoir », réglages, état des tâches.
- **Flux SSE** `/events` alimenté par `LISTEN/NOTIFY` : nouveau message, arête modifiée, score recalculé, nouvelle affirmation.
- Corrections de l'utilisateur (affirmation confirmée ou rejetée, thème validé ou fusionné, poids d'axe validé) : écrites en base et **prises en compte au prochain calcul**.

### 7.8 Interface

Français, thème sombre, simple, fluide, belle. Vues :

- **La carte** : une personne = un point (taille : influence ; couleur : communauté ou position sur un axe au choix) ; un lien = une ligne dont l'épaisseur est le poids et la couleur la nature (vert : accord, rouge : conflit, gris : neutre) ; à chaque nouvel échange, le lien concerné s'illumine ; **frise pour rejouer l'évolution dans le temps** ; filtres par thème et par période. Objectif : fluide à plusieurs milliers de personnes (au-delà, afficher les plus actives et agréger le reste).
- **La fiche d'une personne** (au clic) : **scores sur chaque axe actif avec incertitude** ; **vérification avec ses rôles** (rôle pris, verdict, par axe : score ± incertitude face à la plage attendue, avec les messages qui le prouvent, et les rôles qui se contredisent) ; positions par thème, **chaque position avec ses citations cliquables** (message dans son contexte) ; évolution dans le temps ; statistiques d'actions ; liens principaux ; résumé écrit par l'IA, adossé aux preuves.
- **La vue d'un thème** : qui pense quoi sur une proposition, avec preuves.
- **La boussole** : personnes placées sur deux axes au choix.
- **À revoir** : affirmations à faible confiance, thèmes proposés, poids d'axe proposés ; confirmer ou corriger en un clic.
- **Réglages** : axes actifs, règles de reconnaissance des rôles, modèles, état des tâches, mode pseudonymisé.
- **Cartes de divertissement** : une image par personne, exportable, **sans attribut sensible par défaut**.

### 7.9 Vie privée et sécurité (exigences)

- **Local seulement** : aucun appel sortant vers un service extérieur (sauf Discord, via l'exportateur), aucune télémétrie, aucune police ou bibliothèque chargée depuis un CDN à l'exécution.
- Interface protégée par mot de passe, liée à `127.0.0.1`, jamais exposée sur Internet. Journaux **sans contenu de messages ni jetons**.
- **Âge et genre écartés** partout. **Aucune inférence indirecte.** Étiquettes toujours affichées avec **nombre de preuves et incertitude**, jamais comme un fait.
- **Mode pseudonymisé** (remplace les noms par des pseudonymes dans toute l'interface et dans les cartes exportées).
- **Effacement** : une commande et un bouton appellent `forget_user()` (supprime la personne et tout ce qui la concerne).
- Aucune donnée réelle dans le dépôt : `.gitignore` des exports et des `.env`. Les tests utilisent des **données synthétiques**.
- Rappelle dans le README que ce traitement vise des données sensibles : un usage strictement personnel est hors du champ du RGPD, **plus dès que les fiches sont montrées à d'autres** ; ne pas partager.

## 8. Faits mesurés (ne les refais pas ; reproduis seulement en cas de doute)

Mesures faites sur PostgreSQL 17 dans Docker, sur le Mac M4 Pro, avec 500 000 messages synthétiques (400 personnes très inégalement actives, 40 salons, vraies phrases françaises).

| Mesure | Résultat |
| --- | --- |
| Insertion de 500 000 messages en SQL, index et recherche plein texte compris | 11 s |
| Taille (tables + index) | 206 Mo, soit environ 430 octets par message |
| Tous les messages d'une personne moyenne (1 025) | 1 à 2 ms |
| Tous les messages de la personne la plus active (67 728) | 40 à 70 ms |
| Recherche plein texte en français sans accents (10 002 résultats) | 5 à 11 ms |
| Chiffres de chaque personne (`user_stats`, 408 personnes) | 26 ms |
| Paires de personnes qui se répondent le plus | 36 à 44 ms |
| File de tâches `FOR UPDATE SKIP LOCKED`, 4 ouvriers | 15 400 tâches par seconde |
| `LISTEN/NOTIFY` | 1,2 ms médian, 3,5 ms au pire |
| Graphe complet (500 000 messages, 43 780 arêtes, décroissance temporelle) | 183 ms |
| Mise à jour incrémentale du graphe pour 1 000 nouveaux messages | 5 ms |
| pgvector (1 024 dimensions, `float4`) | environ 5 Ko par vecteur plus environ 8 Ko d'index ; 5 plus proches voisins en 3 ms avec index HNSW |
| Construire l'index HNSW au fil des insertions | lent (30 000 insertions : environ 2 min) : **créer l'index après le chargement en masse** |
| Fichier JSON v2 | environ 350 octets par message ; un message moyen fait environ 58 caractères, soit 15 à 20 tokens |

**Estimations non mesurées** : premier import d'un serveur de 1 million de messages = environ 10 000 requêtes de 100 messages, de l'ordre d'une heure. Étape d'extraction par le modèle : environ 5 à 15 s par discussion de 20 messages avec un modèle de 8 milliards de paramètres sur une puce de cette classe, soit un à deux jours pour 1 million de messages si le tri en retient 30 %. **À mesurer.**

**Vérifications numériques à reprendre comme tests** (la fonction SQL de score doit les redonner) :
- trois positions « contre le pôle +1 » (poids 0,81 / 0,72 / 0,72, toutes x = −1) : score **−0,692**, incertitude **0,381**, poids cumulé 2,250 ;
- trois positions sur un axe (x = −1, −1, −1 ; poids 0,81 / 0,425 / 0,72) : score **−0,662**, incertitude **0,399**, poids 1,955.

## 9. Qualité : tests et critères d'acceptation

- `make test` lance tout. Tests SQL du score et de la vérification (cas : eurosceptique cohérent → concordant ; « européiste » qui défend le contraire → discordant ; rôle sans preuve → non vérifiable ; deux rôles contradictoires → repérés ; preuve rejetée → score recalculé ou retiré).
- Test d'**aller-retour** de l'ingestion (aucune perte), d'**idempotence**, de **reprise** après interruption.
- **Jeu de démonstration** synthétique (`tools/make_demo_server.py`) : faux serveur, fausses personnes, rôles inspirés des vrais noms de rôles d'idéologie, messages en français sur plusieurs thèmes et axes. Il sert à développer l'interface et à tester sans Discord et sans données réelles. Prévois aussi un générateur de **500 000 messages** pour reproduire les mesures du §8.
- Le mode surveillance se teste avec un **faux serveur Discord** et un **faux exportateur** (aucun jeton réel dans les tests).
- Chaque phase du §10 se termine par une démonstration que **tu exécutes toi-même** et dont tu rapportes le résultat réel, y compris les échecs.

## 10. Plan par phases

| Phase | Contenu | Critère de fin |
| --- | --- | --- |
| 0. Socle | dépôt, `docker-compose.yml` (db, ollama, app), schéma appliqué, migrations, `/health`, `make test` | `docker compose up` donne une base saine (37 tables, 9 vues, 21 axes dont 12 actifs) |
| 1. **Carte des échanges, sans IA** | boîte `inbox/`, ingestion par lots, mode surveillance, `edges` incrémentales, API, SSE, interface (carte, fiche simple), jeu de démonstration | un nouvel échange (faux serveur) fait **s'illuminer le lien dans la carte en moins de quelques secondes** ; import de 500 000 messages mesuré |
| 2. Découverte des thèmes | banc d'essai du modèle, embeddings, conversations, regroupement, nommage, écran de validation | thèmes proposés sur le jeu de démonstration, validables, relance sans toucher aux validés |
| 3. Affirmations et preuves | extraction contrainte, propositions, poids d'axe proposés, fiche avec citations cliquables | chaque affirmation affichée a ses messages-preuves ; mesure de qualité sur une petite série annotée |
| 4. Classement et vérification | scores, vérification avec les rôles dans la fiche, file « à revoir » et corrections | la fiche montre rôle, verdict, score ± incertitude, preuves ; les corrections changent le calcul |
| 5. Finitions | frise de rejeu, cartes de divertissement, mode pseudonymisé, effacement, communautés stables ; préparer le bot (mode C) | rendu final ; documentation complète |

## 11. Comment travailler

1. **Lis le kit en entier** avant d'écrire du code, puis résume-moi en dix lignes ce que tu as compris et ce qui te manque.
2. **Pose-moi tes questions** (§12) avant la phase 1.
3. **Ne devine pas, ne maquille pas.** Mesure ce qui peut l'être ; donne les chiffres réels, y compris les mauvais. Distingue toujours « mesuré » et « estimé ». Si un test échoue, dis-le avec la sortie.
4. **Compact** : n'ajoute pas de service, de bibliothèque ou de couche qui n'est pas nécessaire ; justifie chaque ajout dans `docs/DECISIONS.md`.
5. **Petits pas, vérifiés** : fais tourner ce que tu écris. Commits fréquents, messages en anglais.
6. **Ne touche pas aux données de fond** (axes, idéologies, plages) : propose, je relis.
7. Documentation en français (`README.md`, `docs/`) : installer, utiliser, sauvegarder et restaurer (`pg_dump`), mettre à jour, dépanner.
8. Aucune donnée réelle, aucun jeton, aucune capture de messages dans le dépôt.

## 12. Questions à me poser avant de commencer (propose une valeur par défaut)

- Quel **serveur** d'installation (système, mémoire, disque, carte graphique) ? *Défaut : Linux, Docker, pas de carte graphique.*
- Quel(s) **identifiant(s) de serveur Discord**, et quel type de jeton aujourd'hui (compte ou bot) ? *Défaut : compte, surveillance, avertissement affiché.*
- Quel **modèle de langue** préfères-tu que j'essaie en premier ? *Défaut : tu compares deux ou trois selon le banc d'essai.*
- **Mot de passe** : un seul, défini dans `.env` ? *Défaut : oui.*
- Veux-tu garder les **fichiers JSON** importés (archives) ou les supprimer après ingestion ? *Défaut : les garder dans `archive/`.*

## 13. À ne jamais faire

- Appeler un service d'IA ou d'analyse **hébergé** ; envoyer des messages hors de la machine.
- Modifier les définitions d'axes, les idéologies, leurs plages ou les règles de rôles **sans que je les aie relues**.
- Analyser, stocker en clair dans une fiche ou afficher l'**âge** ou le **genre** d'une personne.
- Présenter un classement comme un **fait** : toujours preuves, nombre de preuves, incertitude.
- Utiliser le jeton d'un compte pour autre chose que la collecte décrite ; le journaliser ; le commiter.
- Ajouter Redis, Kafka, Neo4j, Elasticsearch, Kubernetes ou des microservices.
- Réimplémenter l'analyse des messages Discord au lieu d'utiliser l'exportateur.
