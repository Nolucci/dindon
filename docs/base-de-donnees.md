# Base de données

Où stocker les messages exportés pour pouvoir, ensuite, analyser tout ce que dit chaque personne.

Le système complet (collecte automatique, analyse par IA locale, carte en direct) est décrit dans [ARCHITECTURE.md](ARCHITECTURE.md). Cette page ne traite que de la base.

## Recommandation : PostgreSQL 17 + pgvector, en local avec Docker

Une seule base, installée sur votre serveur, sans aucun service externe.

| Besoin du projet | Ce que PostgreSQL apporte |
| --- | --- |
| Le JSON v2 est déjà un modèle de tables (`users`, `roles`, `emojis`, `messages` qui s'y réfèrent par identifiant) | Il se traduit directement en tables reliées par clés étrangères : [schema.sql](../db/schema.sql) |
| « Tous les messages d'une personne, dans l'ordre » | Un index `(auteur, date)` : moins de 2 ms pour une personne moyenne (1 000 messages) sur 500 000 messages |
| Texte en français, avec accents, et noms en lettres fantaisie (`𝐿𝑖𝑡𝑡𝑒́𝑟𝑎𝑡𝑢𝑟𝑒`) | Recherche plein texte française qui ignore les accents, et colonnes normalisées (`name_normalized`) : 5 à 11 ms sur 500 000 messages |
| Qui parle à qui (réponses, mentions, réactions) | Des jointures et des vues SQL (`interactions`, `user_stats`) |
| Profils et cartes générés par une IA locale | Tables `profiles` et `cards` avec `jsonb`, le modèle et la version du prompt utilisés, et les messages sur lesquels ils reposent |
| Recherche « par sens » (optionnelle) | `pgvector`, dans la même base, sans second système à installer |
| Ré-exports réguliers du même salon | `INSERT … ON CONFLICT` : les messages modifiés sont mis à jour, rien n'est dupliqué |
| Tout en local, sur votre serveur | Un conteneur, des données dans un volume, sauvegarde par une commande |

### Les autres options

- **SQLite** : la plus simple (un seul fichier, aucun serveur), et suffisante si une seule personne utilise l'application sur une seule machine. Je ne la retiens pas, parce qu'une application sur serveur aura plusieurs processus (interface, import, calculs d'IA) qui écrivent en même temps, et que sa recherche plein texte ne gère pas le français aussi bien.
- **DuckDB** : excellent pour explorer les fichiers JSON en SQL, sans rien importer. À garder comme outil d'analyse ponctuelle, mais pas comme base de l'application (pas faite pour plusieurs écritures concurrentes).
- **MongoDB** : se prête au JSON, mais les jointures (messages, personnes, rôles) sont son point faible, et c'est précisément ce dont l'analyse a besoin.
- **Elasticsearch / OpenSearch** : lourds à faire tourner pour ce volume. PostgreSQL suffit.

## Ce qui a été mesuré

Sur 500 000 messages simulés (400 personnes dont quelques-unes très actives, 40 salons, vrais textes français), avec PostgreSQL 17 dans Docker :

| Mesure | Résultat |
| --- | --- |
| Insertion de 500 000 messages, index et recherche plein texte compris | 11 s |
| Taille sur disque (tables + index) | 206 Mo (126 Mo de tables, 72 Mo d'index), soit environ 430 octets par message |
| Tous les messages d'une personne moyenne (1 025 messages) | 1 à 2 ms |
| Tous les messages de la personne la plus active (67 728 messages, 14 % du total) | 40 à 70 ms |
| Recherche plein texte en français, sans accents (10 002 résultats) | 5 à 11 ms |
| Chiffres de chaque personne (`user_stats`, 408 personnes) | 26 ms |
| Les 5 paires de personnes qui se répondent le plus | 36 à 44 ms |
| 5 messages les plus proches par le sens (30 000 vecteurs de 1 024 dimensions, avec index) | 3 ms |

Chaque requête a été lancée plusieurs fois, et la plage donnée va de la plus lente à la plus rapide. Ces chiffres viennent d'un jeu de test, sur un ordinateur de 24 Go de mémoire : ils montrent l'ordre de grandeur, pas une garantie sur votre serveur.

À savoir sur la recherche par le sens : un vecteur de 1 024 dimensions prend environ 5 Ko, plus environ 8 Ko pour son entrée d'index. Pour 1 million de messages, cela ferait 13 Go. Mieux vaut vectoriser les messages qui en valent la peine, ou des groupes de messages, plutôt que tous. Voir [schema-vector.sql](../db/schema-vector.sql).

Avec vos vraies données (export « Recyclage », 118 messages), j'ai vérifié qu'après import, chaque message, chaque personne et chaque rôle est identique au fichier d'origine : rien n'est perdu.

## Les tables

| Groupe | Tables |
| --- | --- |
| Provenance | `ingest_runs` : un fichier importé une seule fois (empreinte `sha256`) |
| Serveurs | `guilds`, `channels` (le parent d'un fil ou d'un post de forum est dans `parent_id`) |
| Personnes | `users` (le compte, identifié par un numéro qui ne change jamais), `members` (pseudo, couleur, avatar **dans ce serveur**), `roles`, `member_roles`, `identity_history` (tous les noms et pseudos déjà vus : un changement de pseudo ne fait rien perdre) |
| Messages | `messages`, `attachments`, `mentions`, `reactions`, `reaction_users`, `message_emojis`, `emojis` |
| Analyse | `profiles`, `cards`, et tout ce qui est décrit plus bas (fichier `schema-analysis.sql`) |
| Vues | `member_names` (le nom affiché), `user_stats`, `interactions` |

Choix de conception :
- Les identifiants Discord sont des `bigint` : ils tiennent dans 63 bits, ce qui est plus petit et plus rapide à joindre que du texte.
- Le pseudo, la couleur, les rôles et l'avatar sont rangés par serveur (`members`), parce qu'ils dépendent du serveur. Le nom d'utilisateur et le nom d'affichage sont rangés par compte (`users`).
- Les parties rares et imbriquées (liens enrichis, autocollants, sondages, messages transférés) restent en `jsonb` dans `messages.extra`. Rien n'est stocké deux fois.
- La réponse à un message garde l'auteur et le texte du message d'origine, même s'il n'est pas dans la base.

## L'analyse : axes, idéologies, rôles

Le fichier [schema-analysis.sql](../db/schema-analysis.sql) ajoute ce qui est dérivé des messages, et [seed-axes.sql](../db/seed-axes.sql) contient les données de départ à relire : les 12 axes du modèle [12 Axes](https://12axes.vercel.app) plus 9 axes ajoutés, **actifs depuis le 4 octobre 2026** (Europe, écologie, rupture, protection sociale, confiance, genre, animaux, alliances, démocratie directe), avec leurs définitions et trois points de repère chacun, 28 idéologies avec ce qu'elles impliquent sur les axes (72 fourchettes), et 37 règles de reconnaissance des rôles. La méthode est expliquée dans [ARCHITECTURE.md](ARCHITECTURE.md), section 6, et tout est lisible dans [AXES.md](AXES.md), généré par `generate_axes_review.py`.

Ce qui a été testé : sur vos 51 rôles réels, 27 sont reconnus comme des rôles d'idéologie, 7 notifications, 3 équipe, 2 âge, 2 genre, 1 base, 7 séparateurs, et 2 ne sont pas reconnus (« Dunes », « Plato »). Sur un scénario inventé de cinq personnes, les scores calculés correspondent au calcul fait à la main, et la vérification donne les verdicts attendus (concordant, discordant, non vérifiable, rôles contradictoires). Les fichiers s'appliquent depuis zéro sans erreur et peuvent être rejoués sans rien changer.

## Installer

```console
cd database
cp .env.example .env        # puis choisissez un mot de passe dans .env
docker compose up -d
```

Les quatre fichiers SQL (base, analyse, données de départ, vecteurs) sont appliqués dans cet ordre au premier démarrage. La base n'écoute que sur `127.0.0.1` : elle n'est pas accessible depuis le réseau, seulement depuis le serveur lui-même.

Importer un export (exemple de référence, voir l'en-tête du fichier) :

```console
pip install "psycopg[binary]"
DATABASE_URL=postgresql://dindon:MOT_DE_PASSE@127.0.0.1:5432/dindon python load_export.py mon_export.json
```

Sauvegarder et restaurer :

```console
docker compose exec -T db pg_dump -U dindon dindon | gzip > sauvegarde-$(date +%F).sql.gz
gunzip -c sauvegarde-2026-10-01.sql.gz | docker compose exec -T db psql -U dindon dindon
```

Chiffrez le disque du serveur si les données sont sensibles : la base ne le fait pas elle-même.

## Personnes concernées

Les messages sont ceux de personnes identifiables, et des opinions politiques en font partie. Le schéma prévoit donc de pouvoir effacer quelqu'un : `SELECT forget_user(<numéro>)` supprime la personne et tout ce qui lui est lié (messages, réactions, mentions, profils, cartes), y compris ce que d'autres avaient cité d'elle en lui répondant. Gardez les profils et les cartes dans la base locale, et limitez l'accès au serveur.
