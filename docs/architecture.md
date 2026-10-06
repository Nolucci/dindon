# Architecture

## Composants

| Élément | Rôle | Code |
| --- | --- | --- |
| PostgreSQL 17 et pgvector | messages, relations, analyses, réglages et suivi des tâches | `db/`, `app/dindon/db.py` |
| Application FastAPI | interface, API, import de `inbox/`, surveillance, lecture automatique | `app/dindon/api/`, `api/background.py` |
| Interface Svelte | carte, thèmes, positions, cohérence, débats, vie privée, système | `web/src/` |
| Exportateur REST | lecture de l'historique Discord vers JSON v2 | `app/dindon/export/` |
| Collecteur | premier import, relevé périodique, rattrapage | `app/dindon/collector/` |
| Bot Gateway | nouveaux messages, commandes `/dindon`, débats | `app/dindon/bot/` |
| Ollama | vecteurs, noms des thèmes, lecture des positions et des affirmations | `app/dindon/analysis/`, `debate/` |

`docker-compose.yml` démarre la base et l'application. Les profils facultatifs `bot`, `search` et `ollama` ajoutent respectivement le bot en direct, SearXNG et Ollama. Sur Mac, Ollama peut tourner sur l'hôte et être atteint via `host.docker.internal`.

## Flux des données

1. Un export manuel, l'exportateur REST du collecteur ou le Gateway du bot produit le même document JSON v2. L'adaptateur `bot/adapter.py` est partagé par le bot et l'exportateur.
2. `ingest/loader.py` valide le document, crée ou actualise les messages et leurs relations, et maintient les liens de la carte. Un import répété est reconnu par son empreinte ; les modifications de message invalident les résultats qui en dépendent.
3. La base sert les routes `/api/*` de l'interface. Un flux `/events` annonce les changements pour animer la carte.
4. L'analyse locale regroupe les messages en conversations, trie celles qui ont du contenu, calcule leurs vecteurs et propose des thèmes. Les étapes `claims` et `axes` lisent des positions, rapprochent les propositions, proposent leurs liens aux axes et calculent des scores avec incertitude. Les liens aux axes sont soumis à validation humaine dans l'interface.
5. Les débats utilisent des tables distinctes pour leurs messages, positions, affirmations, sources, réponses et votes. Selon le mode choisi, une vérification peut envoyer une requête neutre à un service de recherche puis lire des pages trouvées.

Les tâches de l'application sont démarrées dans `api/background.py` : surveillance de `inbox/` toutes les deux secondes, collecteur s'il est configuré, analyse automatique si activée, et purge quotidienne lorsque `DINDON_RETENTION_DAYS` est positif. Le service `bot` dépend de la santé de l'application, qui applique les migrations au démarrage.

## Accès et limites

L'interface locale utilise `DINDON_PASSWORD` et un cookie signé. Les routes `/api/*` et `/events` demandent une session, à l'exception de la connexion et de l'état de session ; `/health` ne révèle que des comptes et l'état d'Ollama. L'Activity Discord a ses propres routes `/activity/*` et vérifie auprès de Discord que le porteur du jeton appartient au serveur demandé. Le serveur de recherche facultatif n'expose pas de port dans Compose.

La collecte nécessite l'API Discord. Ollama doit rester à une adresse locale si les textes ne doivent pas quitter la machine. Les modes de débat `observe` et `live`, ainsi que certaines suites du mode `answer`, effectuent des recherches externes : cette exception doit être connue des membres. La qualité des positions, des scores et des corrections dépend du modèle, des données et des validations humaines ; les tests automatisés utilisent principalement des données simulées.
