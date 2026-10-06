# Dindon : rapport complet, partie par partie

*Écrit le 4 octobre 2026, pour vous (la personne qui fait tourner Dindon). Chaque chiffre a été revérifié ce jour-là par une commande, un test ou une lecture du code, pas recopié de mes notes. Chaque affirmation porte un niveau de preuve :*

| Niveau | Veut dire |
| --- | --- |
| **implémenté** | le code existe et un test l'exerce |
| **simulé** | testé contre un faux Discord, un faux Gateway ou un faux Ollama que j'ai écrits |
| **vrai Discord** | a réellement tourné contre Discord (vos serveurs) |
| **mesuré** | un chiffre relevé en exécutant la chose, sur **données inventées** sauf mention contraire |
| **estimé** | calculé ou deviné, pas mesuré |

Ce rapport ne remplace pas les pages détaillées ([RAPPORT-ARCHITECTURE.md](RAPPORT-ARCHITECTURE.md) pour l'architecture, [VALIDATION-AXES.md](VALIDATION-AXES.md) pour les axes) : il dit, pour chaque pièce, **où elle en est vraiment**.

---

## 0. En une page

**Ce qu'est Dindon.** Une carte vivante d'un serveur Discord, entièrement locale : le bot reçoit les messages, une base PostgreSQL les range, une IA locale (Ollama) lit les conversations pour dire de quoi on parle et ce que chacun défend (avec la citation qui le prouve), puis compare ce que les gens disent aux rôles d'idées qu'ils se sont donnés.

**Où ça en est, pièce par pièce.**

| Pièce | Construit | Preuve la plus forte | Prêt pour un vrai serveur chargé ? | Risque principal |
| --- | --- | --- | --- | --- |
| 1. Contrat JSON v2 + ingestion | oui | **mesuré** : 500 000 messages en 26,5 s ; **vrai Discord** : vos 474 messages | **Oui** | les copies JSON gardées dans `archive/` sont des données personnelles de plus |
| 2. Base de données | oui | **mesuré** ; **sauvegarde restaurée avec succès aujourd'hui** | **Oui** | une seule machine (voir 13) |
| 3. Exportateur Dindon | oui | **simulé** (27 tests) + **vrai Discord** (474 messages identiques à l'ancien exportateur, 5 et 21 messages identiques aux rattrapages) | **Avec réserve** | jamais vu : un gros salon, les vraies limites de débit, les fils, les sondages, les transferts |
| 4. Collecte (relevé, rattrapage, import partiel) | oui | **simulé** ; **vrai Discord** : le rattrapage a tourné 3 fois aujourd'hui | **Avec réserve** | chaque redémarrage de l'application relance un rattrapage de 7 jours |
| 5. Bot Discord | oui | **vrai Discord** : connecté, 2 serveurs, `/dindon` enregistrée ; **mesuré** 300 msg/s sans perte (faux Gateway) | **Avec réserve** | **jamais essayé en vrai** : modifications et suppressions en direct (ajoutées le 5 octobre, simulées seulement) ; réactions non reçues ; Mac en veille = bot hors ligne |
| 6. Vie privée et conformité | oui | **simulé** ; effacement **mesuré** (0,2 à 1,5 s) | **Non, pas encore** | pas de consentement préalable, pas de contact indiqué (`DINDON_CONTACT` vide), conservation illimitée, bot qui suit **tous** les serveurs où il est |
| 7. API | oui | **implémenté** : 40 routes, toutes derrière une session sauf la connexion, `/api/session` et `/health` | **Oui** | un seul mot de passe ; `/openapi.json` et `/health` ouverts (en local seulement) |
| 8. Interface | oui | **simulé** + navigateur réel (20 tests) ; aucune requête hors de l'application | **Oui** | un test de survol de la carte instable sous charge |
| 9. Analyse IA (conversations, thèmes, positions) | oui | **mesuré** sur données inventées : thèmes 87 %, sens des positions 86 % | **Non** | **jamais lancée sur de vraies données** ; 14 % de positions à l'envers |
| 10. Axes et scores | oui | **mesuré** : avec les 21 axes (désormais actifs), 68 % de liens corrects et 4 % à l'envers sur les vraies propositions (60 % et 8 % avec 12 axes ; référence relue en voyant l'IA) | **Avec réserve** | il faut valider les poids ; 28 % de liens sur un axe non retenu |
| 11. Rôles contre positions | oui | **mesuré** | **Non** | ne détecte aucun rôle faux sur le serveur de test (7 des 9 n'ont rien dit sur les axes de leur rôle ; plus d'axes = moins de preuves par axe) |
| 12. Performance et lecture automatique | oui | **mesuré** | **Oui** | le préréglage « Économe » rend l'IA très lente (voir 12) |
| 13. Exploitation (Docker, hôte macOS) | oui | **vrai** : tourne depuis 2 jours | **Avec réserve** | conteneurs en root ; bot sans surveillance Docker ; une seule machine |
| 14. Tests et outils | oui | 449 tests, tous réussis au dernier passage (un test de survol reste instable sous charge) | n/a | une partie de la preuve vient de faux que j'ai écrits moi-même |
| 15. Documentation | 22 pages | n/a | **À jour pour l'essentiel** | `RESUME.md` était périmé (état du 2 octobre) : rafraîchi aujourd'hui ; plusieurs pages restent des documents de départ |

**Les cinq choses à régler avant de laisser le bot sur des gens qui ne savent pas qu'il est là** (par ordre d'importance) :

