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
| Premier import : un fichier par 50 000 messages, 2 salons à la fois, **un export par salon** (pas tout le serveur d'un coup) | permet de reprendre salon par salon et message par message ; `exportguild` ne sait pas sauter ce qui est déjà fait. Moins rapide qu'un seul `exportguild --parallel` : non mesuré |
| Un salon qui échoue : attente de 30 s, doublée à chaque échec, jusqu'à 15 min | ne pas marteler Discord ni boucler sur une erreur permanente |
| Un faux Discord qui répond comme l'API REST (`tools/`) pour tous les tests | « aucun jeton réel dans les tests » |

## Application et interface

| Choix | Pourquoi |
| --- | --- |
| Mot de passe : un cookie signé (HMAC, clé dérivée du mot de passe), `HttpOnly`, `SameSite=Strict`, 7 jours ; 5 essais ratés bloquent 30 s ; l'application **refuse de démarrer sans mot de passe** | aucun paquet de plus ; changer le mot de passe déconnecte tout le monde |
| Politique de sécurité de contenu (CSP) : `default-src 'self'` | **« aucune police ou bibliothèque chargée depuis un CDN »** est une exigence : le navigateur lui-même refuse tout le reste (et il a refusé l'`eval` de l'outil de test, ce qui prouve qu'elle agit) |
| **Pas d'avatars** : les adresses sont stockées, jamais chargées | les afficher enverrait des requêtes aux serveurs d'images de Discord depuis le navigateur |
| `psycopg_pool` (déjà une pièce de psycopg) | les requêtes de l'API tournent dans des threads, une connexion chacun ; sans pool, une connexion par requête |
| Svelte 5 + Vite 8, Sigma.js 3 + graphology (+ ForceAtlas2 dans un worker) | imposés par le prompt. 6 paquets directs (3 pour l'exécution, 3 pour la construction) ; 239 Ko de JavaScript (64 Ko compressés) |
| Image Docker en deux étapes (Node pour construire l'interface, Python pour servir) | l'interface est servie par l'application. (L'ancien exportateur .NET, monté depuis un dossier et dépendant d'ICU, n'existe plus : l'exportateur est du Python de l'application.) |
| **Aucune transparence pour dessiner les liens** : leur couleur est mélangée au fond par le code (`faded()` dans `mapgraph.js`) | Sigma écrit les couleurs sans les multiplier par leur transparence : un trait à 7 % d'opacité s'affiche presque plein (mesuré sur une capture : un trait isolé à 0,5 d'intensité au lieu de 0,07). Des couleurs opaques donnent le même rendu sur toutes les cartes graphiques |
| Les liens sont une toile discrète ; **nets seulement pour la personne survolée ou sélectionnée** | demande de l'utilisateur : la carte reste lisible, et les liens sont là quand on s'intéresse à quelqu'un |
| Étiquettes dessinées avec un halo sombre ; densité adaptée au nombre de personnes (toutes pour 90 personnes ou moins) | le blanc sur gris des étiquettes par défaut était illisible sur les traits ; mesuré visuellement sur 60 et 400 personnes |
| L'interface demande par défaut les **2 500 liens les plus forts** | 20 000 traits superposés donnent une masse blanche ; l'API dit combien sont masqués |
| Les événements en direct n'ajoutent un lien que visuellement ; la carte est rechargée au plus toutes les 8 s | éviter de recharger des milliers de liens à chaque message |
| Un compteur `data-flashes` sur la carte | permet de tester depuis l'extérieur (`tools/check_ui.py`) que le lien s'illumine ; ne contient aucune donnée |
| **Personnes sans lien** (`/api/graph?isolated=true`, case cochée par défaut dans l'interface) : toutes celles qui ont **déjà** écrit dans le serveur et ne sont pas sur la carte, **quelle que soit la période** ; taille minimale ; les robots restent exclus (`bots=true` les ajoute) | demande de l'utilisateur : voir son propre compte sur la carte avec un seul compte. Les personnes reliées passent avant et gardent leurs places ; ces points ne prennent que ce qui reste de `limit` (les plus bavards d'abord), et `isolated_hidden` dit combien manquent. Leurs chiffres (messages, dernier message) sont ceux de toute leur activité, pas de la période. Par défaut l'API ne change pas |
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
| Ce que le bot écrit **n'est pas un import d'historique** : la surveillance (« premier import fait ») et `dindon backfill` (« reprendre après le message le plus récent connu ») l'ignorent (`GATEWAY_SOURCE`, `_known(exported_only=True)`) | trouvé à la revue : sans cela, un bot lancé avant le premier import faisait croire à `backfill` que l'historique antérieur à son premier message était là, et il n'était jamais importé. Testé |

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
| Un message que l'adaptateur ou l'ingestion refuse est **isolé**, abandonné et compté, **mais seulement si c'est sa faute** (forme inattendue, donnée refusée par la base). Une base absente, pas encore migrée ou verrouillée fait **attendre** | un message étrange ne doit pas bloquer son salon pour toujours ; mais trouvé à la revue : une base pas encore migrée (le bot démarré avant l'application) faisait abandonner tous les messages. Testé avec une vraie base vide |
| Modifications, suppressions, réactions : reçues, **comptées, non appliquées** | *(décision du 3 octobre, remplacée le 5 octobre : modifications et suppressions sont maintenant appliquées en direct, voir « Le bot applique les modifications et suppressions »)* |
| Erreur qui ne se règle pas en attendant (jeton refusé, intent absent) : message clair, puis **une heure de silence** avant que le conteneur ne redémarre | redémarrer toutes les secondes serait refusé à chaque fois et compté contre le bot |
| Autre échec de la bibliothèque : nouvelle session, délais jusqu'à 5 minutes | reste très en dessous des 1 000 sessions par jour de Discord, même si l'échec revient à chaque démarrage |
| Processus et service `bot` séparés, même image, profil Compose `bot`, dépend de l'application saine | décision validée : redémarrer l'interface ne coupe pas la session Discord ; l'application applique les migrations, le bot jamais |
| `DINDON_COLLECTOR=off` coupe la surveillance | pour essayer le bot seul : les deux apportent les mêmes messages (sans danger) mais la surveillance masquerait le bot |
| Tests : `conftest.py` redirige discord.py vers un port local fermé, **et refuse toute connexion ou résolution de nom hors de cette machine** (un test qui essaie échoue, même si le code testé avale l'erreur) | un `discord.Client` ordinaire démarre toujours sur l'adresse réelle de Discord ; la redirection seule reposait sur des attributs internes de la bibliothèque, rien n'interdisait vraiment une connexion sortante |
| `events.py` : `GatewayEvent` et `FatalGatewayError` sont à part ; le moteur n'importe discord.py que dans `serve()` | trouvé à la revue : le moteur importait `gateway.py`, donc discord.py, malgré l'isolation annoncée. Un test lance l'import dans un processus propre et vérifie que `discord` n'y est pas |
| `compare_with_export` ne compare **que** ce que le bot a écrit et que personne n'a réécrit depuis | après un rattrapage ou un export, la ligne est celle de l'exportateur : la comparer dirait « identique » quoi que le bot ait écrit |
| Limite connue : `exportedAt` du bot est l'heure du message (horloge de Discord), celui de l'exportateur l'heure de la machine | une machine dont l'horloge retarde (VM Docker après une veille) peut faire ignorer, pour les métadonnées, un export fait dans les secondes qui suivent un message ; le rattrapage suivant le rapporte. Non corrigé : pas de problème concret observé |

# Import d'une partie du serveur (salons, personnes, période)

Testé avec un faux Discord ; l'expression de filtre a été vérifiée contre l'analyseur du vrai exportateur, sans connexion.

| Choix | Pourquoi |
| --- | --- |
| Les salons sont choisis **par nom ou par identifiant** ; les personnes **par identifiant seulement** | le nom d'une personne change, son identifiant non (règle du projet) ; le nom d'un salon est lisible et se vérifie tout de suite contre la liste de Discord (erreur claire avec les salons visibles) |
| Un import restreint par personnes ou par période est **partiel** (`ingest_runs.is_partial`, migration 0002) | trouvé en concevant : « reprendre après le message le plus récent connu » et « le premier import est fait » supposent qu'un import ramène tout jusque-là. Un import filtré ne le fait pas : sans la marque, il cacherait l'historique à un import complet ultérieur (même défaut que celui du bot). Choisir des salons seulement n'est pas partiel : ils sont complets |
| Un import partiel **n'avance pas** `_exported_up_to` et ne reprend pas « après le dernier connu » | sinon la surveillance croirait le salon à jour ; une fenêtre ou un filtre se refait en entier (c'est sans danger : l'ingestion ne duplique rien) |
| Les dates sont des **jours UTC, premier et dernier inclus**, transformés en identifiants de messages pour `--after` / `--before` | pas d'ambiguïté de fuseau ni de format de date, et c'est ce que montre un champ de date |
| `from:` pour les auteurs, `mentions:` pour les mentions, « ou » dans un groupe, « et » entre groupes | la syntaxe de l'exportateur (`.docs/Message-filters.md`), vérifiée contre son analyseur : une expression valide passe, une fausse est refusée |
| Un import lancé depuis l'interface est **une tâche de l'application**, un seul à la fois, avec progression et annulation | un import long ne doit pas dépendre d'un onglet ouvert ; deux imports en même temps se disputeraient le même verrou et les mêmes requêtes. L'annulation arrête l'exportateur (`Popen`, plus `subprocess.run`) |
| Une sélection fausse est **refusée avant de démarrer**, avec des mots (liste des salons visibles, identifiant invalide…) | l'erreur ne doit pas arriver après dix minutes d'attente |
| Seuls les serveurs de `DINDON_GUILD_IDS` peuvent être importés ; aucune réponse ne contient le jeton ni un message ; une erreur inattendue est montrée par son **type seulement** | moindre privilège ; le texte d'une exception pourrait en dire trop |
| Un salon sauté à cause d'une annulation est signalé comme les autres | trouvé par un test : l'écran aurait compté « 2 annulés » au lieu de 3 |
| Le formulaire exige au moins un salon choisi | un clic ne doit pas lancer par accident l'import de tout le serveur (la ligne de commande, elle, importe tout sans option) |

## Habillage de l'interface (même style que Poulet)

Demandé : refaire le visuel sur celui de Poulet (`poulet/dashboard-next`), « exactement le même style ». Seul l'habillage a changé : les routes, l'API, les données et le comportement de la carte sont les mêmes. Implémenté ; vérifié par captures dans Chromium (démo sans Discord) et par mesure des boîtes contre le vrai CSS de Poulet (voir plus bas) ; les deux tests de navigateur passent.

| Choix | Pourquoi |
| --- | --- |
| Les **jetons** de `web/src/app.css` sont copiés de `app/globals.css` de Poulet, sous les mêmes noms (`--bg-primary`, `--accent`, `--border-subtle`…), ainsi que les primitives de `ui.module.css` et `Stats.module.css` | pouvoir comparer les deux applications ligne à ligne, et que la prochaine retouche de Poulet se reporte sans traduction |
| La **barre de gauche** (`Navbar.svelte`) reprend `Navbar.module.css` classe pour classe : choix du serveur, entrées, carte de session, tiroir sur téléphone | c'est la structure de Poulet ; il n'y a qu'une page (« Carte ») et une action (« Importer »), rien n'a été inventé pour remplir la barre |
| Le texte **Session / accès local** remplace le profil Discord de Poulet | Dindon n'a pas de compte Discord : une session par mot de passe. Le bouton de sortie est celui de Poulet |
| La **police Inter** est servie par l'application (`@fontsource/inter`, `web/src/fonts.css`, quatre graisses, latin et latin étendu) au lieu de Google Fonts | la politique de sécurité (`default-src 'self'`) interdit toute police venue d'ailleurs, et rien ne doit sortir de la machine. Les noms dans d'autres alphabets retombent sur la police du système |
| Les filtres sont dans une **barre au-dessus de la carte** (`FilterBar.svelte`, comme la barre de filtres de la page Chat de Poulet) ; les types d'échanges sont des pastilles qui s'estompent quand elles sont masquées (comme les séries du graphique d'activité) | même grammaire visuelle ; une rangée de boutons bleus pleins quand tout est actif était trop lourde |
| **Couleurs de la carte** : fond `--bg-primary`, points bleu Discord du clair (message récent) au sombre (ancien), liens gris clair, liens de la personne choisie bleu clair, éclair jaune Discord pour un nouvel échange | la carte est dessinée en WebGL/canvas : ses couleurs ne peuvent pas lire les variables CSS, elles sont en haut de `lib/mapgraph.js` avec leur origine |
| L'entrée « Importer… » devient **« Importer »** (les entrées de Poulet n'ont pas de points de suspension) ; les deux tests de navigateur et la doc suivent | cohérence |

Ce qui est **mesuré** : les boîtes de la barre de gauche (largeur 232, sélecteur 207 × 56,5, entrée 44 de haut, carte de session 59,5, bouton de sortie 34 × 34, polices et couleurs) sont identiques à celles que donne le CSS réel de Poulet chargé dans une page de référence. **Non fait** : comparaison avec Poulet en fonctionnement (il faut son OAuth Discord) ; le rendu de la page de connexion est lu dans son CSS, pas comparé à une capture. Les captures sont faites avec une démo inventée, pas avec de vraies données.

### Carte : couleurs de Discord, survol, échelle

Demandé : surligner le pseudo et le point au survol ; un point de la couleur de la personne sur Discord ; que le zoom de 80 % du navigateur devienne le 100 %.

| Choix | Pourquoi |
| --- | --- |
| `/api/graph` renvoie `color` (`#RRGGBB` ou `null`) pour chaque point : la couleur du **plus haut rôle de la personne qui a une couleur**, sauf les rôles classés `age` ou `genre` (`MEMBER_COLORS` dans `api/routes.py`) | c'est la règle de Discord pour la couleur d'un pseudo. La donnée existait déjà (`members.color`, `roles.color`, remplis par l'export et par le bot) : ni migration ni nouvelle collecte. Les rôles d'âge et de genre ne sortent jamais de l'API (règle du projet) : leur couleur aurait dit la même chose, donc elle est ignorée et le rôle coloré suivant compte |
| Sans rôle colorié (ou sans aucun rôle connu et sans couleur d'export) : `null`, et la page dessine **la couleur par défaut du pseudo dans Discord** (`#DBDEE1`) | c'est ce que Discord montre |
| Seul le format `#RRGGBB` sort de l'API, et la page ne lit que lui ; `#000000` (« pas de couleur » pour Discord) devient `null` | le texte vient d'un fichier d'export : il ne doit jamais atteindre le dessin tel quel |
| Une couleur trop sombre pour le fond (contraste inférieur à 2) est **éclaircie** juste ce qu'il faut | un rôle noir ou bleu nuit donnerait un point invisible. Seules ces couleurs sont modifiées |
| La couleur ne dit plus « activité récente / ancienne » (légende changée) | une seule information par canal visuel : la couleur est celle de Discord. La récence reste lisible par les liens et la fiche ; on peut la remettre autrement (opacité, anneau) si elle manque |
| Au survol, le point reçoit une **lueur de sa couleur**, un anneau blanc et un léger agrandissement, et le pseudo passe dans une **pastille bleue à lettres blanches** ; le survol est **toujours** allumé, même quand quelqu'un est sélectionné | trouvé en reproduisant : avec une personne sélectionnée, survoler un autre point ne montrait ni pseudo ni surbrillance (tout le reste est assombri). Les liens affichés restent ceux de la personne sélectionnée |
| Le **nom** d'une personne se survole et se clique comme son point : `MapGraph` retient où chaque nom a été dessiné (`labelBoxes`, rempli par le dessin des noms) et teste la souris dessus ; le point passe avant le nom, et le survol est gardé tant que la souris reste sur le nom ou sur la pastille qui s'ouvre. La pastille est collée au point | signalé : « quand je survole le pseudo, il ne s'affiche pas plus clairement ». Seul le point était une zone de survol (Sigma ne sait pas survoler un texte). Testé dans un navigateur en demandant à la carte où elle a dessiné les noms (`tests/test_ui_map.py`) ; l'aspect est vu sur capture |
| `html { font-size: 80 % }` et **toutes les tailles en `rem`** (sauf les traits de 1 px) ; la carte lit ce facteur (`UI` dans `lib/mapgraph.js`) pour ses points, ses traits et ses noms. Les seuils d'écran passent de 900/760/560 px à 720/608/448 px | c'est exactement ce que fait un zoom de navigateur de 80 %, mais sans que la personne ait à le régler, et sans la fragilité de la propriété CSS `zoom` (coordonnées de la souris fausses pour le dessin WebGL). Un seul réglage change tout : la valeur de `html` |
| La démo (`make_demo_server.py`) colorie les rôles d'idéologie avec la palette de Discord, et chaque personne prend la couleur de son plus haut rôle coloré | sans cela, la démo ne montrait aucune couleur |

État : couleur de l'API **implémentée, testée avec données simulées** (trois tests : plus haut rôle, rôle d'âge ignoré — le test échoue sans la protection —, valeur qui n'est pas une couleur) ; **jamais vue sur de vraies données Discord**. Survol et échelle : **implémentés, vus sur captures** dans Chromium contre la démo ; pas de test automatique (le dessin est un canvas).

### Inviter le bot depuis l'interface

Demandé : « pouvoir inviter le bot sur des serveurs Discord depuis l'interface ». Implémenté : `GET /api/bot/invite` (`api/invite.py`), la fenêtre « Inviter le bot » (`InvitePanel.svelte`, sur la `Modal.svelte` que partage désormais la fenêtre d'import). **Testé avec un faux Discord** (9 tests d'API, 1 test de navigateur) ; **jamais sur le vrai Discord**.

| Choix | Pourquoi |
| --- | --- |
| Un **lien d'invitation** (`discord.com/oauth2/authorize?client_id=…&scope=bot&permissions=66560`), ouvert dans un autre onglet (`noopener`) ; pas d'ajout automatique | c'est la seule voie de Discord : c'est la personne qui choisit le serveur et accepte, avec sa permission « Gérer le serveur ». La page ne fait aucune requête vers Discord |
| Permissions **voir les salons + lire l'historique des messages**, rien d'autre (le bot n'écrit pas, ne modère rien) | moindre privilège : le Gateway n'a besoin que de voir les salons, et l'exportateur de lire l'historique. L'intent privilégié « Message Content » se règle dans le portail développeur, pas dans le lien |
| L'identifiant de l'application est demandé à Discord (`/oauth2/applications/@me`) avec le jeton déjà configuré | rien de plus à configurer ; le jeton n'est jamais renvoyé (testé), le lien ne contient que l'identifiant public de l'application. Avec un jeton de compte : pas de lien, message clair |
| La fenêtre liste les **serveurs où le bot est** (`/users/@me/guilds`), chacun **suivi** (dans `DINDON_GUILD_IDS`) ou **non suivi**, se rafraîchit au retour sur l'onglet, et dit si l'application n'est pas publique (« Public Bot » désactivé : seul son propriétaire peut l'ajouter) | on voit tout de suite le serveur qu'on vient d'ajouter, et pourquoi rien n'arrive |
| Le **sélecteur de serveur** (en haut à gauche) est **toujours un menu** : les serveurs de la base, puis « Ajouter un autre serveur… » (ouvre la fenêtre d'invitation) et une phrase qui dit pourquoi il n'y en a pas d'autre. Il n'était une carte fixe que s'il n'y avait qu'un serveur | signalé : « je ne peux pas changer de serveur ». Constat : la base n'en contenait qu'un, et le sélecteur ne liste que les serveurs **suivis dont des messages sont arrivés** (`/api/guilds`), pas ceux où le bot est seulement présent. Une carte fixe ressemblait à un bouton cassé. Le changement de serveur lui-même est testé avec deux serveurs en base (`tests/test_ui_servers.py`) |
| **Inviter n'enregistre rien** : un serveur n'est suivi que s'il est dans `DINDON_GUILD_IDS`, modifié à la main dans `.env` puis conteneurs recréés ; la fenêtre le dit, avec l'identifiant à copier et la commande | le bot ne suit jamais « tous » les serveurs (règle de départ). Rendre cette liste modifiable depuis l'interface touche au consentement : un serveur suivi voit **tous** ses messages enregistrés. Il faut décider avant (consentement, effacement durable : P4), puis ce sera une liste en base lue par le bot sans redémarrage. La fenêtre rappelle de n'inviter que là où les personnes sont informées |

## L'analyse locale (étapes 1 à 3 de la cascade)

Demandé : « installer tout et mettre en place un système réel pour l'objectif donné ». Fait pour les trois premières étapes de la cascade ([ANALYSE.md](ANALYSE.md)) ; l'extraction de ce que chaque personne affirme **n'est pas faite** et dépend de choses qui ne viennent que de vous (axes relus, jeu d'exemples, consentement : voir « Ce qui n'est pas fait »). **Testé avec un faux Ollama** (44 tests) ; **mesuré avec les vrais modèles sur des données inventées** (voir [MESURES.md](MESURES.md)) ; **jamais lancé sur un vrai serveur**.

| Choix | Pourquoi |
| --- | --- |
| Ollama **natif sur le Mac** (application officielle, `brew install --cask ollama-app`), joint par `host.docker.internal` ; pas dans Docker | Docker ne peut pas utiliser le GPU du Mac. La formule `brew install ollama` a échoué ici sur un conflit de lien d'une dépendance (`ca-certificates`) déjà installée : l'application n'a pas ce défaut et n'a pas de dépendances |
| Modèles : **`bge-m3`** (vecteurs), **`qwen3:14b`** (noms), `gemma4:12b` comparé ; réglables par `DINDON_EMBED_MODEL` / `DINDON_NAMING_MODEL` | `bge-m3` : multilingue, 1024 nombres, ce que le schéma attendait déjà. Pour les noms, comparaison mesurée : `qwen3:14b` est plus rapide (6,2 s contre 9,4 s) et plus précis ; `gemma4:12b` plus concis mais plus générique. `qwen3.6` (17 Go minimum) est trop gros pour 24 Go avec Docker. Le choix repose sur des données inventées |
| Le client d'Ollama est du **`urllib`** (comme celui de Discord) ; **`numpy`** est la seule dépendance ajoutée | un appel HTTP ne justifie pas une bibliothèque ; regrouper des vecteurs de 1024 nombres en Python pur serait trop lent (problème concret, pas une habitude) |
| Les **conversations** sont faites en **une requête SQL** (coupure après 20 min de silence et tous les 40 messages, robots écartés, attente tant qu'elle peut continuer), jamais défaites, et relancer ne fait que le nouveau | idempotence : un message est dans une conversation au plus ; la base décide, pas un programme. Les valeurs (20, 40) sont celles du plan de départ |
| Le **tri** est un seuil sur le nombre de lettres (15) après retrait des liens, emoji et mentions ; une conversation est retenue avec deux messages qui disent quelque chose, ou un d'au moins 300 lettres | simple, vérifiable, réglable. Rien n'est supprimé |
| Les **thèmes** sont cherchés **sans les noms des personnes** (mentions et liens retirés du texte), regroupés par k-moyennes sphériques, le nombre étant choisi par la silhouette ; un groupe de moins de 3 conversations est du bruit | le plan veut des thèmes découverts « sans tenir compte des personnes ». Le nombre de thèmes n'est pas net (les scores se tiennent de 9 à 25) : `--topics` le fixe |
| Un thème est une **proposition** : validé, renommé, fusionné ou rejeté **par la personne** ; une nouvelle recherche ne remplace que les propositions | le code ne valide jamais seul (même règle que pour les axes) |
| Un nom que le modèle ne sait pas donner (deux essais) est **remplacé par les mots caractéristiques**, et ce n'est pas compté comme nommé par le modèle | une panne du modèle ne doit pas bloquer la recherche ni passer pour un succès |
| L'analyse est **une tâche de l'application** (une à la fois, progression, annulation), comme l'import ; les erreurs sont dites par leur sens ou par leur type, jamais par leur texte | un travail de plusieurs minutes ne doit pas dépendre d'un onglet ouvert |
| **Rien d'automatique** : l'analyse ne démarre que sur demande (bouton ou `dindon analyze`) | personne n'a décidé d'analyser un serveur réel ; et un serveur inconnu de la base est refusé, pas traité à vide |
| Les extraits montrés pour valider un thème sont des **vrais morceaux de messages**, sans mentions ni liens | on ne peut pas valider un thème sans le lire. La page n'est visible qu'avec le mot de passe ; elle est à ne pas partager |

## Exploitation à distance (audit du 3 octobre 2026)

Demandé : l'ordinateur n'est pas accessible, il faut que tout soit opérationnel à distance, vérifier l'architecture, l'IA, l'enchaînement et l'interface, et corriger les défauts. **Constaté** (lu sur la machine, pas supposé) puis **corrigé**. Testé avec données simulées ; la chaîne d'analyse a de plus été lancée **dans l'image de production**, sur une base jetable de données inventées, avec le vrai Ollama (318 conversations, 243 vecteurs en 20 s, 19 thèmes nommés par le modèle en 3 min 10 s).

| Constaté | Décision |
| --- | --- |
| `.env` avait **deux lignes `DINDON_GUILD_IDS` différentes** (premier serveur, puis second ajouté en nouvelle ligne). Docker lit la dernière, le lecteur de `.env` de Dindon la première : l'application suivait le second serveur et le bot le premier | une seule ligne, les deux identifiants séparés par une virgule (c'était l'intention : le second serveur avait été ajouté pour être suivi) ; la règle est écrite dans `.env.example` et la doc. Le bot et l'application ont été recréés : ils suivent tous deux les deux serveurs |
| Le bot a changé de session **13 fois en 12 heures** (50 déconnexions) ; avec `DINDON_COLLECTOR=off` **rien ne comble ces trous**, ni n'applique modifications et suppressions | nouveau réglage **`DINDON_COLLECTOR=catchup`** : seulement le rattrapage nocturne, sans interroger Discord à longueur de journée (`on` et `off` ne changent pas). Mis dans `.env`. Test : il ne relève pas Discord et comble un trou du bot |
| Rien ne **sauvegardait** la base (aucune sauvegarde n'avait jamais été faite) | `tools/host/backup.sh` + tâche `launchd` à 03 h 30, 14 jours gardés, dans `~/Library/Application Support/Dindon/backups/` (pas dans le dépôt, pas sur le Bureau : `launchd` n'y a pas accès). **Restauration vérifiée** dans une base jetable : mêmes chiffres que la vraie (454 messages, 13 personnes, 7 migrations) |
| Ollama lancé à la main ne survit pas à un redémarrage | `tools/host/run-ollama.sh` sous `launchd` : surveille le port, ne lance pas de deuxième serveur si un tourne déjà, reprend la main s'il disparaît. **Vérifié** : serveur tué, revenu en 8 s |
| Le Mac est **sur batterie** (68 %, 9 h 47 restantes) | à signaler, pas à régler à distance : le brancher, couvercle ouvert (écran jamais éteint, donc pas de veille) |
| Le bot ne dit son état que dans ses journaux | il écrit toutes les 30 s un signe de vie (`service_status`, migration 0004 : compteurs et identifiants de serveurs, jamais un message) ; l'API `/api/system` et la page **Système** disent connecté / déconnecté / ne répond plus, et ce qui mérite un coup d'œil, avec le geste à faire (bot jamais vu, reconnexions sans rattrapage, serveur suivi que le bot ne voit pas, Ollama absent ou modèle manquant, fichiers illisibles…) |
| Interface : la **recherche** ne se faisait qu'à la souris ; les fenêtres ne prenaient pas le focus, **Tab en sortait** et le focus se perdait à la fermeture ; Échap ne fermait pas la fiche | flèches, Entrée et Échap dans la recherche ; fenêtre avec focus à l'ouverture, Tab gardé dedans, focus rendu à la fermeture ; Échap ferme la fiche. Chaque comportement a un test de navigateur, qui a d'ailleurs trouvé un défaut de ma première version (Échap rouvrait la liste) |
| Interface : un filtre de type d'échange ou de période ne s'appliquait qu'**après jusqu'à 8 s** (limite pensée pour le direct), et sans aucun type choisi la carte restait inchangée sans rien dire | les choix de la personne s'appliquent aussitôt (120 ms) ; le direct garde sa limite. Sans type choisi : la carte est vidée et la page le dit |
| Page Thèmes sans serveur importé : une erreur **en anglais** de l'API | message clair, pas de bouton qui ne peut pas marcher ; les messages d'erreur affichés (serveur inconnu, jeton, accès refusé…) sont passés en français |
| Un identifiant de serveur qui n'est pas un nombre faisait une **erreur 500** à l'analyse | refusé (422) |
| Les vecteurs étaient lus dans une liste Python de 1024 nombres par ligne (dix fois la mémoire) | lus directement dans un tableau : tient à 15 000 conversations |
| Avertissements `PyNaCl`/`davey` (voix) à chaque démarrage du bot | filtrés : Dindon ne lit que du texte, l'avertissement inquiétait pour rien |

**Revue de code du 3 octobre (dix constats, vérifiés dans le code, tous corrigés, chacun avec un test)**

| Constat | Correction |
| --- | --- |
| Fusionner un thème dans une **proposition** puis relancer l'analyse supprimait la cible : le thème fusionné devenait invisible | une proposition qui a reçu une fusion, ou que la personne a touchée, n'est plus jamais remplacée (`topics.touched_at`, migration 0005) |
| Un thème **renommé** mais encore « proposé » était écrasé à la recherche suivante | idem : agir sur un thème le rend à vous |
| Les noms de **plusieurs mots** après « @ » (« @Jean Dupont ») laissaient « Dupont » dans le texte envoyé au modèle et dans les extraits | les noms des personnes mentionnées sont retirés en entier |
| Le mode `catchup` ne nettoyait jamais son erreur, ne remplissait jamais « premier import à faire » et ne connaissait pas le type de jeton | erreur effacée quand le salon refonctionne ; type de jeton et état du premier import connus sans rien demander à Discord |
| Le signe de vie du bot échouait **sans rien dire** (la page l'aurait dit « jamais vu » alors qu'il tourne) | un avertissement, une seule fois, et un message quand cela remarche |
| La couleur d'un point pouvait venir de la couleur d'**export** d'un membre sans rôle connu (donc d'un rôle d'âge) et un rôle noir cachait un vrai rôle coloré | la couleur ne vient plus que des rôles classables ; le noir n'est pas une couleur |
| La recherche de thèmes gardait **tous les textes** en mémoire (600 Mo pour 100 000 conversations) | lecture par paquets de 500, seuls les extraits typiques sont gardés |
| Les mises à jour d'un thème (fusion, rejet) étaient plusieurs requêtes **sans transaction** | une transaction chacune |
| `/api/system` comptait tous les messages à chaque rafraîchissement (la page le demande toutes les 10 s) et attendait Ollama 5 s | estimation du planificateur au-delà de 100 000 messages (affichée « ≈ »), comptes limités aux serveurs suivis, attente d'Ollama limitée à 2 s |
| Un modèle de vecteurs d'une autre taille donnait « erreur inattendue (ValueError) » | message clair : quel modèle, quelle taille, quoi choisir |

**Pas fait, à décider**

- **Combler automatiquement les trous du bot au moment de la reconnexion** (au lieu d'attendre la nuit) : c'est la reprise de session de la priorité P3 ; le rattrapage nocturne couvre l'essentiel en attendant.
- **Un bouton « Suivre ce serveur »** : une liste de serveurs suivis en base, lue par le bot sans redémarrage, avec confirmation de consentement. Aujourd'hui : `.env` puis recréer les conteneurs.
- Le Mac qui s'éteint, se met en veille ou n'a plus de batterie arrête tout : aucun réglage logiciel ne le remplace.

## Suivre tout serveur où le bot est (sans identifiant dans `.env`)

Demandé : ne plus avoir à écrire l'identifiant du serveur dans `.env`. Cela **remplace la règle de départ** (« le bot ne suit jamais tous les serveurs ») : être invité devient la décision, prise par la personne qui a le droit « Gérer le serveur ». `DINDON_GUILD_IDS` vide ou `all` = tous les serveurs où le bot est ; une liste reste possible et limite. Testé avec un faux Discord.

| Choix | Pourquoi |
| --- | --- |
| Seulement avec un **jeton de bot** | un compte personnel est dans tous les serveurs de la personne : « tout suivre » enregistrerait tout ce qu'elle lit |
| L'application demande la liste à Discord (`/users/@me/guilds`), gardée une minute ; si Discord ne répond pas, la dernière réponse sert | importer, rattraper, la page Système et l'invitation lisent la même liste (`Settings.followed()`) |
| La fenêtre d'invitation dit que **inviter suffit** et rappelle de n'inviter que là où les personnes sont informées | c'est ce que fait ce réglage : l'enregistrement commence à l'invitation |
| `.env` est passé à `DINDON_GUILD_IDS=all` | les deux serveurs déjà suivis le restent, tout nouveau serveur le sera |

**Pour limiter de nouveau** : remettre une liste d'identifiants sur une ligne, puis `docker compose --profile bot up -d`.

## Ce qui n'est pas fait, et pourquoi

| Reste à faire | Où |
| --- | --- |
| **L'effacement doit empêcher le retour** : `forget_user()` supprime une personne, mais un export ultérieur (le rattrapage nocturne, un fichier déposé) la réimporterait. Il faudra une liste de personnes oubliées que l'ingestion respecte | phase 5 |
| Mode pseudonymisé : tous les noms passent par une seule expression (`LABEL` dans `api/routes.py`) pour que ce soit un changement à un seul endroit | phase 5 |
| Communautés (couleur des points), frise de rejeu | phase 5 |
| **Extraction de ce que chaque personne affirme**, normalisation, relations, scores alimentés par l'IA | à décider avec vous : il faut d'abord relire les axes ([AXES.md](AXES.md)), un jeu d'exemples relus par vous pour **mesurer** l'extraction, et le consentement et l'effacement durable ([ANALYSE.md](ANALYSE.md) §8) |
| Les vecteurs et les thèmes ne sont pas purgés par `forget_user()` (ils dérivent de messages de plusieurs personnes) | avec l'effacement durable (P4) |
| Lecture d'un fichier JSON ligne par ligne (la mémoire vaut environ 10 fois la taille du fichier) | à voir si un cas réel le demande |
| Rien n'a tourné contre le **vrai Discord** | dès qu'un jeton et un serveur sont donnés |


## L'exportateur de Dindon (4 octobre 2026)

| Décision | Pourquoi |
| --- | --- |
| **Écrire notre exportateur en Python, dans Dindon** (`app/dindon/export/`), et supprimer DiscordChatExporter (binaire et source) | ne plus dépendre du code d'un autre (C#, écrit pour d'autres besoins, non optimisé pour ce que Dindon en fait) ; une seule technologie dans l'image (plus de .NET ni de `libicu`) ; moins de coût à l'exécution et à la maintenance |
| **Même JSON v2, même adaptateur que le bot** | un message s'écrit pareil qu'il arrive par le Gateway ou par l'exportateur ; la base et l'analyse ne changent pas ; l'adaptateur sait maintenant aussi écrire aperçus, sondages, messages transférés et réactions |
| **Seulement ce que Dindon utilise** : profils demandés pour qui a écrit, a été mentionné ou a reçu une réponse (pas pour qui n'a fait que réagir) ; qui a réagi seulement pour les messages récents par défaut ; pas d'émojis Unicode du texte | la requête par réaction et par profil est le poste le plus cher d'un export ; ce qui n'est pas utilisé n'est pas demandé |
| **Respecter les limites de Discord avant de les atteindre** (seaux, plafond global, attente plutôt que refus) | un refus a une pénalité ; attendre est moins cher |
| **Des fichiers, comme avant** (`inbox/`, `archive/`) | l'archive brute des exports est une fonction de Dindon ; le relevé, le premier import, le rattrapage et la fenêtre « Importer » ne changent pas |
| **Vérifié en lecture seule sur le vrai Discord avant tout autre usage** : 474 messages comparés à ce que l'ancien exportateur avait écrit | le rattrapage nocturne peut supprimer des messages absents d'un export (garde-fou à 30 %) : un exportateur faux serait dangereux ; l'essai n'écrit rien dans la base |


## Nettoyage et refonte du code (5 octobre 2026)

Objectif : un code plus simple à lire et à modifier, **sans changer ce qu'il fait** (toute la suite de tests sert de filet : elle passait avant, elle passe après). Règles écrites dans [CONVENTIONS.md](CONVENTIONS.md) ; `make lint` (ruff) ne doit rien signaler.

| Changement | Pourquoi |
| --- | --- |
| **`ruff` ajouté et réglé** (`pyproject.toml`, `make lint`) ; 160 corrections mécaniques : imports inutiles, `datetime.UTC`, annotations modernes… | un style vérifié par une machine ne dépend plus de la mémoire de chacun |
| **`clock.py`** : `utc_now()` / `utc_iso()` au lieu de 25 `datetime.now(...)` et de deux `_now()` privés | un seul endroit, remplaçable par un test |
| **`locks.py`** : tous les verrous de la base au même endroit. **Défaut trouvé** : le verrou de l'ingestion et celui de la construction des conversations avaient le même numéro (7 262 025) par hasard ; le comportement (ils s'attendent, ce qui protège aussi l'effacement d'une personne) est conservé, mais dit et testé (`tests/test_locks.py`) | deux nombres égaux sont le même verrou : on ne les choisit pas à deux endroits |
| **`api/main.py` découpé** (session, santé, direct, en-têtes, interface) et **`api/background.py`** (les tâches de fond) ; `api/common.py` pour ce qui sert à plusieurs routeurs (`LABEL`, `iso`, `resolve_guild` : quatre copies d'`_iso` et des fonctions privées importées d'un fichier à l'autre) | `create_app` faisait 20 branches ; un routeur n'importe plus les détails d'un autre |
| **`api/system.py`** : une fonction par sorte de vérification (`_bot_checks`, `_collector_checks`, `_ollama_checks`) | `checks_for` faisait 19 branches |
| **`bot/adapter.py`** : `_reactions_entry`, `_reference_entry`, `_with_icon` ; **`export/exporter.py`** : `_kept_in_page`, `_ask_for_extras` | `_message_entry` (20) et `_export_one` (17) |
| **`__main__.py`** : un parseur, une fonction par commande, un tableau `COMMANDS` | `main()` faisait 16 branches |
| **`analysis/axes.py`** : plus de fermeture sur une variable de boucle (`functools.partial`) ; `zip(strict=True)` ; `contextlib.suppress` pour les échecs sans importance | ce que `ruff` signale comme des bugs probables |
| **Interface** : `lib/format.js` (`day`, `ago`, `plural`) et `makeGuard` dans `lib/api.js` | les mêmes fonctions étaient copiées dans 2 à 4 composants |

**Défauts corrigés** (chacun avec un test) : le rattrapage nocturne **se refaisait à chaque redémarrage** de l'application (le jour du dernier rattrapage vit désormais en base, `runtime_settings`) ; « 1 liens » ; les compteurs de la page Cohérence mélangeaient personnes et rôles (ils s'additionnent maintenant au nombre de personnes) ; `/openapi.json` lisible sans session ; un test de survol de la carte instable sous charge (il attend maintenant que la carte soit stable et relit la position du nom avant chaque geste).

**Durcissement** : les conteneurs `app` et `bot` **ne tournent plus en root** (utilisateur `dindon`, un entrypoint répare les droits de `/data` puis abandonne ses privilèges) ; le conteneur du bot a un **contrôle de santé Docker** (`dindon bot-health` : signe de vie récent et connecté à Discord).

**Fichiers supprimés** : `tools/load_export.py` (le « chargeur de référence » du kit de départ, doublon non testé de l'ingestion réelle, plus référencé nulle part), `tools/peek_stance.py` (expérience remplacée par l'étape « positions »), et dans `political/` les journaux, marqueurs et résultats intermédiaires (décisions provisoires, candidats du jeu de référence, rapports de consignes périmées, une copie du prompt qui est maintenant dans le code).

**Pas fait, volontairement** : redécouper `bot/runner.py`, `ingest/loader.py` ou les composants Svelte de plus de 600 lignes (ils sont couverts par des tests mais le gain est faible pour le risque) ; réécrire le SQL de `schema-analysis.sql`.


## Le bot applique les modifications et suppressions ; ce qui est déduit d'un message part avec lui (5 octobre 2026)

| Décision | Pourquoi |
| --- | --- |
| **Une suppression efface aussi ce qui en a été déduit** : les conversations qui contiennent le message (donc leurs vecteurs, leurs positions avec leurs citations, leur rattachement aux thèmes) et les scores que ces positions faisaient | **défaut trouvé** : le rattrapage nocturne supprimait le message mais **gardait** la position déduite et le score ; une personne qui retire un message s'attend à ce que ce qu'il disait disparaisse. La conversation est refaite sans lui à la prochaine analyse |
| **Une modification qui change le texte fait la même chose** (pas une modification d'épinglage, de réaction ou d'aperçu) | les positions reposaient sur l'ancien texte |
| **Suppressions en direct** (`MESSAGE_DELETE`, `MESSAGE_DELETE_BULK`) et **modifications en direct** (`MESSAGE_UPDATE` avec auteur et texte) appliquées par le moteur du bot, avec reprise si la base est indisponible ; un message supprimé avant d'être écrit n'est jamais écrit | ces événements arrivent déjà avec l'intention « messages des serveurs » (aucune permission de plus) |
| **Les liens de la carte sont recalculés par différence** pour une suppression, comme pour un import | pas de recalcul complet (1,5 s pour 500 000 messages) à chaque suppression |
| **Un tour du relevé après une coupure ou un redémarrage du bot** (mode `catchup`), au plus un toutes les 10 minutes | combler « le trou après une reconnexion » sans attendre la nuit ; il ne fait jamais un premier import (c'est `backfill` qui décide) |
| **Réactions toujours au rattrapage nocturne** | il faudrait l'intention « réactions » et une écriture à part pour les liens qu'elles font : peu de valeur pour le coût |


## Plus de « contact » ; `/dindon info` explique la gestion des données ; `/dindon card` (5 octobre 2026)

| Décision | Pourquoi |
| --- | --- |
| **`DINDON_CONTACT` supprimé** (réglage, bandeau de la page Vie privée, contrôle `dindon preflight`) | demande du propriétaire : ce n'est pas utile ici |
| **`/dindon info` dit comment les données sont gérées** : ce qui est gardé, où et combien de temps (la durée de `DINDON_RETENTION_DAYS`, ou « sans limite »), à quoi cela sert (carte, sujets, IA locale), ce qui se passe quand on modifie ou supprime un message, les sauvegardes (14 jours), les droits | c'est le texte que les membres lisent |
| **`/dindon card @pseudo`** poste dans le salon une **carte** (embed) : activité, depuis quand, salons, personnes avec qui elle échange le plus, rôles d'idées qu'elle s'est donnés, et, si l'analyse a lu ses messages, jusqu'à 3 axes où ses propos penchent nettement (« lecture automatique, pas un verdict ») | demande du propriétaire ; la carte est **publique dans le salon**, c'est son but |
| Pas de carte pour une personne qui a demandé à ne pas être enregistrée, un bot, ou quelqu'un jamais vu ; les personnes arrêtées n'apparaissent pas non plus dans « échange surtout avec » | le registre de vie privée passe avant tout |
| **Attention** : les axes sont des opinions déduites (art. 9 du RGPD) et la carte les montre à tout le salon. À n'utiliser qu'avec des membres informés | `INFORMATION-MEMBRES.md` le dit |


## Bot expulsé d'un serveur : effacement si on l'a demandé (5 octobre 2026)

| Décision | Pourquoi |
| --- | --- |
| Réglage **`DINDON_ERASE_ON_REMOVAL=true`** (dans `.env`, **éteint par défaut**) : quand le bot est retiré d'un serveur (expulsé, banni, parti, serveur supprimé), tout ce que Dindon garde de ce serveur est effacé aussitôt : messages, salons, membres, liens, scores, conversations, thèmes, affirmations, personnes vues nulle part ailleurs, propositions orphelines, fichiers d'export de ce serveur | demande du propriétaire ; éteint par défaut parce que c'est irréversible |
| Une **panne de Discord** (`unavailable`) n'est pas un retrait : rien n'est effacé | sinon une panne effacerait tout |
| Le **registre des personnes non enregistrées reste** | c'est une promesse faite aux personnes, pas une donnée du serveur |
| **`dindon forget-server <id>`** fait la même chose à la main (pour un serveur quitté avant d'activer le réglage) | |
| Si l'effacement échoue, le journal du bot le dit et donne cette commande ; il n'est pas retenté tout seul | |
| Limite : un message déjà en cours d'écriture à l'instant exact du retrait pourrait recréer une trace ; `dindon forget-server` la retire | |


## La carte en 4 pages (5 octobre 2026)

| Décision | Pourquoi |
| --- | --- |
| `/dindon card` poste une carte colorée en **4 pages** (Profil, Interactions, Positions, Contradictions), des **boutons** changent de page sur le même message | demande du propriétaire |
| Chaque position et chaque contradiction porte sa **preuve** : un extrait (110 caractères) et le lien du message | une lecture sans preuve ne se vérifie pas |
| Contradictions = rôle d'idée contre propos (axes « incompatibles »), deux rôles qui s'opposent, revirements (autre camp plus tard sur la même proposition) | ce que la vue de cohérence calcule déjà |
| Tout le monde peut tourner les pages ; la personne est relue à chaque clic : si elle s'est retirée entre-temps, la carte disparaît au clic suivant | la carte est publique, mais le registre de vie privée passe avant |
| **Risque connu** : l'extrait d'un message d'un salon privé est lisible de tout le salon où la carte est postée (Dindon ne connaît pas les droits de lecture des salons) | à décider : garder, ou ne montrer que le lien |

## 2026-10-05 : le bot écrit (débats)

| Choix | Pourquoi |
| --- | --- |
| Le lien d'invitation passe de 2 à **6 permissions** : voir les salons, lire l'historique (comme avant) + créer des fils publics, envoyer des messages, envoyer des messages dans les fils, intégrer des liens. Cela remplace la ligne « le bot n'écrit pas » de la section de l'invitation | `/dindon debat` ouvre un fil et y écrit ; rien de plus n'est demandé (ni gérer les messages, ni gérer les fils, ni mentions) |
| Tout message du bot interdit les mentions (`allowed_mentions: {parse: []}`) | un sujet ou un pseudo contenant `@everyone` ne prévient personne |
| Boutons à emojis plutôt que vraies réactions | un clic = un choix modifiable, pas d'intent de plus, pas le cas « deux réactions contradictoires » |
| Les messages d'un débat (fil ou salon) sont comptés pour le débat **et** vont à la carte comme les autres | les personnes sont informées par `/dindon info` ; `/dindon stop` les exclut des deux |
| Le préflight dit (niveau « info », pas bloquant) si le bot peut ouvrir des débats | un bot invité avant ce changement enregistre toujours : seuls les débats manquent |
| Le moteur du bot a un « tick » de 2 s tant qu'un débat tourne, dans une tâche à part | une réponse lente de Discord ne doit jamais retarder les événements du Gateway |

## 2026-10-06 : les débats vérifient sur Internet (D4 à D6)

| Choix | Pourquoi |
| --- | --- |
| La vérification se fait **sur Internet** (et non avec une base de faits locale) | demande du propriétaire ; remplace la décision du 2026-10-05 |
| **Trois principes** : vérifier sans chercher plus ; impartialité (la vérité vraie quand elle est établissable) ; rien d'autre ne sort de la machine | demande du propriétaire ; imposés par la structure du code (`debate/scope.py`, `tests/test_outbound.py`, lecture à l'aveugle) |
| Un verdict « confirmé » ou « contredit » exige **une source officielle ou une rédaction de vérification ET une citation copiée mot pour mot que le programme retrouve sur la page** ; les pages d'autres sources ne sont **jamais lues** | un modèle peut inventer une phrase, pas que la page la dise ; une page hostile n'a rien sur quoi agir |
| Désactivée par défaut ; **mode observation** (rien n'est publié) avant les corrections publiques | on ne publie rien avant d'avoir mesuré |
| `live` (corrections publiques) **exige une précision mesurée** donnée par le propriétaire (`DINDON_DEBATE_PRECISION` ≥ seuil 0,90) ; sinon le bot reste en observation et le dit | verrou : la précision de « contredit » est le chiffre qui décide si Dindon peut parler en public |
| Correction publique **seulement pour « contredit »**, même message pour tous, sans nom, sans mention, avec **boutons-liens** vers les sources ; **retirée** si le message est modifié ou supprimé ou la personne effacée | demandé : sources cliquables ; impartialité ; une correction ne doit pas survivre à ce qu'elle cite |
| « Message phare » = le plus commenté et le plus apprécié (réponses ×3 + réactions), sans modèle | un critère objectif, identique pour tous, plutôt qu'un jugement de Dindon |
| Le message de fin attend la lecture des messages restants, cinq minutes au plus | des statistiques complètes |
| Les liens écrits par les membres **ne sont pas ouverts** ; les affirmations sur une personne privée ne sont **pas** vérifiées en ligne | rien d'autre ne sort ; pas de profilage de particuliers |

## 2026-10-06 : le débat libre (D7)

Sur demande du propriétaire : « un fil seulement si on le demande, enlève la limite de temps, une popup pour choisir les paramètres, puis Dindon fait un message et analyse tous les messages ». Réponses aux questions : fin = « bouton + fin si personne n'écrit » ; fil = « optionnel (case dans la fenêtre) » ; champs = « sujet et contexte », « vérification des affirmations », « temps ».

| Choix | Pourquoi |
| --- | --- |
| `/dindon debat sujet` **ne crée rien** : il montre une fenêtre ; le débat s'écrit quand elle est envoyée | les limites (une personne, trois par serveur, un débat par salon) sont revérifiées à l'envoi, car elles ont pu changer entre-temps |
| **« Temps » lu comme le silence** après lequel le débat se termine seul (1 h, 6 h, 24 h par défaut, 3 j, 7 j) | plus de limite de temps ; la réponse libre était un seul mot : **à corriger si ce n'était pas cela** |
| Plus de minuteur, de période, de vote, de table `debate_votes` (migration 0018) | demandé ; rien de réel n'avait tourné sur ces tables |
| Fil facultatif ; sinon **le débat a lieu dans le salon, où Dindon lit tous les messages** tant qu'il est ouvert ; un seul débat « dans le salon » par salon | demandé ; deux débats compteraient les mêmes messages ; **le message de lancement avertit en gras** |
| Le lieu d'un débat n'est plus unique à vie, seulement parmi les débats **non terminés** (index unique partiel) | un salon héberge des débats l'un après l'autre |
| Seuls la personne qui a lancé le débat et les **modérateurs** (droits lus dans l'interaction) peuvent le terminer ; les messages des dernières secondes sont comptés avant la fin | éviter qu'un inconnu mette fin à un débat ; ne rien perdre |
| La case « Vérifier » ne peut que **désactiver** la vérification pour ce débat, jamais aller au-delà du réglage du propriétaire ; un débat non vérifié ne lit, ne note et ne corrige rien | les trois principes tiennent : le propriétaire décide de ce qui sort |
| Un message qui a attendu plus d'une heure n'est plus lu (il reste compté) | dans un salon actif, ne jamais corriger bien après la conversation |
| Le texte validé de la notice change d'un mot : « dans les fils de débat » → « dans les débats » | un débat peut avoir lieu dans un salon ; **à confirmer par le propriétaire** |

## 2026-10-06 : un axe au lieu d'un sujet (D8)

Sur demande du propriétaire : « si on ne sait pas quoi choisir comme débat, qu'on puisse sélectionner une catégorie/axe et qu'il y ait une question posée par Dindon (reprendre les axes déjà inscrits et les mettre en liste sur la fenêtre) ».

| Choix | Pourquoi |
| --- | --- |
| La liste de la fenêtre reprend les axes actifs de la table `axes` (au plus 25) ; la question posée est `axes.question` | « reprendre les axes déjà inscrits » ; ces questions sont déjà écrites et relues (`docs/AXES.md`) |
| **On répond avec les deux pôles de l'axe** (🔵 pôle −1, 🟠 pôle +1, « Ne sait pas »), pas avec pour / contre | **choix de ma part, à confirmer** : « faut-il privilégier l'ordre ou la liberté ? » n'a pas de « pour » ; les boutons gardent les mêmes identifiants (`for`, `unsure`, `against`), seuls les mots changent |
| Jamais ✅ / ❌ sur les pôles | impartialité : une coche dirait qu'un pôle est le bon |
| `/dindon debat` : le sujet devient facultatif ; un sujet écrit gagne sur l'axe | sinon on ne pourrait pas lancer la commande sans savoir quoi débattre |
| Les cases « fil » et « vérification » se regroupent dans une rubrique « Options du débat » (groupe de cases) ; chaque case est facultative | une fenêtre tient 5 champs et l'axe en prend un ; la documentation de Discord dit qu'une case est **obligatoire par défaut** : sans `required: false`, une case décochée aurait pu empêcher d'envoyer (défaut de ma première version, corrigé) |
| Le débat garde une copie des mots de l'axe (`debates.axis`) | renommer ou éteindre un axe ne change pas un débat en cours |

## 2026-10-06 : le forum des débats, et Dindon qui répond d'abord (D9, D10)

Sur demande du propriétaire (captures d'écran de son serveur : un forum « Débats » dont chaque post porte des étiquettes) : « pouvoir dire à Dindon que le fil doit être placé ici, pour éviter de polluer le salon » ; « la création de fil doit être cochée de base » ; « Dindon n'intervient pas ; s'il peut répondre sans Internet qu'il le fasse, avec Valide / Invalide dessous ; plus de Valide : il s'arrête, plus d'Invalide : il approfondit sur Internet ».

| Choix | Pourquoi |
| --- | --- |
| Le forum se règle **une fois par serveur**, par un modérateur (`/dindon forum`), et non dans la fenêtre | une fenêtre ne tient que 5 champs (vérifié dans la documentation de Discord) et elle est pleine ; « dire à Dindon que le fil doit être placé ici » est un réglage de serveur. La case « fil » (cochée par défaut) place alors le débat dans le forum |
| Un débat dans le forum est un **post** créé en un appel (post + message de lancement), avec les **étiquettes** : celle choisie par le modérateur, plus celles dont tout le nom est fait de mots du nom de l'axe ; jamais une étiquette réservée aux modérateurs de lui-même | les posts de votre serveur portent des étiquettes ; deviner davantage serait risqué |
| Forum en panne, supprimé ou étiquette introuvable : le débat s'ouvre dans un fil sous le salon et la personne est prévenue | un débat ne doit pas être perdu pour un réglage |
| La case « Ouvrir un fil » est **cochée par défaut** | demandé ; et c'est le choix qui lit le moins : un fil ne fait lire que ceux qui y viennent |
| Nouveau niveau `answer` entre `observe` et `live` ; `live` sans précision mesurée retombe sur `answer` (et non plus sur `observe`) | « Dindon n'intervient pas » : la cause était `off` ; `answer` est le niveau où il parle, sous le contrôle des participants |
| « Sous son message » lu comme « sous **le message de Dindon** » : les participants jugent **sa réponse** | à confirmer : l'autre lecture (juger le message de la personne) donnerait les mêmes boutons sous chaque message de la conversation |
| Dindon répond d'abord avec son **IA locale sans Internet**, seulement quand il est **certain** que l'affirmation est **fausse** ; il se tait sinon, et ne dit jamais « vrai » en public | demandé ; se taire est le côté sûr |
| Sa réponse est **publique sans passer par le verrou de précision mesurée**, étiquetée « sans source, elle peut se tromper » | **décision de ma part, à confirmer** : le verrou garde sa fonction (corrections automatiques par des sources) ; pour les réponses locales ce sont le jugement des participants et l'étiquette qui protègent |
| L'IA locale **ne répond pas** quand l'affirmation compare un chiffre à un seuil, quand sa certitude déclarée est sous 90, ou quand sa « correction » garde les chiffres de l'affirmation | mesuré : sans cela, 2 « faux » sur 11 étaient à tort sur des affirmations vraies (docs/DEBAT.md) |
| **Plus d'Invalide que de Valide, strictement**, et à tout moment : une recherche, une seule ; égalité ou plus de Valide : jamais | la règle demandée, sans seuil minimum de votants (un seul vote Invalide contre zéro suffit) : à confirmer |
| Le résultat de la recherche **réécrit le message de Dindon**, quel qu'il soit, y compris « ma réponse était fausse » | être honnête sur ses propres erreurs est ce qui rend les boutons crédibles |
| Les votes sont gardés par personne (retirés à l'effacement, exportés, jamais comptés pour quelqu'un qui a demandé l'arrêt) | vie privée ; migration 0020 : 2 tables de plus (52) |
| Le texte aux membres est écrit pour chaque niveau | **à valider par le propriétaire** |

## `/dindon map` : la carte en image sur Discord (6 octobre 2026)

| Décision | Pourquoi |
|---|---|
| `/dindon map [periode] [personne]` poste une **image PNG** (Pillow, police Inter embarquée) avec un menu de périodes ; `periode` est une liste fermée (7 / 30 / 90 jours / tout), `personne` le sélecteur de membres de Discord : rien n'est tapé librement | demande du propriétaire : une commande guidée, où l'on ne peut pas demander n'importe quoi |
| **Éteinte par défaut**, réglée par les administrateurs depuis la page Système (panneau « Carte sur Discord ») : nombre de personnes, de noms, types d'échanges | la carte est publique dans le salon ; ce qu'elle montre est une décision de l'administrateur |
| Les personnes de `privacy_subjects` (stop ou effacement) et les bots n'y sont jamais ; demander leur carte répond « rien à montrer », sans dire qu'elles existent | même règle que `/dindon card` |
| Centrée sur une personne : ses liens les plus forts et ceux entre ces personnes, pas plus | une question sur quelqu'un ne doit pas montrer le reste du serveur |
| **Pas d'Activité Discord (version interactive en salon vocal) pour l'instant** | elle demande une URL publique en HTTPS, une authentification Discord OAuth2 et un endpoint de lecture réservé aux membres, séparé du mot de passe de l'interface ; à faire avec l'URL de production |

Niveau de preuve : **simulé** (membres inventés, vraie base PostgreSQL, faux Discord REST). Jamais lancé sur un vrai serveur.

