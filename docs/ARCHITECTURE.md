# Architecture : une carte vivante du serveur

Ce document décrit le système complet, de Discord jusqu'à la carte affichée. Il s'appuie sur ce qui existe déjà dans le projet (l'exportateur, le format JSON version 2, la base PostgreSQL de [la base](base-de-donnees.md)) et sur des mesures faites pour l'occasion. Quand un chiffre est une estimation et non une mesure, c'est écrit.

## Décisions confirmées

- **Usage** : vous seul, pour l'instant.
- **Collecte** : la surveillance automatique d'abord (le jeton de votre compte suffit) ; un bot sur votre serveur ensuite, pour le direct.
- **Axes et idéologies** : les 12 axes du modèle [12 Axes](https://12axes.vercel.app), plus 9 axes ajoutés (inactifs jusqu'à votre relecture, voir [AXES.md](AXES.md)), définis dans la base avec leur définition précise ([seed-axes.sql](../db/seed-axes.sql)). Les personnes sont classées sur ces axes à partir de ce qu'elles écrivent, puis le résultat est **vérifié avec les rôles qu'elles se sont données elles-mêmes**, et cette vérification s'affiche sur la carte quand on clique sur une personne.
- **Thèmes** : découverte automatique d'abord, indépendamment des personnes ; précision et ajout d'autres ensuite.
- **Où on en est** : c'est la préparation de l'architecture. Sont faits et testés : l'exportateur, le format JSON v2, la base, et le modèle d'analyse (axes, idéologies, rôles, calcul des scores, vérification). Le reste est à construire, dans l'ordre du §11.

## 1. Ce que le système doit faire

1. **Collecter** les messages d'un serveur entier, à la main (export ponctuel) et automatiquement, au fil de l'eau.
2. **Analyser** ce que dit chaque personne : de quoi elle parle, ce qu'elle défend, ce qu'elle fait (répond, lance des débats, modère…).
3. **Classer** les personnes selon leurs idées et leurs actions, **avec les preuves** : chaque position est liée aux messages qui la justifient. C'est la « banque d'information ».
4. **Relier** les personnes selon leurs interactions : qui répond à qui, qui mentionne qui, qui est d'accord ou en conflit.
5. **Afficher** le résultat sous forme d'une carte dynamique, mise à jour en direct, simple et belle.
6. Tout reste **en local**, sur votre serveur, et l'IA aussi.

## 2. Vue d'ensemble

```
   DISCORD
      │
      ├── (A) export manuel (application ou ligne de commande) ──┐
      ├── (B) surveillance automatique (relève les nouveautés) ──┼─►  fichiers JSON v2
      └── (C) bot en direct (option, si vous administrez) ───────┘         │
                                                                           ▼
        ┌─────────────────────────────  UNE SEULE BASE : PostgreSQL  ─────────────────────────────┐
        │  messages · personnes · rôles · emojis   (déjà fait)                                      │
        │  conversations · affirmations · positions · idéologie   (analyse)                         │
        │  arêtes du graphe · communautés · vecteurs · file de tâches · notifications               │
        └──────┬──────────────────────────────────┬──────────────────────────────────┬─────────────┘
               │ tâches                           │ résultats                        │ NOTIFY (1 ms)
               ▼                                  ▼                                  ▼
       Ouvriers d'analyse  ◄────────►   IA locale (Ollama)                 API + flux en direct (SSE)
       (même application Python)        modèle de langue + vecteurs                    │
                                                                                       ▼
                                                                          CARTE WEB (navigateur)
```

**Cinq principes**

1. **Un seul contrat.** Le JSON v2 (et le schéma de la base) est la porte d'entrée unique. Export manuel, surveillance, bot : tous produisent la même chose, donc l'analyse ne sait pas d'où viennent les données.
2. **Une seule base.** PostgreSQL sert de stockage, de file de tâches, de bus d'événements, de moteur de recherche, de base vectorielle et de graphe. Rien d'autre à installer (voir §4).
3. **Pas de classement sans preuve.** Une position, une étiquette idéologique ou une phrase d'une carte n'existe que si elle cite des messages.
4. **Deux vitesses.** Les liens entre personnes (réponses, mentions, réactions) sont mis à jour tout de suite, sans IA. Les idées passent par l'IA et arrivent en quelques minutes.
5. **Tout en local.** Aucun appel à un service extérieur, hors Discord lui-même.

## 3. Collecte : manuelle et automatique

L'exportateur sait déjà : `--after` (reprendre après un message ou une date), `--parallel`, `--include-threads`, `exportguild` (un serveur entier), et il connaît le dernier message de chaque salon (`last_message_id`, déjà lu dans le code), ce qui permet de savoir sans rien télécharger quels salons ont bougé.

| Mode | Comment | Délai | Ce qu'il faut | À écrire |
| --- | --- | --- | --- | --- |
| **A. Manuel** | L'application ou la ligne de commande produit un JSON v2, déposé dans un dossier `inbox/` que le système surveille | à la demande | rien de plus | presque rien (le dossier surveillé) |
| **B. Surveillance** | Toutes les 30 à 60 s : une requête (liste des salons), comparaison des derniers messages avec la base, export `--after` des seuls salons qui ont bougé | 30 à 60 s | un jeton de bot **ou** de compte | une commande `watch` dans l'exportateur (réutilise le code existant) |
| **C. Bot en direct** | Un bot reçoit chaque message au moment où il est écrit (Gateway), ainsi que les modifications et suppressions | moins d'une seconde | administrer le serveur, ajouter un bot, activer l'accès au contenu des messages | un petit module dans l'application Python |

**Choix confirmé : B maintenant, puis C quand le bot sera créé.** Les deux alimentent la même ingestion, on passe donc de l'un à l'autre sans rien refaire. En attendant le bot, la surveillance utilise le jeton de votre compte : voir le point « Conditions d'utilisation » ci-dessous.

Points d'attention :
- **Conditions d'utilisation de Discord.** Automatiser un compte personnel (jeton utilisateur) est interdit par Discord et peut faire fermer le compte. Pour une surveillance continue, utilisez un bot. L'exportateur le sait déjà (c'est écrit dans son README) ; ici, le risque grandit parce que l'automatisation est permanente.
- **Premier import d'un serveur entier.** 1 million de messages = environ 10 000 requêtes de 100 messages. À un rythme poli de quelques requêtes par seconde, cela prend de l'ordre d'une heure (estimation). Les réactions coûtent une requête chacune (celle qui liste qui a réagi) : sur un gros serveur, c'est le poste le plus lent. Levier à prévoir : une option qui saute les auteurs des réactions pendant le premier import, puis les complète en tâche de fond.
- **Modifications et suppressions.** Avec B, on ré-exporte chaque nuit les 7 derniers jours pour rattraper ce qui a été modifié ou supprimé. Avec C, ces événements arrivent en direct.
- **Idempotence.** Importer deux fois le même fichier, ou deux exports qui se chevauchent, ne crée aucun doublon (vérifié : voir [base-de-donnees.md](base-de-donnees.md)).

## 4. Stockage : PostgreSQL seul, mesuré

La base et son schéma existent déjà ([schema.sql](../db/schema.sql)) : 206 Mo pour 500 000 messages, tous les messages d'une personne en 1 à 2 ms, recherche en français en 5 à 11 ms.

Pour la partie « temps réel », voici ce que j'ai mesuré pour éviter d'ajouter des services :

| Besoin | Solution | Mesure (500 000 messages) |
| --- | --- | --- |
| File de tâches pour l'IA | table `jobs` + `FOR UPDATE SKIP LOCKED` | **15 400 tâches réclamées par seconde** avec 4 ouvriers (une tâche d'IA dure des secondes : la file n'est jamais le goulot) |
| Prévenir la carte | `LISTEN` / `NOTIFY` | **1,2 ms** de délai médian (3,5 ms au pire) |
| Graphe des interactions | table `edges` (une ligne par paire de personnes et par type de lien) | reconstruction complète : **183 ms** ; mise à jour pour 1 000 nouveaux messages : **5 ms** |
| Recherche par le sens | pgvector | 3 ms pour les 5 plus proches (voir le coût en place dans le README de la base) |

**Ce que je n'ajoute volontairement pas** : Redis ou Kafka (la file Postgres suffit), Neo4j (le graphe tient dans une table et se calcule en SQL), Elasticsearch (la recherche française de Postgres suffit), Kubernetes, des microservices. Moins il y a de pièces, moins il y a de pannes et plus c'est facile à installer sur un serveur.

**Tables d'analyse** (fichier [schema-analysis.sql](../db/schema-analysis.sql), testé) :

| Groupe | Tables et vues |
| --- | --- |
| Thèmes | `topic_runs` (une découverte automatique), `topics` (statut : proposé, validé, fusionné, rejeté) |
| Axes et idéologies | `axes`, `axis_anchors`, `ideologies`, `ideology_axis_ranges` |
| Rôles | `role_rules`, vues `classified_roles`, `claimed_ideologies` |
| Idées et preuves | `propositions`, `proposition_axis`, `claims`, `claim_evidence`, `conversations`, `conversation_messages` |
| Positions | vue `current_stances`, table `person_axis_scores`, fonction `refresh_person_axis_scores()`, table `scoring_settings` |
| Vérification | vues `ideology_concordance`, `claimed_ideology_summary`, `claimed_ideology_conflicts` |
| Graphe et travail | `edges`, `jobs` |

Les tables `profiles` et `cards` existent déjà. Les vecteurs des affirmations et des propositions sont dans [schema-vector.sql](../db/schema-vector.sql). Les données de départ (axes, idéologies, rôles) sont dans [seed-axes.sql](../db/seed-axes.sql) : c'est un fichier à relire et à modifier.

**Poids** : environ 430 octets par message en base (mesuré). 1 million de messages ≈ 430 Mo, plus les vecteurs si on en calcule (environ 13 Ko par message vectorisé : on ne vectorise donc que ce qui en vaut la peine, voir §5).

## 5. Analyse par l'IA locale : une cascade, pas un modèle qui lit tout

Faire lire 1 million de messages à un grand modèle serait trop long (voir le coût plus bas). On filtre d'abord avec des méthodes peu coûteuses, et le grand modèle ne voit que ce qui compte, **avec son contexte**.

| Étape | Méthode | Coût |
| --- | --- | --- |
| 1. Conversations | on regroupe les messages en discussions : chaînes de réponses, plus coupure après 20 minutes de silence, 40 messages au plus. Le JSON v2 garde déjà le texte du message auquel on répond, ce qui sert de contexte | SQL, secondes |
| 2. Tri | on écarte les bots, les messages vides, les « mdr », les liens seuls ; on note l'importance (longueur, réponses reçues, réactions) | SQL, secondes |
| 3. Vecteurs | calcul des vecteurs sur les messages retenus ; détection des doublons ; découverte des thèmes par regroupement | modèle d'embeddings local |
| 4. Extraction | par discussion, le grand modèle liste les affirmations de chaque personne **dans un format imposé** (JSON contraint), avec les identifiants des messages qui les prouvent | **le poste coûteux** |
| 5. Normalisation | chaque affirmation est rattachée à une proposition existante (vecteur le plus proche + vérification) ou crée une nouvelle proposition | vecteurs + petit appel |
| 6. Relations | pour chaque réponse, nature du lien envers le message d'origine : accord, désaccord, soutien, moquerie, information… | réutilise l'étape 4 |

**Pourquoi des discussions et pas message par message** : « oui, tout à fait » ne veut rien dire seul. Dans son contexte, c'est un accord avec quelqu'un. Lire par discussion donne aussi de meilleurs résultats et partage le contexte entre plusieurs messages, donc moins de calcul.

**Coût de l'étape 4 (estimation, à mesurer)** : un message moyen fait environ 58 caractères, soit 15 à 20 tokens. Une discussion de 20 messages avec les consignes fait de l'ordre de 900 tokens à lire et 250 à écrire. Sur une puce comme la vôtre (M4 Pro, 24 Go), un modèle de 8 milliards de paramètres lit quelques centaines de tokens par seconde et en écrit quelques dizaines : environ 5 à 15 secondes par discussion. Si le tri retient 30 % des messages d'un serveur de 1 million de messages, cela fait environ 15 000 discussions, soit un à deux jours de calcul en tâche de fond. Pour 100 000 messages : quelques heures. Le travail avance par ordre d'importance, donc les premiers résultats utiles arrivent bien avant la fin. **Aucune IA locale n'est installée sur cette machine, donc ces durées ne sont pas mesurées** : la première chose à faire sera un petit banc d'essai.

**Choix du modèle** : un modèle de langue de 7 à 14 milliards de paramètres, quantifié, de la famille Qwen, Mistral, Gemma ou Llama (récents, bons en français), servi par Ollama ; un modèle d'embeddings multilingue (par exemple bge-m3 ou multilingual-e5). Le choix final se fait sur un jeu de test annoté par vous, pas sur la réputation.

## 6. Axes, idéologies et vérification par les rôles

L'erreur à éviter est de demander au modèle « quelle est l'idéologie de Paul ? » : la réponse serait invérifiable. À la place, une chaîne où chaque maillon se contrôle :

```
messages ──► affirmations ──► propositions ──► positions ──► score par axe ──► vérification
 (preuves)    (qui dit quoi)   (comparables)   (pour/contre)    (calcul)       avec ses rôles
```

### Les axes

Ce sont les échelles sur lesquelles on place les personnes, de -1 à +1. **Les 12 axes, leurs noms et leurs deux pôles viennent du modèle [12 Axes](https://12axes.vercel.app)** (section « What does each axis mean? ») : sur ce site, chaque axe a un pôle de gauche et un pôle de droite, ici -1 et +1. Les définitions, les repères et les fourchettes sont écrits pour ce projet.

Chaque axe est défini précisément en base (`axes`, `axis_anchors`) : la question qu'il pose, ce qu'il couvre, ce qu'il ne couvre pas (pour qu'un sujet n'appartienne qu'à un axe), et ce que veulent dire -1, 0 et +1 en une phrase. Les pôles ne sont pas des jugements de valeur.

| Axe | Question | -1 | +1 |
| --- | --- | --- | --- |
| `structure` | Pouvoir réparti entre régions et collectivités, ou concentré dans un État unitaire ? | Fédéral | Unitaire |
| `representation` | Pouvoir issu d'élections libres et d'une opposition, ou d'un chef, d'un parti, d'experts ? | Démocratie | Autocratie |
| `pouvoir` | Ordre et sécurité, ou liberté individuelle ? | Sécurité | Liberté |
| `immigration` | Assimilation à l'identité nationale, ou multiculturalisme ? | Assimilation | Multiculturalisme |
| `diplomatie` | Force militaire, ou négociation ? | Militariste | Pacifiste |
| `intervention` | Rester en retrait du monde, ou défendre activement les intérêts nationaux ? | Non-interventionniste | Nationaliste |
| `economie` | Entreprises et services essentiels publics, ou privés ? | Public | Privé |
| `controle` | Économie planifiée et régulée, ou libre marché ? | Planification | Libre marché |
| `commerce` | Protéger l'industrie nationale, ou ouvrir au commerce mondial ? | Protectionnisme | Globalisme |
| `religion` | Religion hors de la vie publique, ou influente ? (la laïcité est ici) | Irréligieux | Religieux |
| `morale` | Faire évoluer les normes sociales, ou préserver la tradition ? | Progressiste | Traditionaliste |
| `technologie` | Accélérer le développement technique, ou prudence envers le vivant ? | Technologie | Biologie |

**Neuf axes ajoutés**, présents mais **inactifs** (ils ne sont pas calculés tant que vous ne les avez pas relus et activés). Les trois premiers couvrent ce que les 12 ne couvrent pas et que vos rôles expriment : `europe` (souveraineté nationale ↔ intégration européenne : Européiste, Eurosceptique), `ecologie` (productivisme ↔ écologie) et `rupture` (réforme ↔ rupture : Pragmatique, Extrême-Gauche). Les six autres portent sur des sujets importants du débat français : `redistribution` (protection sociale et fiscalité), `confiance` (institutions, experts, médias), `genre` (égalité des sexes), `animaux` (condition animale), `alliances` (OTAN, atlantisme ou non-alignement) et `participation` (démocratie directe ou représentative). Chacun a sa question, ce qu'il ne couvre pas, et ses trois repères. **Tout est à relire dans [AXES.md](AXES.md)**, une page générée depuis la base.

Activer un axe, c'est `UPDATE axes SET is_active = true WHERE code = 'europe'`, sans toucher au reste ; j'ai vérifié qu'une fois activé il est calculé et utilisé dans la vérification.

Une réserve sur le modèle : le site précise lui-même que son test est éducatif et non validé scientifiquement. La précision du classement ne vient donc pas de ce choix d'axes, mais des preuves qui sont derrière chaque score. Certains axes (Technologie et nature, Intervention) risquent aussi de peu apparaître dans des discussions politiques françaises : leurs scores resteront alors marqués « insuffisant », ce qui est le comportement voulu.

### Les idéologies

Une idéologie est un nom, plus **ce qu'elle implique sur les axes** : une fourchette de scores (`ideology_axis_ranges`). Par exemple, *Communiste* implique `economie` entre -1 et -0,7 (public) et `controle` entre -1 et -0,5 (planification) ; *Eurosceptique* implique `europe` entre -1 et -0,2 et `intervention` entre 0 et 1. Les familles reçoivent aussi une place sur le spectre, avec le vocabulaire des 12 Axes (extrême gauche, gauche, centre, droite…), utile pour colorer la carte. Trois sortes, car toutes ne contraignent pas autant :

| Sorte | Ce que c'est | Exemples |
| --- | --- | --- |
| `famille` | une famille politique entière, qui contraint plusieurs axes | Communiste, Socialiste, Gaulliste, Centre-Gauche |
| `position` | une position sur un ou deux axes | Européiste, Protectionniste, Écologiste, Progressiste |
| `valeur` | une valeur ou une attitude, qui n'implique presque rien | Humaniste, Démocrate, Patriote, Pragmatique |

28 idéologies sont préparées (72 fourchettes), toutes marquées « non validées » (`is_validated`) tant que vous ne les avez pas relues. Les fourchettes sont larges exprès : un écart n'est signalé que s'il est net. Celles qui portent sur un axe inactif ne comptent qu'une fois l'axe activé.

### Les rôles que les gens se donnent

Les rôles sont reconnus par leur nom (`role_rules`), quel que soit le serveur. Sur votre export (51 rôles), la reconnaissance donne : 27 rôles d'idéologie, 7 de notification (« Ping… »), 3 d'équipe, 2 d'âge, 2 de genre, 1 de base, 7 séparateurs, et 2 non reconnus (« Dunes », « Plato »). **Seuls les rôles d'idéologie servent à la vérification.** Les rôles d'âge et de genre sont reconnus pour être **écartés** : jamais analysés, jamais affichés sur une carte.

Constat sur vos données : ces rôles sont des étiquettes posées à la légère. Dans l'échantillon, les 3 membres (sur 8) qui en ont pris en ont en moyenne 14 sur 27, et 2 d'entre eux ont des rôles qui se contredisent (par exemple Protectionniste et Mondialiste, ou Gaulliste et Multiculturaliste). C'est pourquoi la vérification se fait rôle par rôle, et que les contradictions entre rôles sont repérées à part (`claimed_ideology_conflicts`).

### Où se trouve une personne sur un axe

Chaque position (pour, contre, nuancé) d'une personne sur une proposition compte pour un axe selon deux choses : la confiance de l'analyse, et le poids de la proposition sur l'axe. Le score est la moyenne pondérée, tirée un peu vers 0 par une part de « doute », pour qu'**une seule remarque ne donne jamais un score ferme**. L'incertitude diminue quand les preuves s'accumulent et ne descend jamais sous un plancher qui représente les erreurs inévitables (ironie, citations). Le calcul est une fonction SQL (`refresh_person_axis_scores`), ses réglages sont dans `scoring_settings`, et il est reproductible : mêmes preuves, même score. Les positions ont une date : on garde l'historique, et la position « actuelle » est la plus récente.

### La vérification avec les rôles, affichée sur la fiche

Pour chaque rôle d'idéologie pris par la personne et chaque axe qu'il contraint, on compare l'intervalle de son score à la fourchette attendue :

| Verdict par axe | Sens |
| --- | --- |
| **confirmé** | l'intervalle du score est entièrement dans la fourchette |
| **compatible** | il la chevauche |
| **incompatible** | il est entièrement en dehors : ce que dit la personne ne correspond pas |
| **insuffisant** | pas assez de preuves (par défaut : moins de 3 positions ou trop peu de confiance cumulée) |

Par rôle, cela donne : **concordant** (rien d'incompatible et au moins un axe évaluable), **discordant** (au moins un axe incompatible) ou **non vérifiable**. En cliquant sur une personne, la fiche montre : les rôles qu'elle a pris, leur verdict, et pour chaque axe le score avec son incertitude face à la fourchette attendue, avec les messages qui le prouvent. Par exemple : « Rôle Européiste, discordant. Axe Europe : score -0,69 ± 0,38, attendu entre +0,3 et +1, d'après 3 positions » avec les 3 citations.

Un verdict « discordant » ne dit pas que la personne ment : le rôle peut être pris à la légère, ou ses idées avoir changé. C'est une alerte à regarder, pas une accusation. Je l'ai testé sur un scénario inventé (un eurosceptique cohérent, un « européiste » qui défend le contraire, un communiste, un rôle sans preuve, deux rôles contradictoires) : les verdicts sont ceux attendus, et rejeter une preuve fait bien bouger le score ou le retire.

### Les thèmes : découverte d'abord

1. **Découverte, sans tenir compte des personnes.** À partir des discussions, regroupement par proximité de sens puis nommage par le modèle. On obtient des thèmes au statut « proposé » (`topics`, avec la trace de la découverte dans `topic_runs`).
2. **Validation.** Dans l'écran « À revoir » : vous validez, renommez, fusionnez ou rejetez. Les propositions (« il faut augmenter le SMIC ») se rattachent aux thèmes validés.
3. **Précision, puis ajouts.** Vous pouvez affiner (un thème devient plusieurs, `parent_id`) et ajouter à la main des thèmes qui vous intéressent (`origin = 'manual'`). Relancer la découverte plus tard ne touche pas à ce qui est déjà validé.

### Mesurer la précision

Vous annotez une petite série d'affirmations ; on mesure l'accord avec le système et on le suit à chaque changement de modèle ou de consigne (`profiles` garde déjà le modèle et la version de la consigne). Les rôles donnent une deuxième mesure, gratuite : si, sur un axe, les scores calculés contredisent systématiquement les rôles, c'est que la définition de l'axe ou le poids des propositions est à revoir. Les rôles étant des étiquettes légères, ce signal se lit avec prudence.

**Les actions** (ce que font les personnes, indépendamment de ce qu'elles pensent) se calculent surtout en SQL, sans IA : part de messages qui lancent une discussion ou qui répondent, longueur et régularité, diversité des sujets, réponses reçues, réactions reçues, rôle de modération (sanctions des bots, messages épinglés, sondages lancés), influence dans le graphe. Les cartes mêlent ces deux dimensions : idées et actions.

## 7. Le graphe des interactions

**Liens** (entre deux personnes, orientés) : réponse, mention, réaction, plus la proximité de conversation (deux personnes qui se répondent dans la même discussion). Chaque lien a un **poids avec décroissance dans le temps** (demi-vie réglable, 90 jours par défaut : les échanges récents comptent plus), et une **nature** quand l'IA l'a déterminée (accord, désaccord, soutien, conflit).

**Calcul** : le graphe se maintient tout seul. Chaque nouveau message ajoute ou renforce quelques liens (5 ms pour 1 000 messages, mesuré) ; une reconstruction complète prend moins d'une seconde pour 500 000 messages.

**Communautés** : détection par la méthode de Leiden (bibliothèque igraph), recalculée chaque nuit et à la demande. Un identifiant de groupe reste stable d'un calcul à l'autre (on rattache chaque nouveau groupe à l'ancien qui lui ressemble le plus), pour que les couleurs de la carte ne changent pas sans raison.

## 8. L'application et la carte

**Serveur** : une application Python (FastAPI) qui sert l'interface, expose une API, envoie les événements en direct (SSE, alimenté par `NOTIFY`) et fait tourner les ouvriers d'analyse. Python parce que l'analyse de texte et de graphes y est la mieux outillée ; l'exportateur (qui était en C#) est depuis le 4 octobre 2026 écrit en Python dans `app/dindon/export/` (voir [EXPORTATEUR.md](EXPORTATEUR.md)).

**Interface** : une page web (Svelte et Vite) servie par la même application. Le graphe est dessiné avec Sigma.js (WebGL) et graphology, avec le placement des nœuds calculé dans un thread à part. Cela reste fluide à plusieurs milliers de personnes ; au-delà, on n'affiche que les plus actives et on agrège le reste.

L'habillage reprend celui du tableau de bord de Poulet (mêmes couleurs, même police, même barre de gauche) : voir « Habillage de l'interface » dans [DECISIONS.md](DECISIONS.md).

**Ce que vous voyez**

| Vue | Contenu |
| --- | --- |
| **La carte** | une personne = un point (taille : influence ; couleur : communauté ou position sur un axe au choix). Un lien = une ligne dont l'épaisseur est le poids, la couleur la nature (vert : accord, rouge : conflit, gris : neutre). Les groupes se détachent naturellement. À chaque nouveau message, le lien concerné s'illumine. Une frise permet de rejouer l'évolution dans le temps |
| **La fiche d'une personne** | ses scores sur chaque axe avec leur incertitude, **la vérification avec les rôles qu'elle s'est donnés** (§6), ses positions classées par thème, **chaque position avec ses citations cliquables** (le message dans son contexte), son évolution, ses statistiques d'actions, ses liens principaux, un résumé écrit par l'IA qui ne contient que des phrases adossées à des preuves |
| **La vue d'un thème** | qui pense quoi sur une proposition, avec les preuves : la « banque d'information » pour justifier les positions |
| **La boussole** | les personnes placées sur deux axes au choix |
| **À revoir** | les affirmations à faible confiance, à confirmer ou corriger en un clic |

L'apparence : fond sombre, points lumineux, lignes fines qui s'épaississent, mouvements lents. Les cartes de divertissement sont générées à partir des fiches (image exportable), sans attribut sensible par défaut.

## 9. Déploiement compact

Trois conteneurs et un programme :

| Élément | Rôle |
| --- | --- |
| `db` : PostgreSQL 17 + pgvector | toute la donnée (existe déjà, [db/](../db/)) |
| `ollama` : modèles de langue et de vecteurs | l'IA locale |
| `app` : application Python | ingestion, ouvriers d'analyse, API, flux en direct, interface web |
| exportateur (`app/dindon/export/`, Python, dans le processus `app`) | collecte manuelle et surveillance (remplace le programme C# d'origine) |

Un seul `docker compose up`. Le serveur doit avoir de quoi faire tourner le modèle : plus que tout autre élément, c'est la mémoire (et idéalement une carte graphique) qui décide de la taille du modèle et du temps d'analyse. La base et l'application, elles, tiennent sur une petite machine.

## 10. Vie privée et garde-fous

Ce système dresse le profil de personnes identifiables, dont leurs opinions politiques : en droit européen (RGPD), ce sont des données sensibles. Un usage strictement personnel est hors du champ ; **ce n'est plus le cas dès que le résultat est montré à d'autres, publié, ou utilisé par une organisation**. Vous êtes seul pour l'instant : si cela change, il faudra le faire valider (je ne suis pas juriste).

Garde-fous prévus dans la conception :

- **Local seulement**, avec un mot de passe sur l'interface même si vous êtes seul, jamais exposée sur Internet, disque chiffré.
- **Rien d'inféré en douce.** Les positions viennent de ce que la personne a écrit, avec citation. On ne déduit pas une orientation de signaux indirects (style, horaires, fréquentations).
- **Âge et genre écartés.** Les rôles de ce type sont reconnus pour être ignorés. Les rôles d'âge du serveur (par exemple « Entre 16 et 20 ans ») montrent que des mineurs en font partie : raison de plus pour ne pas diffuser les fiches.
- **Des étiquettes honnêtes.** Un classement s'affiche toujours avec son nombre de preuves et son incertitude, jamais comme un fait. « Discordant » est une alerte, pas une accusation.
- **Pseudonymisation à la demande** : un mode d'affichage qui remplace les noms par des pseudonymes, utile le jour où vous voudrez montrer la carte.
- **Débats et vérification sur Internet** ([DEBAT.md](DEBAT.md)) : la seule chose qui sort de la machine, pour vérifier une affirmation, est une phrase de recherche neutre (budget de 2 recherches et 3 pages par affirmation, pages de sources de confiance seulement, citations vérifiées sur la page) ; un test de structure interdit tout autre chemin vers l'extérieur ; lecture des messages à l'aveugle ; corrections publiques verrouillées par une précision mesurée.
- **Effacement** : `forget_user()` supprime une personne et tout ce qui la concerne (déjà dans le schéma), y compris ses positions et ses cartes.

## 11. Feuille de route

Chaque étape donne quelque chose d'utilisable.

| Étape | Contenu | Ce que vous obtenez |
| --- | --- | --- |
| 0. *(fait, testé)* | Export JSON v2, schéma PostgreSQL, chargeur, **modèle d'analyse : axes, idéologies, rôles, calcul des scores, vérification** | les données dans une base solide, et la grille de lecture prête à être relue |
| 1. Collecte automatique et carte des interactions | commande `watch`, ingestion continue, table `edges`, application et carte | **une carte en direct des échanges entre personnes, sans IA** |
| 2. Découverte des thèmes | vecteurs, regroupement des discussions, nommage, écran de validation | explorer ce qui se dit, par thème |
| 3. Affirmations et preuves | extraction par l'IA, propositions et leurs poids sur les axes, fiches avec citations | **la banque d'information** |
| 4. Classement et vérification | calcul des scores, vérification avec les rôles sur la fiche, file « à revoir » | le classement des personnes, avec incertitude et contrôle |
| 5. Finitions | frise de rejeu, cartes de divertissement, pseudonymisation | le rendu final |
| Plus tard | bot en direct (mode C) | mise à jour instantanée |

## 12. Ce qui reste à décider

| Question | Mon choix par défaut | Ce que ça change |
| --- | --- | --- |
| Les fourchettes des idéologies de [seed-axes.sql](../db/seed-axes.sql), et les 9 axes ajoutés à activer ou non | fourchettes : proposition à relire ; axes ajoutés : inactifs | la qualité du classement : c'est ce qui compte le plus |
| Matériel de l'IA (carte graphique, mémoire) | une machine comme la vôtre (24 Go) | taille du modèle, durée du premier import |
| Serveur d'installation (système, mémoire, disque) | un Linux avec Docker | seulement le dimensionnement, l'architecture ne change pas |
| « Temps réel » | quelques dizaines de secondes pour les liens, quelques minutes pour les idées, instantané avec le bot | surveillance ou bot |