1. **Indiquer un contact** (`DINDON_CONTACT` dans `.env`, puis recréer les conteneurs). Aujourd'hui `/dindon info` ne dit pas à qui écrire. La page Vie privée l'affiche en bandeau.
2. **Décider des serveurs suivis.** `DINDON_GUILD_IDS=all` : le bot enregistre **tous** les serveurs où il est. Il en suit deux : « Serveur de Technowl_Z » (430 messages, 4 auteurs) et « L'Améliocratie » (44 messages, **11 auteurs**, dont le dernier date d'aujourd'hui). Est-ce voulu, et ces 11 personnes sont-elles informées ? (Je n'ai lu le contenu d'aucun message, seulement des nombres.)
3. **Fixer une durée de conservation** (`DINDON_RETENTION_DAYS`, 0 = illimité aujourd'hui).
4. **Ne pas lancer l'IA sur ces vraies données** avant d'avoir tranché 1 à 3 : l'analyse crée des opinions politiques attachées à des personnes identifiables (donnée sensible au sens du RGPD, art. 9). Elle n'a jamais été lancée sur le vrai serveur.
5. **Valider les poids des axes** avant de lire les scores comme des faits (voir 10).

**Une chose qui n'est pas du produit mais qui compte : le travail n'est pas commité.** Le dernier commit de `dindon/` date du 3 octobre à 00 h 49. Depuis : **146 fichiers** modifiés ou nouveaux (58 modifiés, 85 nouveaux, 3 supprimés ; environ 3 200 lignes ajoutées sur les seuls fichiers déjà suivis), c'est-à-dire presque tout ce qui est décrit ici (vie privée, analyse des positions, axes, performance, lecture automatique, exportateur). Ils n'existent que dans le dossier de travail ; la sauvegarde nocturne ne couvre que la **base**, pas le code. Je ne commite pas sans que vous me le demandiez.

**Ce que j'ai fait aujourd'hui, en une ligne.** Exportateur Dindon écrit et déployé ; axes de l'IA mesurés, 395 propositions relues et validées sur la base de test ; deux défauts trouvés et corrigés (relecture des axes qui gardait d'anciens liens ; proposition qui se refermait à la frappe) ; **les 21 axes sont maintenant actifs** partout (jeu de départ, migration 0011, instance réelle et base de test) ; ce rapport.

---

## 1. Les chiffres du projet (comptés aujourd'hui)

| | |
| --- | --- |
| Code de l'application (`app/dindon/`) | 52 fichiers Python, **7 042 lignes** : API 1 538, bot 1 392, analyse 1 209, exportateur 660, collecte 660, ingestion 574, le reste (configuration, vie privée, performance, automatisation…) 1 009 |
| Interface (`web/src/`) | 16 composants Svelte + 3 modules, **5 756 lignes** de JS/Svelte |
| Base | 4 fichiers de base (schéma, analyse, axes de départ, vecteurs) + 11 migrations, **1 310 lignes** ; **44 tables, 9 vues**, 21 axes, 28 idéologies, 72 fourchettes, 37 règles de rôles |
| Outils | 3 584 lignes (faux Discord/Gateway/Ollama, serveur politique, mesures, relecture des axes…) |
| Tests | 7 673 lignes, **40 fichiers, 376 fonctions de test, 449 cas**, tous réussis au dernier passage complet |
| Documentation | 22 pages, environ 55 000 mots |
| Services en marche | `db` (PostgreSQL 17 + pgvector), `app`, `bot` (Docker) ; Ollama et la sauvegarde nocturne sur l'hôte (LaunchAgents) |
| Données réelles dans la base | 2 serveurs, 474 messages, 13 personnes, base de 12 Mo ; **0 position, 0 conversation, 0 thème : l'IA n'y a jamais tourné** |
| Serveur de test politique (inventé) | 100 personnes, 3 332 messages, 343 conversations, 9 thèmes, 396 propositions, 1 123 positions, base de 20 Mo |

---

## 2. Le contrat de données et l'ingestion

**Rôle.** Tout ce qui entre dans la base passe par **un seul chemin** : un document JSON « v2 » (schéma strict, `contracts/JSON-format.md`) lu par `ingest/loader.py`. Les trois portes d'entrée (fichiers déposés à la main dans `inbox/`, relevé REST, bot en direct) produisent le même document, donc la même validation.

**État : implémenté, mesuré, vrai Discord.**

- **mesuré** : 500 000 messages importés en 26,5 s (≈ 18 900 messages/s), 276 Mo de base ; les liens du graphe calculés pendant l'import sont **identiques** à ceux reconstruits depuis zéro (0 différence sur 70 345). 300 000 messages en 29,8 s.
- **vrai Discord** : vos 474 messages réels sont ingérés ; le rattrapage a réimporté les 7 derniers jours aujourd'hui sans créer de doublon.
- Verrou consultatif (une seule ingestion à la fois), garde-fou contre une suppression de masse (refuse d'effacer si l'export semble manquer de plus de 30 % de la fenêtre), une base pas prête ne fait perdre aucun message (seules les fautes propres à un message sont isolées). 24 tests (`test_ingest` 20, `test_inbox` 4).

**Limites.**

- Les copies JSON des imports sont rangées dans `archive/` : **ce sont des copies des messages**, en dehors de la base. L'effacement d'une personne les réécrit (126 s pour 4,2 Go avec la personne dans tous les fichiers : le point lent) ; les **sauvegardes** gardent la personne 14 jours encore.
- Un fichier illisible est refusé en entier et mis de côté dans `inbox/failed/` avec un fichier `.error.txt` qui dit pourquoi ; il est compté « en échec » sur la page Système.

**À faire.** Rien de bloquant.

---

## 3. La base de données

**Rôle.** PostgreSQL 17 avec l'extension pgvector. Une migration légère maison (`migrate.py`, 75 lignes) : les 4 fichiers de base se rejouent sans effet, les migrations numérotées (`0001` à `0011`) s'appliquent une fois, et en modifier une déjà appliquée est une erreur.

**État : implémenté, mesuré, vrai.**

