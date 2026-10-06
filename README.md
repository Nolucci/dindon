# Dindon

Dindon collecte les échanges d'un serveur Discord, affiche une carte des interactions et peut analyser localement les conversations, thèmes et positions. Le bot propose aussi des commandes de vie privée, des cartes et des débats. L'interface et PostgreSQL tournent sur votre machine ; Discord reste nécessaire pour la collecte et le bot. La vérification des débats peut consulter Internet **uniquement si elle est activée**.

## Démarrer

Prérequis : Docker avec Compose. Pour développer hors Docker : Python 3.12 ou plus, Node.js 20.19+ (ou 22.12+) et, pour l'analyse, Ollama.

```sh
cp .env.example .env       # renseigner POSTGRES_PASSWORD et DINDON_PASSWORD
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

Ouvrir <http://127.0.0.1:8000> et saisir `DINDON_PASSWORD`. Les ports de Compose sont publiés sur `127.0.0.1`. La page reste vide avant le premier import. Déposer un export JSON v2 dans `inbox/` ou configurer `DISCORD_TOKEN` et lancer un import depuis l'interface. Pour le bot en direct : `docker compose --profile bot up -d --build` après avoir activé **Message Content Intent** pour l'application Discord. `DINDON_GUILD_IDS` liste les serveurs à suivre ; vide ou `all` suit tous les serveurs du bot.

Pour une démonstration avec des personnes inventées, sans Discord :

```sh
make setup web
make demo                 # http://127.0.0.1:8011 ; mot de passe demo
```

## Documentation

| Fichier | Contenu |
| --- | --- |
| [Lancer l'application](LANCER.md) | commandes de première installation, démarrage, arrêt et variantes |
| [Base de données](docs/base-de-donnees.md) | schéma, migrations, sauvegarde, effacement |
| [Architecture](docs/architecture.md) | composants, flux, frontières et état de réalisation |
| [Fonctionnement](docs/fonctionnement.md) | interface, analyse, carte, débats et vie privée |
| [Commandes](docs/commandes.md) | CLI, Makefile, configuration et exploitation |
| [Règles du bot](docs/regles-du-bot.md) | commandes Discord, accès, débats et garde-fous |
| [API et export](docs/api-export.md) | routes HTTP, sessions, Activity et export JSON v2 |
| [Import des données](docs/import-des-donnees.md) | format, import manuel, backfill, collecte et reprise |

Le contrat machine se trouve dans [JSON-format.schema.json](contracts/JSON-format.schema.json), avec un [exemple](contracts/JSON-format.template.json). Les données d'essai et résultats de mesure sont dans `political/` ; ce sont des jeux de travail, pas la documentation d'utilisation.

## Prudence

Les messages, rôles et positions peuvent être des données sensibles, notamment des opinions politiques. L'accès à l'interface repose sur un mot de passe unique ; protégez la machine, les sauvegardes et le fichier `.env`, et informez les membres avant de collecter ou de montrer leurs données. Les positions déduites par l'IA sont des hypothèses à relire avec leurs citations. L'automatisation d'un compte personnel Discord enfreint ses conditions d'utilisation : utiliser un jeton de bot.

Le code comporte des tests sur un faux Discord et des données inventées. La présence d'une fonction ou d'un test ne garantit pas son comportement sur tous les serveurs Discord réels. Les corrections publiques automatiques des débats ont un verrou de précision configurable ; voir [Règles du bot](docs/regles-du-bot.md).
