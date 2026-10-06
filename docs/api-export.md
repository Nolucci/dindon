# API HTTP et export

L'application écoute par défaut sur `127.0.0.1:8000` avec Compose. `POST /api/login` reçoit `{"password":"…"}` et pose un cookie `dindon_session` signé, HttpOnly et SameSite Strict ; `POST /api/logout` l'efface et `GET /api/session` dit si la session est valide. Les autres routes `/api/*` et `/events` demandent le cookie. `GET /health` est public et n'expose que version, compte de la base et état des modèles Ollama. Le schéma OpenAPI et Swagger sont désactivés.

## Routes de l'interface

| Famille | Routes |
| --- | --- |
| Carte et personnes | `GET /api/guilds`, `/api/graph`, `/api/people`, `/api/person/{user_id}`, `/api/avatar/{user_id}`, `/api/status` |
| Import | `GET /api/import/options`, `GET/POST /api/import`, `POST /api/import/cancel` |
| Analyse | `GET/POST /api/analysis`, `POST /api/analysis/cancel`, `GET /api/topics`, `PATCH /api/topics/{topic_id}`, `POST /api/topics/{topic_id}/merge` |
| Positions | `GET /api/positions`, `/api/positions/proposition/{id}`, `/api/positions/person/{id}`, `/api/positions/coherence` ; validation et réglages sous `PUT/POST /api/positions/*` |
| Vie privée | `GET /api/privacy`, `/api/privacy/find`, `/api/privacy/export/{user_id}` ; `POST /api/privacy/stop`, `/erase`, `/release` |
| Exploitation | `GET /api/system`, `GET/PUT /api/performance`, `GET/PUT /api/automation`, `POST /api/automation/run`, `GET/PUT /api/discord-map`, `GET /api/bot/invite` |
| Débats | `GET /api/debates`, `GET /api/debates/{debate_id}` |
| Direct | `GET /events` : Server-Sent Events après authentification |

Les modèles des requêtes et réponses sont définis dans `app/dindon/api/`. Les erreurs utilisent les statuts HTTP habituels : 401 sans session, 403 si le serveur n'est pas suivi, 409 si un travail est déjà en cours, 422 pour une sélection invalide, 429 en cas de limite et 502 si Discord répond mal.

## Activity Discord

`GET /activity/config` fournit l'identifiant de l'application ; `POST /activity/token` échange un code OAuth Discord ; `GET /activity/map`, `/activity/person/{user_id}` et `/activity/avatar/{user_id}` servent une carte limitée au serveur demandé. Ces routes ne donnent pas accès à l'API d'administration : elles exigent un jeton Discord et vérifient l'appartenance au serveur. L'Activity nécessite `DISCORD_CLIENT_ID` et `DISCORD_CLIENT_SECRET` et une adresse accessible par Discord.

## Exportateur Discord

`dindon export CHANNEL_ID --out dossier/` appelle l'API REST Discord et écrit un ou plusieurs fichiers **JSON v2** conformes à [JSON-format.schema.json](../contracts/JSON-format.schema.json). Il exporte les messages du salon et, selon `--threads none|active|all`, ses fils publics accessibles. `--after` et `--before` sont des identifiants de messages ; `--filter` restreint les auteurs et mentions, par exemple `"(from:111 | from:222) (mentions:333)"`. `--partition` fixe le nombre de messages par fichier.

Le nombre de chaque réaction est conservé. L'identité des personnes qui ont réagi demande des requêtes supplémentaires : `--reactions recent` est le défaut (30 jours, réglable), `all` lit tout, `none` omet les identités. Un ré-export avec `none` peut donc faire perdre des identités de réactions déjà importées. L'exportateur écrit d'abord un fichier temporaire puis le renomme lorsqu'il est complet. Les pièces jointes sont référencées, pas téléchargées. Le contrat JSON v2 et l'import correspondant sont décrits dans [Import des données](import-des-donnees.md).
