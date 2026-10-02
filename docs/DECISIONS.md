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

# Phase 1 : la carte des échanges, sans IA

## Ingestion

| Choix | Pourquoi |
| --- | --- |
| Un fichier = une transaction ; les lignes passent par `COPY` dans des tables temporaires, puis du SQL ensemble les applique | version par lots du chargeur de référence : 500 000 messages en 26,5 s. Une interruption ne laisse rien ([MESURES.md](MESURES.md)) |
| **Les liens du graphe sont mis à jour par la différence** entre ce que la base savait des messages du fichier et ce que le fichier dit | exact même si un message est modifié, si un export arrive en retard ou chevauche un autre. `rebuild_edges()` recalcule la même chose depuis zéro ; les tests vérifient que les deux donnent le même résultat |
| Poids d'un lien = somme de 0,5^(âge / demi-vie), **stocké « à la date du dernier échange »** | permet d'ajouter un échange sans relire les autres ; l'âge jusqu'à maintenant se calcule à la lecture. Demi-vie : 90 jours, réglage `edge_half_life_days` (migration 0001, pas dans le fichier du kit) |
| Pas de lien d'une personne vers elle-même ; les robots sont dans la table `edges` mais **absents de la carte** par défaut | un lien à soi-même n'est pas un échange ; garder les robots permet de les afficher plus tard sans tout recalculer |
| Une réaction compte à la date du message, pas à celle de la réaction | l'export ne donne pas la date des réactions |
| **Un export plus ancien que ce que la base sait n'écrase rien** (message, pseudo, rôles, nom du salon) | l'ordre dans lequel les fichiers arrivent ne doit pas changer le résultat (testé dans les deux ordres) |
| **Ce qui manque ne sert pas à effacer** : un compte qui a quitté le serveur n'a plus ni pseudo ni rôles dans l'export ; on garde ceux qu'on connaît | sinon un message cité plus tard efface les rôles d'un ancien membre, justement ceux qui servent à la vérification |
| Suppressions : seulement par un **réexport complet d'une fenêtre** (le rattrapage nocturne), jamais par un fichier déposé à la main ; et pas si plus de 30 % de la fenêtre (50 messages au moins) semble manquer | un export manuel peut être filtré. Un export défectueux ne doit pas vider la base |
| Une tâche d'analyse (`conversations`) par salon modifié, sans doublon | les tâches s'accumulent sans consommateur jusqu'à la phase 2 : une seule ligne par salon reste raisonnable |
| Pièce jointe déjà connue sous un autre message : ignorée (`ON CONFLICT DO NOTHING`) | un échec bloquerait le fichier entier pour un détail |
| Un message dont l'auteur manque dans la liste `users` du fichier **fait échouer le fichier** (erreur claire, fichier mis de côté dans `inbox/failed/`) | le contrat dit que tout le monde y figure ; mieux vaut un échec visible qu'une personne « inconnue » créée en douce |
| Un lien de la carte = une paire de personnes, tous types confondus ; poids : réponse 1, mention 0,6, réaction 0,25 | une réponse est une conversation, une réaction un signe de tête. Chiffres à ajuster (constante `KIND_FACTOR` de l'API) ; le détail par type est envoyé aussi |
| Texte des messages : celui que l'exportateur met en forme par défaut (mentions en noms, sans balisage) | meilleur pour l'analyse que le texte brut ; je n'ai pas passé `--markdown false` |

## Collecte

| Choix | Pourquoi |
| --- | --- |
| **Rien n'est exporté avant un premier import explicite** (`dindon backfill`) | démarrer la surveillance sur un gros serveur ne doit pas lancer des milliers de requêtes par surprise, avec un compte qui risque d'être fermé |
| Un salon créé après le premier import est exporté en entier ; un ancien salon absent du premier import est laissé à `backfill` | le premier cas est petit et sûr ; le second est probablement un accès refusé |
| Les fils : détectés un par un avec un **bot** (une requête les liste) ; avec un **compte**, exportés avec leur salon parent et par le rattrapage nocturne | un compte ne peut pas les lister d'un coup (le code de l'exportateur le dit) : une recherche par salon coûterait trop de requêtes toutes les 30 s |
| Le jeton passe par l'environnement du sous-processus, jamais par la ligne de commande ; il est effacé des messages d'erreur | `ps` montre la ligne de commande |
| Type de jeton deviné comme l'exportateur (compte, puis bot) ; **bandeau d'avertissement dans l'interface** pour un compte | exigence du prompt |
| Intervalle de relevé par défaut : 30 s (`DINDON_POLL_SECONDS`) | bas de la fourchette du prompt (30 à 60 s). Délai moyen d'affichage : la moitié de l'intervalle |
| Premier import : un fichier par 50 000 messages, 2 salons à la fois, **un processus exportateur par salon** (pas `exportguild`) | permet de reprendre salon par salon et message par message ; `exportguild` ne sait pas sauter ce qui est déjà fait. Moins rapide qu'un seul `exportguild --parallel` : non mesuré |
| Un salon qui échoue : attente de 30 s, doublée à chaque échec, jusqu'à 15 min | ne pas marteler Discord ni boucler sur une erreur permanente |
| Un faux Discord et un faux exportateur (`tools/`) pour tous les tests | « aucun jeton réel dans les tests » |

