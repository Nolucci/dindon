# Dindon

Une carte vivante d'un serveur Discord : qui parle à qui, de quoi, avec quelles idées, et les preuves de chaque position. **Tout reste en local** : aucun service extérieur, hors Discord lui-même.

> **État : phase 1 (la carte des échanges, sans IA).** Les messages arrivent (exports déposés dans `inbox/`, ou surveillance de Discord), les liens entre personnes se mettent à jour, et la carte s'affiche et s'anime en direct. Pas encore d'analyse des idées, de classement ni de vérification par les rôles : voir la [feuille de route](docs/ARCHITECTURE.md#11-feuille-de-route). **Rien n'a encore tourné contre le vrai Discord** (pas de jeton) : tout est testé avec un faux Discord ([docs/COLLECTE.md](docs/COLLECTE.md)).

## Lire avant de s'en servir

- **Données sensibles.** Ce projet traite les messages de personnes identifiables, dont leurs **opinions politiques**. Le serveur compte des **mineurs**. Un usage strictement personnel est hors du champ du RGPD ; **ce n'est plus le cas dès que les fiches sont montrées à d'autres**. Ne partagez ni la base, ni les fiches, ni les cartes. Chiffrez le disque de la machine.
- **Conditions d'utilisation de Discord.** Automatiser un **compte personnel** (jeton utilisateur) est interdit par Discord et peut le faire fermer. La surveillance continue (phase 1) doit utiliser un **bot** ; avec un compte, c'est à vos risques.
- **Classements = hypothèses.** Une position n'existe que si elle cite des messages ; elle s'affiche avec son nombre de preuves et son incertitude, jamais comme un fait. « Discordant » est une alerte à regarder, pas une accusation. L'âge et le genre ne sont jamais analysés ni affichés.
- **Rien de réel dans le dépôt.** Les exports, archives, sauvegardes, fichiers `.env` et jetons sont ignorés par Git ; les tests n'utilisent que des données inventées.

## Essayer tout de suite, sans Discord

```console
make setup && make web      # Python et Node.js
make demo                   # puis http://127.0.0.1:8011, mot de passe : demo
```

Un faux Discord (60 personnes inventées) répond comme le vrai, le premier import se fait avec `dindon backfill`, puis les personnes continuent à parler : on voit les liens s'illuminer. `make check-ui` vérifie la page dans un vrai navigateur.

## Lire la carte

Un point par personne, une ligne par paire de personnes qui se parlent. La case **Personnes sans lien** (cochée au départ) ajoute aussi, comme de petits points sans trait, toutes celles qui ont déjà écrit mais n'ont aucun lien affiché, quelle que soit la période choisie ; cliquer un tel point ouvre sa fiche. Les **noms** sont affichés avec un halo sombre, en nombre adapté à la taille du serveur (pour un grand serveur, seuls les noms qui tiennent ; zoomer ou chercher en révèle d'autres). Les **liens** forment une toile discrète : ils ne se révèlent qu'en **survolant** ou en **cliquant** une personne, dont les liens deviennent nets (épaisseur = poids de l'échange), avec le nom de ses interlocuteurs principaux. La fiche s'ouvre à côté de la carte. « Tout voir » revient à la vue d'ensemble.

## Installer

Il faut Docker (avec `docker compose`). Pour travailler sur le code, il faut aussi Python 3.13.