- **44 tables, 9 vues** (testé : `test_migrate`, 7 tests ; `test_health` vérifie le même compte sur `/health`).
- **mesuré** (500 000 messages) : API du graphe 0,2 à 0,3 s ; fiche d'une personne de 70 000 messages 0,4 s ; reconstruction complète des liens 1,3 à 1,7 s.
- **Sauvegarde : restaurée avec succès aujourd'hui.** J'ai restauré le dernier dump (`dindon-2026-10-04-0334.sql.gz`) dans une base temporaire : 0 erreur, 472 messages / 13 personnes / 5 liens / 21 axes ; la base vivante en a 474 (2 messages arrivés depuis). Base temporaire supprimée. Je n'ai trouvé trace d'aucune vérification de restauration avant celle-ci (`DINDON_JURIDIQUE_ET_AMELIORATIONS.md` la réclamait).
- Sauvegarde nocturne à 03 h 30 (LaunchAgent `com.dindon.backup`), 14 jours gardés, dossier en `chmod 700`, dumps en `600`. Deux dumps existent (3 et 4 octobre). Le disque de l'hôte est chiffré (**FileVault actif**).

**Limites et risques.**

- **Le dump contient tous les messages**, comme la base. Il reste sur cette machine, protégé par FileVault, mais il n'est pas chiffré en lui-même.
- La migration 0011 (les 21 axes actifs) est **appliquée** sur l'instance réelle (`/health` : `axes_active: 21`, 15 migrations).
- Le mot de passe de la base n'est pris en compte qu'à la création du volume (noté dans le README).

**À faire.** Tester de temps en temps la restauration (une commande, trois lignes dans le README).

---

## 4. L'exportateur de Dindon

**Rôle.** Lit Discord (API REST) et écrit le même JSON v2 que l'ancien exportateur C# (supprimé à votre demande). Dans `app/dindon/export/` (660 lignes) ; documenté dans [EXPORTATEUR.md](EXPORTATEUR.md).

**État : implémenté, simulé, vrai Discord (partiel).**