## Application et interface

| Choix | Pourquoi |
| --- | --- |
| Mot de passe : un cookie signé (HMAC, clé dérivée du mot de passe), `HttpOnly`, `SameSite=Strict`, 7 jours ; 5 essais ratés bloquent 30 s ; l'application **refuse de démarrer sans mot de passe** | aucun paquet de plus ; changer le mot de passe déconnecte tout le monde |
| Politique de sécurité de contenu (CSP) : `default-src 'self'` | **« aucune police ou bibliothèque chargée depuis un CDN »** est une exigence : le navigateur lui-même refuse tout le reste (et il a refusé l'`eval` de l'outil de test, ce qui prouve qu'elle agit) |
| **Pas d'avatars** : les adresses sont stockées, jamais chargées | les afficher enverrait des requêtes aux serveurs d'images de Discord depuis le navigateur |
| `psycopg_pool` (déjà une pièce de psycopg) | les requêtes de l'API tournent dans des threads, une connexion chacun ; sans pool, une connexion par requête |
| Svelte 5 + Vite 8, Sigma.js 3 + graphology (+ ForceAtlas2 dans un worker) | imposés par le prompt. 6 paquets directs (3 pour l'exécution, 3 pour la construction) ; 239 Ko de JavaScript (64 Ko compressés) |
| Image Docker en deux étapes (Node pour construire l'interface, Python pour servir) ; la bibliothèque ICU est ajoutée pour l'exportateur | l'interface est servie par l'application ; l'exportateur (.NET) ne démarre pas sans ICU. Le binaire est monté depuis `exporter/bin/`, pas copié dans l'image : il doit correspondre à l'architecture du conteneur |
| **Aucune transparence pour dessiner les liens** : leur couleur est mélangée au fond par le code (`faded()` dans `mapgraph.js`) | Sigma écrit les couleurs sans les multiplier par leur transparence : un trait à 7 % d'opacité s'affiche presque plein (mesuré sur une capture : un trait isolé à 0,5 d'intensité au lieu de 0,07). Des couleurs opaques donnent le même rendu sur toutes les cartes graphiques |
| Les liens sont une toile discrète ; **nets seulement pour la personne survolée ou sélectionnée** | demande de l'utilisateur : la carte reste lisible, et les liens sont là quand on s'intéresse à quelqu'un |
| Étiquettes dessinées avec un halo sombre ; densité adaptée au nombre de personnes (toutes pour 90 personnes ou moins) | le blanc sur gris des étiquettes par défaut était illisible sur les traits ; mesuré visuellement sur 60 et 400 personnes |
| L'interface demande par défaut les **2 500 liens les plus forts** | 20 000 traits superposés donnent une masse blanche ; l'API dit combien sont masqués |
| Les événements en direct n'ajoutent un lien que visuellement ; la carte est rechargée au plus toutes les 8 s | éviter de recharger des milliers de liens à chaque message |
| Un compteur `data-flashes` sur la carte | permet de tester depuis l'extérieur (`tools/check_ui.py`) que le lien s'illumine ; ne contient aucune donnée |
| Les rôles d'âge et de genre ne sortent **nulle part** de l'API (seuls les rôles d'idéologie, présentés comme « non vérifiés ») | exigence du prompt ; un test le vérifie sur toutes les fiches |

# Bot en direct (mode C, étapes 1 à 3 du plan de reprise)

Rien de ce qui suit n'a tourné contre le vrai Discord : tout est testé avec un faux Gateway (`tools/fake_gateway.py`).

## Ingestion partagée

| Choix | Pourquoi |
| --- | --- |
| `ingest_document(conn, document, nom, sha256)` extrait de `ingest_file` : **une seule ingestion** pour un fichier et pour un document construit en mémoire | le bot n'a pas sa propre écriture en base ; les imports à la main, la surveillance et le bot convergent |
| Option `only_new` : un message que la base a déjà n'est **pas touché** | une annonce « nouveau message » ne sait rien des réactions ou modifications que la base a apprises par ailleurs (rattrapage, exportateur). Importée comme un instantané, elle les effacerait : un événement rejoué après une reconnexion détruirait les réactions et les liens qui vont avec. Testé : sans l'option, le test « annonce tardive » échoue |
| `consume` : l'import vide `messages` du document au fur et à mesure (gros fichiers) ; sans lui, le document reste intact | un nouvel essai après une panne de base doit pouvoir renvoyer **le même document**. Le comportement économe en mémoire de `ingest_file` est conservé |
| Le bot s'inscrit dans le registre des imports sous le nom `gateway`, avec l'empreinte du document | le même lot reçu deux fois est reconnu et ignoré, sans même une ligne de plus dans le registre |

## Adaptateur (`app/dindon/bot/adapter.py`)

| Choix | Pourquoi |
| --- | --- |
| Fonction pure : des dictionnaires en entrée, un document JSON v2 en sortie ; ni discord.py, ni base, ni horloge | testable avec des charges utiles enregistrées ; le cœur de Dindon reste indépendant de la bibliothèque |
| Reproduit le formatage de l'exportateur (noms de types, texte brut avec mentions en noms, émojis personnalisés, dates, phrases des messages système, couleur et rôles des membres, avatars) | un message doit être identique qu'il vienne du bot ou d'un export, sinon le rattrapage nocturne réécrirait ce que le bot a écrit et l'analyse lirait deux « dialectes ». **Écart au principe « Dindon ne réécrit pas la lecture de Discord »** : voir RESUME.md. Les valeurs attendues des tests viennent de la **lecture** du code C#, pas de son exécution ; la preuve est `tools/compare_with_export.py` sur un vrai serveur |
| `exportedAt` du document = heure du message le plus récent (pas l'heure de l'appel) | le même lot donne toujours le même document et la même empreinte ; une annonce tardive ne peut jamais paraître plus récente qu'un export ultérieur |
| Un salon, un serveur ou un rôle inconnu : **rien n'est inventé**, le message est sauté et compté | un nom fabriqué écraserait le vrai (`ON CONFLICT … DO UPDATE` du salon) ; le rattrapage rapporte le message |
| Dates écrites dans le texte (`<t:…>`) : UTC, culture invariante | l'exportateur utilise la culture et le fuseau de la machine ; dans un conteneur c'est l'invariant et UTC. Parité exacte impossible sur une autre machine |
| Pas couverts : aperçus de liens, sondages, messages transférés, émojis Unicode du texte, résultat d'un sondage détaillé | le rattrapage les ajoute ; les omettre est sans danger, les inventer ne l'est pas |

## Connexion (`gateway.py`, `runner.py`)

| Choix | Pourquoi |
| --- | --- |
| **discord.py**, isolé dans un seul fichier, utilisé pour la connexion seulement (battement de cœur, reprise, reconnexion, débit) ; les trames brutes arrivent par `on_socket_raw_receive` et sortent en dictionnaires | décision validée ; ses modèles et ses caches ne sortent pas du fichier ; une autre bibliothèque pourrait le remplacer |
| Intents : serveurs, messages, **contenu des messages**. Pas de membres, présences, réactions | le minimum ; « Message Content » est « privilégié » : le propriétaire du bot l'active dans le portail. Vérifié par un test : l'IDENTIFY envoyé demande exactement ces trois |
| Aucun cache de messages ni de membres | mémoire constante ; le contenu n'est conservé nulle part ailleurs qu'en base |
| Les trames de débogage de discord.py (qui contiennent les messages) sont **filtrées de force** | même en DEBUG, ni le jeton ni un texte de message ne sort dans un journal (testé avec tous les journaux à DEBUG) |
| Le bot ne suit **que** `DINDON_GUILD_IDS` (liste obligatoire, jamais « tous ») ; messages privés ignorés | moindre privilège ; le bot refuse de démarrer sans liste |
| Lots de 300 ms par salon (100 messages au plus par document) | un document coûte environ 80 ms sous un verrou global (mesuré, voir MESURES.md) : une rafale ne doit pas devenir une rafale de documents |
| Base indisponible : le lot attend et est réessayé (1, 2, 5, 15, 60 s) ; au-delà de 5 000 messages, les nouveaux sont abandonnés et comptés | réessayer est sans danger (voir `only_new`) ; la mémoire reste bornée ; le rattrapage rapporte ce qui manque |
| Un message que l'adaptateur ou l'ingestion refuse est **isolé**, abandonné et compté | un message étrange ne doit pas bloquer son salon pour toujours |
| Modifications, suppressions, réactions : reçues, **comptées, non appliquées** | décision du plan : étape P3. Tant que ce n'est pas fait, un message supprimé reste en base jusqu'au rattrapage nocturne |
| Erreur qui ne se règle pas en attendant (jeton refusé, intent absent) : message clair, puis **une heure de silence** avant que le conteneur ne redémarre | redémarrer toutes les secondes serait refusé à chaque fois et compté contre le bot |
| Autre échec de la bibliothèque : nouvelle session, délais jusqu'à 5 minutes | reste très en dessous des 1 000 sessions par jour de Discord, même si l'échec revient à chaque démarrage |
| Processus et service `bot` séparés, même image, profil Compose `bot`, dépend de l'application saine | décision validée : redémarrer l'interface ne coupe pas la session Discord ; l'application applique les migrations, le bot jamais |
| `DINDON_COLLECTOR=off` coupe la surveillance | pour essayer le bot seul : les deux apportent les mêmes messages (sans danger) mais la surveillance masquerait le bot |
| Tests : `conftest.py` redirige discord.py vers un port local fermé | un `discord.Client` ordinaire démarre toujours sur l'adresse réelle de Discord ; aucun test ne doit pouvoir l'atteindre |

## Ce qui n'est pas fait, et pourquoi

| Reste à faire | Où |
| --- | --- |
| **L'effacement doit empêcher le retour** : `forget_user()` supprime une personne, mais un export ultérieur (le rattrapage nocturne, un fichier déposé) la réimporterait. Il faudra une liste de personnes oubliées que l'ingestion respecte | phase 5 |
| Mode pseudonymisé : tous les noms passent par une seule expression (`LABEL` dans `api/routes.py`) pour que ce soit un changement à un seul endroit | phase 5 |
| Communautés (couleur des points), frise de rejeu | phase 5 |
| Lecture d'un fichier JSON ligne par ligne (la mémoire vaut environ 10 fois la taille du fichier) | à voir si un cas réel le demande |
| Rien n'a tourné contre le **vrai Discord** | dès qu'un jeton et un serveur sont donnés |