```console
cp .env.example .env     # puis choisissez les deux mots de passe (POSTGRES_PASSWORD, DINDON_PASSWORD)
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

`/health` doit répondre `"status":"ok"` avec **52 tables, 9 vues, 21 axes dont 12 actifs**. Les fichiers SQL sont appliqués au démarrage de l'application (voir [docs/DECISIONS.md](docs/DECISIONS.md)). Aucun port n'est ouvert sur le réseau : tout est publié sur `127.0.0.1` seulement.

Ouvrez ensuite **http://127.0.0.1:8000** et entrez le mot de passe `DINDON_PASSWORD` de `.env`. La carte est vide tant qu'aucun export n'est arrivé : déposez des fichiers JSON dans `inbox/` (ils sont importés puis rangés dans `archive/`) ou configurez la surveillance.

### Collecter les messages

Voir **[docs/COLLECTE.md](docs/COLLECTE.md)** : exports à la main, surveillance automatique (jeton, serveur, premier import avec `dindon backfill`), rattrapage nocturne, **bot en direct** (`docker compose --profile bot up -d --build`, pas encore essayé sur le vrai Discord), limites.

**Compte personnel ou bot ?** Un bot est recommandé : automatiser un compte personnel est interdit par Discord. L'interface affiche un bandeau d'avertissement tant qu'un compte personnel est utilisé.

### L'IA locale (Ollama)

Elle sert à l'analyse (page **Thèmes**) : voir [docs/ANALYSE.md](docs/ANALYSE.md) pour tout le détail. Sur un Mac, installez Ollama directement, pas dans Docker, qui ne peut pas utiliser la puce graphique :

```console
brew install --cask ollama-app && open -a Ollama   # ou le téléchargement de ollama.com ; sinon : ollama serve
ollama pull bge-m3 && ollama pull qwen3:14b        # 1,2 Go et 9,3 Go
```

Sur un serveur Linux, `docker compose --profile ollama up -d` le lance dans Docker. Réglez `OLLAMA_URL` dans `.env` (par défaut `host.docker.internal:11434`) ; `/health` indique si Ollama répond et quels modèles il a. Lancer l'analyse : page **Thèmes** de l'interface, ou `dindon analyze`.

## Utiliser

| Commande | Effet |
| --- | --- |
| `make up` / `make down` | démarrer / arrêter (les données sont gardées) |
| `make test` | tous les tests (voir plus bas) |
| `make web` / `make demo` / `make check-ui` | construire l'interface, la démonstration sans Discord, la vérification dans un navigateur |
| `/dindon debat sujet` (sur Discord) | ouvre une fenêtre de paramètres, puis un débat encadré (dans un fil si on le demande, sinon dans le salon) : positions, fin par bouton ou après un silence, statistiques, et, si vous l'activez, vérification des affirmations sur Internet : [docs/DEBAT.md](docs/DEBAT.md) |
| `/dindon forum` (sur Discord, modérateurs) | choisit le forum du serveur où Dindon crée les débats, un post chacun, avec étiquettes : [docs/DEBAT.md](docs/DEBAT.md) |
| `dindon debate-report` | ce que la vérification a noté des débats (affirmations, verdicts, sources, parité par position) |
| `python tools/measure_claims.py reading\|verify` | mesure la lecture et la vérification sur un jeu de référence (nécessaire avant les corrections publiques) |
| `dindon ingest dossier/` | importer des exports sans passer par `inbox/` |
| `dindon bot` | le bot en direct (jeton de bot, `DINDON_GUILD_IDS`) : normalement lancé par le service `bot` de Compose ; l'inviter sur un serveur : entrée **Inviter le bot** de l'interface (voir [COLLECTE.md](docs/COLLECTE.md)) |
| `dindon backfill --channel … --from … --mentioning … --after … --before …` | importer seulement certains salons, certaines personnes, une période (voir [COLLECTE.md](docs/COLLECTE.md)). Aussi dans l'interface : **Importer** (barre de gauche) |
| Recherche et filtres | **chaque page a sa barre de recherche** (accents et majuscules ignorés, tous les mots tapés doivent correspondre) et ses filtres ; la touche **/** met le curseur dans la recherche de la page. Carte : personnes, période, types de liens. Thèmes : mots, état, tri. Positions : proposition ou personne, thème, position, tri (les plus partagées, clivantes, récentes). Cohérence : personne ou rôle, verdict, rôle. Vie privée : registre et journal. Système : points à voir, serveurs. Fenêtres Importer et Inviter : salons et serveurs |
| Performance | limiter ce que le bot et l'IA prennent de la machine, au prix de la vitesse : page **Système**, panneau **Performance** (voir [docs/PERFORMANCE.md](docs/PERFORMANCE.md)) |
| Lecture automatique | l'IA lit de elle-même ce que le bot enregistre, à intervalle et à des heures choisis, **éteinte par défaut** : page **Système**, panneau **Lecture automatique** (voir [docs/LECTURE-AUTOMATIQUE.md](docs/LECTURE-AUTOMATIQUE.md)) |
| Axes de l'IA | ce qui a été vérifié, corrigé et ce qui reste (mesures, défaut corrigé, les 21 axes activés) : [docs/VALIDATION-AXES.md](docs/VALIDATION-AXES.md) |
| Rapport d'architecture | tout Dindon en un document : composants, flux, base, IA, vie privée, exploitation, niveaux de preuve et risques : [docs/RAPPORT-ARCHITECTURE.md](docs/RAPPORT-ARCHITECTURE.md) |
| `make politique` | un serveur politique **inventé** avec rôles, opinions connues et vérité pour tester l'IA, sur http://127.0.0.1:8012 (voir [docs/SERVEUR-DE-TEST.md](docs/SERVEUR-DE-TEST.md)) |
| `dindon privacy list\|stop\|erase\|release\|export\|purge [ID]` | les droits des personnes : ne plus enregistrer quelqu'un, l'effacer, lui donner ses données, purger l'ancien (voir [docs/CONFORMITE.md](docs/CONFORMITE.md)). Aussi : page **Vie privée**, et `/dindon` sur Discord (chaque membre gère ses données) |
| `dindon analyze` | l'analyse locale : conversations, vecteurs, thèmes à valider (Ollama requis, voir [docs/ANALYSE.md](docs/ANALYSE.md)). Aussi dans l'interface : page **Thèmes** |
| `dindon backfill` / `dindon catchup` | premier import d'un serveur / rattrapage des derniers jours maintenant |
| `make check` | ce que contient la base (tables, vues, axes) |
| `make axes` | réécrit [docs/AXES.md](docs/AXES.md) depuis la base : la page où relire les axes et idéologies |
| `make backup` | sauvegarde compressée dans `backups/` |

Activer un axe après relecture : `UPDATE axes SET is_active = true WHERE code = 'europe';`. **Les axes, idéologies, plages et règles de rôles sont les vôtres à relire** ; le code ne les modifie jamais.

## Sauvegarder et restaurer

```console
make backup                                  # crée backups/dindon-AAAA-MM-JJ-HHMM.sql.gz
```

Restaurer sur une installation neuve (base vide : seul `db` est démarré, l'application n'a donc rien créé) :

```console
docker compose up -d --wait db
gunzip -c backups/dindon-2026-10-01-2128.sql.gz | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U dindon dindon
docker compose up -d --build                 # les migrations voient que tout est déjà là
```

La sauvegarde contient **tous les messages** : traitez-la comme la base elle-même (ne la partagez pas, chiffrez le disque).

### Faire tourner Dindon sans personne devant l'ordinateur (Mac)

Les conteneurs redémarrent seuls (`restart: unless-stopped`) tant que Docker Desktop tourne (réglage « Start Docker Desktop when you sign in »). Deux choses ne survivent pas à un redémarrage sans aide : Ollama, et la sauvegarde. Un script les met en place, sans droits d'administrateur :

```console
sh tools/host/install.sh            # Ollama relancé à l'ouverture de session ; sauvegarde de la base chaque nuit à 03 h 30
sh tools/host/install.sh --remove   # défait tout (les sauvegardes sont gardées)
```

Les sauvegardes vont dans `~/Library/Application Support/Dindon/backups/` (14 jours gardés, lisibles par vous seul), les journaux dans `…/Dindon/logs/`. Les scripts y sont copiés parce qu'une tâche de `launchd` n'a pas le droit de lire le Bureau. Le Mac doit rester allumé (branché, couvercle ouvert) : il se met en veille sinon, et le bot se déconnecte.

La page **Système** de l'interface montre l'état de chaque pièce (bot, collecte, base, IA locale, serveurs suivis) et ce qui mérite un coup d'œil, avec le geste à faire.

## Mettre à jour

```console
git pull
docker compose up -d --build
```

Les nouvelles migrations (`db/migrations/`) sont appliquées au démarrage, une seule fois chacune, dans l'ordre.

## Dépanner

| Symptôme | Piste |
| --- | --- |
| `docker compose up` : « Choose a password in .env » | `.env` n'existe pas ou la variable est vide : `cp .env.example .env` |
| `/health` répond 503 | la base n'est pas prête ou le mot de passe de `.env` a changé après la création du volume : `docker compose logs db app` |
| Le mot de passe de la base a changé dans `.env` | il n'est pris en compte qu'à la création du volume. Soit remettre l'ancien, soit restaurer une sauvegarde dans un volume neuf (`docker compose down -v` **efface les données**) |
| Port 5432 ou 8000 déjà pris | changer `POSTGRES_PORT` ou `DINDON_PORT` dans `.env` |
| La carte reste vide | rien n'est encore importé : déposer des exports dans `inbox/`, ou `dindon backfill`. Bandeau « premier import pas fait » = la surveillance attend `dindon backfill` |
| Un fichier est dans `inbox/failed/` | lire le `.error.txt` à côté : fichier illisible ou pas du JSON v2 |
| Bandeau orange en haut | un compte personnel est automatisé : passer à un bot |
| En bas : une erreur de surveillance | `docker compose logs app` ; vérifier le jeton, l'identifiant du serveur, et que le bot voit les salons |
| `/health` : `"ollama":{"reachable":false}` | Ollama n'est pas lancé (`open -a Ollama` ou `ollama serve`), ou `OLLAMA_URL` est faux. Seule l'analyse en a besoin |
| Le build Docker échoue sur « no such host » | pas de réseau au moment du téléchargement des images : relancer |

## Tests

`make test` démarre une base jetable (projet Docker `dindontest`, port 55432), applique le schéma, lance les tests, puis supprime la base. Tout est inventé : un faux Discord (qui répond comme l'API REST, pour tester l'exportateur de Dindon) remplacent Discord. Ils couvrent :

- **la base et le calcul** : création (52 tables, 9 vues, 21 axes dont 12 actifs), migrations, scores (les deux valeurs de référence : −0,692 ± 0,381 et −0,662 ± 0,399), vérification avec les rôles ;
- **l'ingestion** : aller-retour sans aucune perte (chaque message, mention, réaction, pièce jointe, personne et rôle comparés au fichier), idempotence, chevauchements, messages modifiés, exports arrivant dans le désordre, suppressions et garde-fou, interruption puis reprise, fichiers invalides ;
- **le graphe** : les liens tenus à jour pendant l'import sont les mêmes que ceux recalculés depuis zéro ;
- **la collecte** : rien avant le premier import, premier import repris après interruption, un échange n'exporte que son salon, limitation de débit, échecs et reprise, compte ou bot, rattrapage nocturne ;
- **l'API** : mot de passe, cookies falsifiés, en-têtes de sécurité, graphe (tout le temps ou une période : les deux calculs concordent), recherche, fiche, **aucun rôle d'âge ou de genre ne sort jamais** ;
- **de bout en bout, sur un vrai port** : un échange sur le faux Discord arrive à la page en quelques secondes (0,5 s mesuré avec un relevé toutes les secondes).

La page elle-même se vérifie dans un vrai navigateur avec `make check-ui` (facultatif : il faut Playwright).

## Organisation

| Dossier | Contenu |
| --- | --- |
| `contracts/` | le contrat de données : JSON version 2 (description, JSON Schema, modèle) |
| `db/` | les fichiers SQL (`schema*.sql`, `seed-axes.sql`) et les migrations |
| `app/dindon/` | l'application Python (FastAPI) |
| `web/` | l'interface (Svelte + Sigma.js) |
| `tools/` | outils : serveur de démonstration et serveur politique inventé, faux Discord / Gateway / Ollama, mesures, relecture et mesure des axes et des positions (`review_axes`, `check_axes`, `check_stances`, `score_axes_reference`…) |
| `tests/` | tests (données inventées uniquement) ; `make lint` : ruff |
| `docs/` | [résumé de tout le projet](docs/RESUME.md), [architecture](docs/ARCHITECTURE.md), [collecte](docs/COLLECTE.md), [mesures](docs/MESURES.md), [décisions](docs/DECISIONS.md), [axes à relire](docs/AXES.md), [la base](docs/base-de-donnees.md), le prompt d'origine |
| `docs/PRODUCTION.md` | [la liste à suivre avant et après avoir mis le bot sur un vrai serveur](docs/PRODUCTION.md), avec le contrôle automatique `dindon preflight` |
| `docs/CONVENTIONS.md` | [où va quoi dans le code, et les principes à suivre](docs/CONVENTIONS.md) |
| `app/dindon/export/` | [l'exportateur de Dindon](docs/EXPORTATEUR.md) : il lit Discord et écrit le JSON v2 |