- **simulé** : 27 tests contre un faux Discord qui répond comme l'API REST (pagination dans le même sens que Discord, limites de débit, erreurs 401/403/404/429/5xx, annulation…).
- **vrai Discord** : lecture seule sur **474 messages réels** : texte, auteur, heure, réponses, mentions, pièces jointes, aperçus, autocollants, messages système **identiques** à l'ancien exportateur, aux écarts connus et notés près ([EXPORTATEUR.md](EXPORTATEUR.md) §6). Depuis : le **rattrapage a tourné 3 fois aujourd'hui** (à 14 h 55, 14 h 58 et 16 h 07 UTC, des heures qui correspondent à des redémarrages de l'application) et a rapporté **5 et 21 messages**, exactement le nombre de l'ancien exportateur sur la même fenêtre.
- Économe par construction : requêtes seulement pour ce qui est demandé, profils des membres demandés une fois (gardés 1 h), réactions « qui a réagi » seulement pour les messages récents (au choix : tous / récents / aucun), connexions gardées ouvertes, limites de Discord respectées *avant* d'être atteintes. **mesuré** (faux Discord avec latence) : 6,6 s / 116 requêtes sans « qui a réagi », 14,1 s / 514 requêtes avec les 30 derniers jours (défaut).
- Le jeton ne figure dans aucun message d'erreur (test), les erreurs sont en français et disent quoi faire.

**Jamais vu en vrai** (honnêtement) : un **gros salon** (des dizaines de milliers de messages), les **vraies limites de débit** de Discord, les **fils**, les **sondages**, les **messages transférés**. Le jeu d'essai réel était de 474 messages dans 2 salons.

**À faire.** Un essai sur un salon un peu gros avant de compter dessus pour un premier import complet.

---

## 5. La collecte : relevé, rattrapage, import partiel

**Rôle.** `collector/` (660 lignes) : trois modes, un seul chemin d'ingestion.

| Mode | État | Preuve |
| --- | --- | --- |
| **Dépôt à la main** dans `inbox/` | implémenté | **vrai** |
| **Relevé** (poll : une requête par serveur toutes les 30 s, seuls les salons qui ont bougé sont lus) | implémenté | **simulé** ; délai mesuré de 0,15 à 1,99 s (médiane 0,3 à 1,3 s) au faux Discord |
| **Rattrapage nocturne** (7 jours relus pour voir modifications et suppressions) | implémenté | **vrai** : a tourné aujourd'hui |
| **Premier import** (`dindon backfill`) et **import partiel** (salons, personnes, période ; fenêtre « Importer ») | implémenté | **simulé** ; la liste des salons via l'API a marché en vrai le 3 octobre, la fenêtre « Importer » elle-même n'a jamais été utilisée en vrai ; la lecture des messages en vrai, **seulement via le rattrapage** |

Un import restreint par personnes ou par période est **partiel** : il ne compte jamais comme un premier import et ne marque jamais un salon à jour (colonne `is_partial`, migration 0002).

**Votre configuration actuelle** : `DINDON_COLLECTOR=catchup` → pas de relevé, le bot apporte les nouveaux messages et l'application ne fait que le rattrapage.

**Particularité à connaître.** La condition du rattrapage est « il est 03 h UTC passées et je n'en ai pas fait aujourd'hui », et la mémoire du « fait aujourd'hui » est **vidée à chaque redémarrage** : donc **chaque redémarrage de l'application après 03 h UTC relance un rattrapage de 7 jours**. Aujourd'hui, 3 redémarrages = 3 rattrapages (inoffensifs : même résultat, quelques requêtes par salon). Pas un défaut grave, mais à savoir.

**Limites.** Tests : `test_collector` 17, `test_import_selection` 15, `test_import_api` 11, `test_live` 3 (tous contre le faux Discord).

---

## 6. Le bot Discord

**Rôle.** Reçoit chaque nouveau message au moment où il est écrit (Gateway), le convertit avec `bot/adapter.py` (le même que l'exportateur : un texte identique) et l'envoie à l'ingestion par lots. Écoute aussi les commandes `/dindon`. 1 392 lignes ; `discord.py 2.7.1` n'est importé que par `gateway.py`.

**État : implémenté, simulé, vrai Discord (partiel).**

- **vrai Discord** (3 octobre) : connexion Gateway, `GUILD_CREATE` lu (9 salons et fils, 4 rôles sur le premier serveur), Message Content autorisé, un message de test ingéré **en 69 ms**, commande `/dindon` enregistrée (« registered » dans le journal). **Aujourd'hui** : le bot redéployé s'est reconnecté et voit **2 serveurs** (le second : 11 salons et fils, 8 rôles).
- **mesuré** (faux Gateway) : 100 messages/s sur 40 salons pendant 20 s : 2 000 sur 2 000 écrits, aucune perte ; **300 messages/s** sur 80 salons : 6 000 sur 6 000, vidé 3,9 s après le dernier. Équivalence avec l'export : 3 202 messages sur 3 202 identiques en passant par le moteur du bot (**simulé**).
- Tests : `test_bot` 24, `test_adapter` 30, `test_gateway` 9, `test_follow_all` 5 (+ outil de latence).

**Limites et risques (à lire).**

1. **Les réactions ne sont pas reçues en direct** (les intents demandés sont Guilds, Guild Messages, Message Content). Depuis le 5 octobre, les **modifications et suppressions sont appliquées en direct** (une suppression retire aussi ce qui en avait été déduit) : voir DECISIONS.md.
2. **Pas de rattrapage automatique du trou** après une nouvelle session Gateway (il est journalisé, pas comblé).
3. **Le bot suit tous les serveurs où il est** (`DINDON_GUILD_IDS=all`, voir 0). Inviter n'est donc pas neutre.
4. **L'affichage de `/dindon` dans un vrai serveur n'a jamais été vérifié** : l'enregistrement a réussi, l'usage par un membre non.
5. **Une machine en veille = un bot hors ligne** : le Mac est actuellement sur batterie (98 %).
6. Le conteneur du bot n'a pas de surveillance Docker (`healthcheck`) ; c'est la page Système (signe de vie toutes les 30 s) qui sert de contrôle. Il tourne en **root**.

---

## 7. Vie privée et conformité

**Rôle.** Rendre l'arrêt et l'effacement possibles, pour les membres comme pour vous. Code : `privacy.py` (225 lignes), `bot/privacy_commands.py`, `api/privacy.py`, page « Vie privée ». Cadre juridique : [CONFORMITE.md](CONFORMITE.md) ; texte à donner aux membres : [INFORMATION-MEMBRES.md](INFORMATION-MEMBRES.md).

**État : implémenté, simulé.**

- Commandes que tout membre tape lui-même : `/dindon info`, `mes-donnees` (un fichier JSON de ses données), `stop` (s'arrête d'être enregistré, réversible), `effacer` (bouton de confirmation, irréversible), `reprendre`. Réponses différées (limite de 3 s de Discord), délai de 15 s par personne.
- L'effacement (sous le verrou d'ingestion) supprime la personne, **les conversations qui contiennent ses messages**, tout ce qui en est dérivé (positions, scores, vecteurs) et **réécrit** les JSON de `inbox/` et `archive/`. Le registre garde **seulement l'identifiant**, pour qu'elle ne soit pas réenregistrée par un import, un rattrapage ou le bot. **mesuré** : 0,24 s (personne moyenne) à 1,52 s (la plus active, 40 518 messages) ; 126 s pour réécrire l'archive de 4,2 Go.
- Purge par durée (`DINDON_RETENTION_DAYS`), page « Vie privée » (chercher, traiter une demande reçue autrement, journal sans aucun message).
- 25 tests (`test_privacy`) + 1 test navigateur.

**Ce qui n'est PAS fait** (écrit tel quel dans CONFORMITE.md) : **consentement préalable** (art. 9 : opinions politiques), **vérification d'âge** (les rôles d'âge `entre N et M ans` ne distinguent pas un mineur d'un majeur), **analyse d'impact** (AIPD), **information individuelle** des membres avant l'enregistrement.

**État de votre instance aujourd'hui** :

| | |
| --- | --- |
| Durée de conservation | **illimitée** (`DINDON_RETENTION_DAYS=0`) |
| Personnes ayant demandé l'arrêt | 0 |
| Serveurs enregistrés | 2, **dont un second où 11 personnes ont écrit** depuis l'ajout du bot |
| Positions et opinions déduites | **0** : l'IA n'a pas tourné sur ces données |

**Risque principal du projet.** C'est la partie où une erreur coûte le plus (juridiquement et humainement), pas la technique. La position raisonnable : bot actif seulement là où les gens savent qu'il est là, contact renseigné, durée fixée, et l'IA lancée seulement sur un serveur dont les membres en ont été informés.

---

## 8. L'API

**Rôle.** `api/` (1 538 lignes) : FastAPI. **40 routes**.

| Famille | Routes | Rôle |
| --- | --- | --- |
| session | `/api/login`, `/api/logout`, `/api/session` | mot de passe unique → cookie `HttpOnly`, `SameSite=Strict` ; trop d'essais → 429 |
| carte | `/api/graph`, `/api/people`, `/api/person/{id}`, `/api/guilds`, `/events` (SSE) | graphe, recherche, fiche, direct |
| analyse | `/api/analysis`, `/api/topics*` | lancer l'analyse, valider/renommer/fusionner/rejeter des thèmes |
| positions | `/api/positions*` (7) | propositions, fiche, cohérence, validation des liens, « ne compter que les validés » |
| vie privée | `/api/privacy*` (6) | registre, demandes, journal |
| système | `/api/status`, `/api/system`, `/api/performance*`, `/api/automation*`, `/api/bot/invite`, `/api/import*` | état, réglages, import, invitation |
| santé | `/health` | santé de la base et d'Ollama |

**Vérifié aujourd'hui** : j'ai appelé chaque route `GET` sans paramètre de chemin, sans session : **toutes répondent 401** sauf `/api/session`, `/health` et `/openapi.json`. En-têtes : `Content-Security-Policy` (`default-src 'self'`, scripts de soi seulement, aucun cadre autorisé), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`. Les erreurs ne divulguent ni le mot de passe de la base ni son adresse (test).

**Limites (mineures, local seulement).**

- `/openapi.json` est lisible **sans session** (le schéma de l'API ; `docs_url` est désactivé mais pas `openapi_url`).
- `/health` est public et donne les noms des modèles Ollama installés et le nombre de tables.
- Un seul mot de passe pour tout (pas de comptes). Le port 8000 n'est publié que sur `127.0.0.1`.
- Les identifiants Discord dépassent 2^53 : l'API les envoie **en chaînes** (un bug de précision l'avait montré).

---

## 9. L'interface, page par page

**Technique.** Svelte + Sigma (carte WebGL), servie par l'application elle-même. Aucune ressource externe : la police Inter est embarquée, la CSP interdit le reste (les tests du navigateur échouent si la page demande quoi que ce soit hors de l'application). Habillage repris de votre tableau de bord Poulet, interface à « 80 % comme 100 % ». **Vérifié aujourd'hui en navigateur réel** : aucune erreur dans la console, aucune réponse HTTP ≥ 400, aucun débordement horizontal à 390 px de large.

| Page | Ce qu'on y fait | Recherche / filtres | État |
| --- | --- | --- | --- |
| **Connexion** | mot de passe | | implémenté |
| **Carte** | un point par personne (taille : poids des échanges ; couleur : rôle Discord), un trait par paire qui se parle, en direct (SSE) ; clic = **fiche** : activité, liens principaux, salons, rôles d'idées (« non vérifiés »), **une barre par axe** avec le point de la personne, la marge d'incertitude et les cadres des rôles qu'elle s'est donnés, ses thèmes, **avec qui elle en a parlé** et si c'est d'accord ou non, ses citations | période (tout, 90 j, 30 j, 7 j, dates), réponses/mentions/réactions, nombre de liens, « personnes sans lien », recherche d'une personne, raccourci `/` | implémenté, **simulé** (+ **mesuré** : 400 personnes et 20 000 liens affichés en 1,8 s) |
| **Thèmes** | les sujets trouvés automatiquement, **que vous validez, renommez, fusionnez ou rejetez** ; lancer l'analyse | recherche, état, tri | implémenté, **mesuré** |
| **Positions** | chaque proposition avec ses barres (pour / nuancés / contre), qui dit quoi **avec la citation exacte**, relire les liens aux axes (valider, corriger, retirer), « ne compter que les liens validés », lancer la lecture | recherche, thème, position, tri | implémenté, **mesuré** |
| **Cohérence rôles / positions** | pour chaque personne portant un rôle d'idées : ce qu'elle dit correspond-il au rôle ? (contradiction / cohérent / pas assez de propos) | recherche, verdict, rôle | implémenté, **mesuré** |
| **Système** | l'état de chaque pièce (bot, collecte, base, IA), **lecture automatique** (réglable), **performance** (4 préréglages + réglages libres) | | implémenté, **simulé** |
| **Vie privée** | demandes, registre, durée de conservation, journal | recherche d'une personne | implémenté, **simulé** |
| **Importer** | fenêtre : salons proposés par Discord, filtres (auteurs, mentions, période), prévenue quand l'import est « partiel », progression, annulation | recherche de salon (accents ignorés) | implémenté, **simulé** |
| **Inviter le bot** | lien d'invitation (voir les salons, lire l'historique, rien d'autre), serveurs où le bot est, suivis ou non | | implémenté, **simulé** |

**Défauts connus et mineurs** : « 1 liens » (pas de pluriel au singulier, `Dashboard.svelte`) ; sur la page Cohérence, la tuile « personnes » compte des personnes (73) mais les trois autres comptent des **rôles** (14 + 68 = 82, car certaines personnes en portent plusieurs), ce qui ne s'additionne pas à l'écran (`api/positions.py`, le calcul `count`) ; un test de survol de la carte (`test_ui_map`) qui a échoué dans deux passages complets sur trois et réussit **3 fois sur 3 seul** (sensible à la charge de la machine), 20 tests navigateur optionnels (ils se sautent sans Playwright). Avec les 21 axes actifs, la fiche d'une personne affiche **21 barres** (j'ai vérifié : elle défile correctement) ; sur le serveur de test, les propositions ont été relues avec les nouveaux axes et les neuf barres ajoutées ont des données ; sur votre instance réelle, aucune barre n'en a (l'IA n'y a pas tourné).

---

## 10. L'analyse par l'IA : de la conversation aux positions

**Rôle.** Une cascade où chaque étape ne lit que ce que l'étape d'avant a produit, et où **rien n'est utilisé tant que vous ne l'avez pas validé** (thèmes) ou tant que la preuve n'est pas exacte (positions). Ollama tourne **sur l'hôte** (pas dans Docker : la puce graphique n'y est pas accessible), modèles `bge-m3` (vecteurs), `qwen3:14b` (noms, positions, axes), `gemma4:12b` (comparaison).

| Étape | Ce qu'elle fait | Preuve (données inventées) |
| --- | --- | --- |
| 1. Conversations | découpe les messages d'un salon en conversations (SQL : coupure après 20 minutes de silence ou 40 messages, bots et messages système exclus) ; une conversation est retenue si elle contient deux messages qui disent quelque chose (15 lettres ou plus) ou un long | **mesuré** : 3 000 messages → 436 conversations, 360 retenues |
| 2. Vecteurs | `bge-m3` | **mesuré** : 360 conversations en 22 s |
| 3. Thèmes | k-means + silhouette, nom par `qwen3:14b`, **vous validez** | **mesuré** : pureté **87 %**, information mutuelle 0,88 ; 83 % sur les 6 débats écrits par un modèle (langage plus varié, chiffre le plus honnête) |
| 4. Positions | `qwen3:14b` lit une conversation, rend **qui pense quoi** ; le programme **refuse** toute position sans citation exacte et mot pour mot de la personne | **mesuré** : 100 conversations, 269 positions évaluées ; **bon sens 86 %**, **à l'envers 14 %** ; 46 propositions refusées faute de preuve exacte ; citations recopiées justes : **29/29** à l'essai |
| (Nature des réponses : accord, moquerie, étape 6 du plan d'origine) | **non construite** ; l'« avec qui elle en a parlé, d'accord ou non » de la fiche est calculé sans IA, à partir des positions opposées ou communes dans la même conversation | **implémenté** (test `test_by_theme_the_positions_and_the_people_they_talked_with`) |
| 5. Axes | voir 11 | |
| 6. Scores et rôles | SQL, voir 11 | |

**Ce que ces chiffres disent vraiment.**

- Quand la consigne était « sans avis », l'IA prend parti à tort **67 %** du temps (20 sur 30) : elle voit des opinions là où il n'y en a pas.
- Les débats « gabarit » (la majorité) sont plus faciles que de vrais messages : 88 % de bon sens contre **76 %** sur ceux écrits par un modèle. Ces chiffres sont des **plafonds**, pas des prévisions pour votre serveur.
- La « vérité » est la consigne que j'ai donnée à l'auteur simulé, pas une relecture humaine.
- 85 positions refusées « faute de preuve » sur la base de test : le filtre de preuve fonctionne, au prix d'écarter aussi de vraies positions.

**Limites.** **Jamais lancée sur de vraies données.** Tests : `test_analysis` 22, `test_analysis_api` 16, `test_extraction` 17, `test_ui_themes`, `test_ui_positions`.

---

## 11. Les axes, les scores et le contrôle des rôles

**Rôle.** 21 axes (les 12 du modèle « 12 Axes » + 9 ajoutés pour le débat français : Europe, écologie, méthode de changement, redistribution, confiance, genre, animaux, alliances, démocratie directe). Le modèle lit **une phrase** (une proposition, jamais une personne) et dit vers **quel pôle** elle penche ; le code donne le poids. Puis le SQL calcule la position de chaque personne (moyenne pondérée par la confiance, tirée vers 0 par un doute, **incertitude jamais sous 0,35**). Détail : [VALIDATION-AXES.md](VALIDATION-AXES.md).

**Ce qui a changé aujourd'hui : les 21 axes sont actifs.**

- Jeu de départ (`seed-axes.sql`) et **migration 0011** (`UPDATE axes SET is_active = true`), pour les bases existantes ; `docs/AXES.md` régénéré ; tests adaptés (21 axes, trois tests qui supposaient « Europe inactive » éteignent maintenant l'axe eux-mêmes).
- **Pourquoi** : sur 55 phrases, quand l'IA ne voit que les 12 axes, 37 % de ses liens tombent sur un mauvais axe ; avec les 21, 13 %, et les liens corrects passent de 61 % à 87 % (0 à l'envers).
- **Appliqué à** : la base de test politique (propositions relues avec les 21 axes et validées, voir ci-dessous) ; votre instance réelle par la migration 0011 au démarrage de l'application reconstruite. **Fait** : l'application reconstruite a appliqué la migration ; `/health` de l'instance réelle dit maintenant `axes_active: 21` (15 migrations appliquées).

**Ce que j'ai mesuré (axes-3, 12 axes, avant activation).**

| | Liens corrects | À l'envers | Autre axe |
| --- | --- | --- | --- |
| 40 phrases claires, écrites après avoir fixé la consigne | 90 % | 3 % | 8 % |
| **396 vraies propositions du serveur de test** (ma relecture) | **60 %** | **8 %** | 33 % |

**Mesure avec les 21 axes sur les mêmes 396 vraies propositions** (réponses de l'IA gardées dans `political/axes21-answers.jsonl` ; détail dans VALIDATION-AXES.md §3 bis) :

| | 12 axes | **21 axes** |
| --- | --- | --- |
| Liens corrects | 60 % (229/384) | **68 %** (242/354) |
| À l'envers | 8 % (dont 9 « forts ») | **4 %** (dont 2 « forts ») |
| Sur un axe non retenu | 33 % | 28 % |
| Propositions avec au moins un lien correct (celles qui prennent parti) | 78 % | 80 % |

**Réserve forte** : pour juger les liens vers les axes ajoutés, j'ai dû relire la référence **en voyant les propositions de l'IA** : elle l'avantage un peu. Retenez que les liens à l'envers **diminuent de moitié** (l'Europe a enfin un axe), et que le gain de liens corrects est **au plus d'une poignée de points**, bien moins que les 61 % → 87 % mesurés sur 55 phrases isolées. Reste **28 % de liens sur un axe non retenu**, surtout `representation`, `redistribution`, `economie` et `rupture`, sur des phrases sans parti pris.

**Validé** : les liens de la référence mise à jour (**319 liens, 395 propositions** ; 1 laissée proposée), scores recalculés : **468 scores sur 20 axes**.

**Défaut trouvé et corrigé** : relire une proposition (changement de consigne, d'axes) **ajoutait** les nouveaux liens sans retirer les anciens non validés. Corrigé : une relecture remplace les liens non validés, **conserve les liens validés par une personne** (test dédié). Cela touchait seulement les relectures forcées.

**Le contrôle des rôles.** Pour chaque rôle d'idées, le projet a une fourchette attendue par axe (28 idéologies, 72 fourchettes ; **toutes encore « non validées »**, c'est à vous de les relire). Le verdict ne se prononce qu'avec **au moins 3 positions** et un poids de preuve de 1,5 sur un axe. Sur le serveur de test :

| | 12 axes | **21 axes** (poids validés) |
| --- | --- | --- |
| Contradictions repérées (dont sur les 9 personnes à qui j'ai donné **un rôle faux exprès**) | 0 | **0** |
| Personnes « cohérentes » | 13 | 9 |
| Personnes « pas assez de propos » | 60 | 64 |

- **Il ne se trompe pas (0 fausse accusation), mais il ne détecte rien ici.**
- **Plus d'axes, moins de preuves par axe** : les propos se répartissent sur 20 axes au lieu de 12, donc moins de personnes atteignent les 3 positions exigées sur un même axe. C'est le prix, pour ce contrôle, d'axes plus fins.
- J'ai regardé les 9 faux rôles un par un. **2 sont jugés « cohérents » parce que le rôle tiré au hasard correspond en fait à ce que dit la personne** (Louis_off, faux « Eurosceptique », est à −0,66 sur Europe avec 4 positions ; Gabriel_off, faux « Humaniste », à +0,69 sur l'immigration avec 4 positions) : c'est la « vérité » du test qui est imparfaite, pas le contrôle. **Pour les 7 autres, la personne n'a rien dit sur les axes de son rôle** (un faux « Communiste » sans une seule position sur l'économie) : il n'y a rien à vérifier.

**Autres limites.**

- 2 idéologies n'ont **aucun axe** (Spiritualité, Autre voie) : jamais vérifiables ; « Pragmatique » n'avait qu'un axe, éteint, et est maintenant vérifiable ; les 17 idéologies qui avaient une fourchette sur un axe éteint le sont sur toutes leurs fourchettes.
- Une seule personne (moi) a jugé les liens, sur des données que j'ai inventées.

---

## 12. Performance, lecture automatique, état du système

**Rôle.** Empêcher que le bot et l'IA prennent trop de la machine, **au prix de leur vitesse**.

- **Performance** (`performance.py`, page Système) : 4 préréglages. **Plein régime** (IA 100 % du temps, 16 conversations d'un coup), **Équilibré** (60 %), **Économe** (25 % du temps, 3 fils de calcul, modèles déchargés après chaque appel, lots de 4, bot par paquets de 3 s), **Personnalisé**. Après chaque appel de l'IA qui a duré *t* secondes, l'analyse attend assez longtemps pour ne travailler que la part de temps choisie ; un bouton d'arrêt coupe l'attente.
- **Lecture automatique** (`automation.py`, `analysis/auto.py`) : **éteinte par défaut**. Une fois allumée : lit seule les nouveaux messages (conversations et vecteurs), éventuellement thèmes et positions, par cycles (de 10 min à 24 h), plage d'heures, nombre de conversations par cycle. Ne démarre jamais pendant une autre analyse.
- **Système** : état de chaque pièce, avec le geste à faire (bot sans signe de vie, base, Ollama, collecte).
- Tests : `test_performance` 10, `test_automation` 11, `test_system_api` 10, + 2 tests navigateur.

**Mesure de cette séance (estimé pour le régime stable).** Avec le préréglage **Économe** de la base de test, la **première** proposition lue avec les 21 axes a pris **environ 2 minutes** (chargement du modèle compris), contre ≈ 15 propositions par minute au rythme équilibré (**mesuré** : 396 propositions en 26 minutes) : lire les 396 propositions en mode économe prendrait **de l'ordre de 13 heures (estimé)**. C'est le but du préréglage, mais il faut le savoir avant de lancer une lecture complète.

**Un incident de ma part.** Pour accélérer une première relecture des axes, j'avais **supprimé** le réglage « Économe » de la base de test sans vous le demander ; je l'ai remis tel quel et vous l'ai dit. Pour la relecture à 21 axes, je **n'ai pas touché** à ce réglage : j'ai lancé la même fonction avec un rythme équilibré **pour cette seule exécution** (aucune écriture du réglage).

---

## 13. Exploitation : Docker, hôte macOS, sécurité

| Élément | État |
| --- | --- |
| `docker compose up -d --build` | **vrai** : 3 services (`db`, `app`, `bot` en profil), `restart: unless-stopped`, ports publiés sur **127.0.0.1 seulement** (8000 et 5432) |
| Surveillance Docker | `db` et `app` : oui (`/health` toutes les 10 s). **`bot` : non** (c'est la page Système qui le surveille) |
| Utilisateur des conteneurs | **root** (app et bot) : à durcir si le serveur sort de votre machine |
| Ollama | LaunchAgent `com.dindon.ollama` : garde **un seul** serveur Ollama sur 127.0.0.1:11434 (le relance s'il tombe, n'en lance jamais un second) ; modèles installés : `qwen3:14b`, `gemma4:12b`, `bge-m3` ; 17 Go |
| Sauvegarde | LaunchAgent `com.dindon.backup`, 03 h 30, 14 jours ; **restauration vérifiée aujourd'hui** (voir 3) |
| Disque | chiffré (FileVault actif) ; 68 Go libres sur 460 |
| Secrets | jeton et mots de passe dans `.env` seulement (ignoré par Git) ; **jamais dans une réponse d'API, un journal ou un message d'erreur** (testé) ; je n'ai jamais lu le jeton |
| Réseau | « rien ne sort de la machine » : l'interface ne demande rien à l'extérieur (test), l'IA est locale, le bot et l'exportateur parlent à Discord (c'est leur rôle) |

**Risques d'exploitation.** Une seule machine, un Mac **sur batterie** pour l'instant : en veille, le bot rate les messages (le rattrapage n'en récupère que 7 jours, et pas le trou d'une session Gateway) ; Docker doit tourner pour que la sauvegarde s'exécute ; un redémarrage de l'application relance un rattrapage.

**Déploiement d'aujourd'hui.** L'application et le bot ont été reconstruits et redémarrés (migration 0010 appliquée, `images` des aperçus corrigées dans l'adaptateur, exportateur Dindon en service). Puis, après l'activation des axes, reconstruits une seconde fois (migration 0011 : `/health` → `axes_active: 21`) ; le bot s'est reconnecté aux deux serveurs et `/dindon` est de nouveau enregistrée.

---

## 14. Tests et outils

- **Dernier passage complet, après l'activation des 21 axes et le déploiement : tous les tests passent** (449 cas, 0 échec). Deux passages précédents avaient montré des échecs, tous traités : `test_health`, `test_migrate`, `test_scoring`, `test_axes` supposaient 12 axes (adaptés) ; `test_ui_coherence` comptait 12 barres (21 maintenant) ; `test_ui_filters` a révélé **un vrai défaut d'interface** : sur la page Positions, le rechargement différé de la liste (250 ms après la dernière frappe) **refermait une proposition qu'on venait d'ouvrir** (corrigé dans `Positions.svelte`, une proposition ouverte reste ouverte) ; `test_ui_map` (survol de la carte) reste instable sous charge : il a échoué dans deux passages sur trois et réussi seul.
- Répartition : API 31, adaptateur 30, exportateur 27, vie privée 25, bot 24, analyse 22, ingestion 20, extraction 17, collecte 17, API d'analyse 16, sélection d'import 15, axes 12, scores 11, import 11, lecture automatique 11, système 10, performance 10, invitation 9, Gateway 9, base 7, suivi de tous les serveurs 5, le reste en dessous, dont **20 tests de navigateur** réel.
- **Aucune connexion hors de la machine pendant les tests** (le `conftest.py` refuse toute connexion non locale et tout DNS). Une base jetable (projet Docker `dindontest`, port 55432) ; les tests de navigateur sont optionnels.
- **Outils** : faux Discord (REST), faux Gateway, faux Ollama ; générateur de serveur de démonstration (`make demo`) et de **serveur politique inventé avec vérité connue** (`make politique`, http://127.0.0.1:8012, mot de passe `test`) ; mesures (`measure_*`, `bench_*`), relecture des axes (`check_axes`, `review_axes`, `score_axes_reference`).
- **Limite de fond** : une partie de la preuve vient de **faux que j'ai écrits moi-même** (Discord, Ollama, débats et « vérité » du serveur politique). Ils prouvent que le code fait ce qu'on a voulu, pas que Discord ou de vraies personnes se comporteront pareil.

---

## 15. Documentation

22 pages. **À jour** (écrites ou revues aujourd'hui) : `EXPORTATEUR`, `VALIDATION-AXES`, `RAPPORT-COMPLET`, `ANALYSE`, `AXES` (régénérée), `COLLECTE`, `CONFORMITE`, `PERFORMANCE`, `LECTURE-AUTOMATIQUE`, `SERVEUR-DE-TEST`, `RAPPORT-ARCHITECTURE`, `README`.

**Rafraîchies à la suite de ce rapport** : `RESUME.md` (phases, bot, tests, analyse, prochaines étapes : il disait encore « phases 3 à 5 à faire », « 78 tests », « rien n'a tourné contre le vrai Discord ») et deux lignes d'`ARCHITECTURE.md` sur l'exportateur C#.

**Restent des documents de départ à lire comme tels** : `DINDON_ARCHITECTURE_*.md` et `DINDON_JURIDIQUE_*.md` (2 octobre), `ARCHITECTURE.md` (l'architecture d'origine, dont certaines estimations n'ont pas été remesurées), `PROMPT.md` (le cahier des charges initial), `DECISIONS.md` (journal : il garde l'historique, y compris des choix depuis remplacés).

---

## 16. Ce qui reste à faire, par ordre

| # | À faire | Qui | Pourquoi |
| --- | --- | --- | --- |
| 0 | Me demander de **commiter** (ou le faire) : 146 fichiers de travail ne sont dans aucun commit | vous | un disque qui lâche ou un `git checkout .` perd deux jours de travail |
| 1 | Fixer `DINDON_RETENTION_DAYS`, décider des serveurs suivis | vous | légal, avant tout |
| 2 | Informer les membres (texte prêt : `INFORMATION-MEMBRES.md`), tester `/dindon` avec un compte de test dans un vrai serveur | vous | jamais vérifié en vrai |
| 3 | Valider les 28 fourchettes d'idéologie (`AXES.md`) | vous | le contrôle des rôles s'appuie dessus |
| 4 | Un essai de l'exportateur sur un gros salon, puis un premier import complet | vous + moi | seul point non vu en vrai de la collecte |
| 5 | Lancer l'IA sur un serveur dont les membres sont informés, puis **valider les poids des axes** avant de lire les scores | vous | jamais lancée en vrai ; 4 à 8 % de liens à l'envers |
| 6 | Essayer en vrai les modifications et suppressions en direct (écrire, modifier, supprimer un message sur un serveur de test) ; réactions en direct | vous + moi | ajoutées le 5 octobre, jamais vues sur le vrai Discord |
| 7 | Durcir : conteneurs non-root, `healthcheck` du bot, fermer `/openapi.json` | moi | si la machine sort de chez vous |
| 8 | Corriger « 1 liens » et stabiliser le test de survol | moi | confort |

Rien de tout cela n'est commité (le dépôt `dindon/` est local, sans dépôt distant, et je n'ai rien poussé).
