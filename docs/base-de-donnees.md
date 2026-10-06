# Base de données

Dindon utilise PostgreSQL 17 avec `pgvector` dans le service `db` de Compose. `app/dindon/migrate.py` applique quatre fichiers de base dans cet ordre : `schema.sql`, `schema-analysis.sql`, `seed-axes.sql`, `schema-vector.sql`, puis les migrations numérotées de `db/migrations/`. Les fichiers de base sont rejouables lorsqu'ils changent ; une migration déjà appliquée ne doit pas être modifiée. `schema_migrations` conserve leur empreinte SHA-256. `dindon check` et `/health` donnent les nombres réels de tables, vues, axes et migrations : ces comptes peuvent évoluer.

## Principales données

| Famille | Tables principales |
| --- | --- |
| Origine | `ingest_runs`, `guilds`, `channels` |
| Personnes | `users`, `members`, `roles`, `member_roles`, `identity_history` |
| Messages | `messages`, `attachments`, `mentions`, `reactions`, `reaction_users`, `emojis`, `message_emojis` |
| Carte | `edges`, vues `interactions` et `user_stats` |
| Analyse | `conversations`, `conversation_messages`, `conversation_embeddings`, `topics`, `topic_assignments`, `claims`, `claim_evidence`, `propositions`, `proposition_axis`, `person_axis_scores`, `axes`, `ideologies`, `role_rules` |
| Débats | `debates`, `debate_messages`, `debate_positions`, `debate_claims`, `debate_sources`, `debate_corrections`, `debate_answers`, `debate_answer_votes` |
| Exploitation | `jobs`, `service_status`, `runtime_settings`, `privacy_subjects`, `privacy_log` |

Les identifiants Discord sont des entiers longs ; noms et rôles propres à un serveur sont dans `members` et ses relations. Les champs imbriqués peu fréquents sont conservés en JSONB. Les vecteurs sont stockés dans PostgreSQL avec le nom du modèle. Les axes et règles de rôles initiaux se trouvent dans `seed-axes.sql` : relisez ces choix avant d'utiliser les déductions sur des personnes.

## Vie privée et cohérence

`privacy_subjects` est le registre des personnes à ne plus enregistrer. `dindon privacy stop ID` empêche les futurs imports ; `erase ID` efface aussi les données déjà conservées et les traces des fichiers `inbox/` et `archive/`. `release ID` reprend l'enregistrement sans restaurer les données effacées. Une rétention positive déclenche la purge quotidienne des anciens messages. Les sauvegardes sont séparées de ce mécanisme : il faut gérer leur durée de conservation et leur accès.

L'import est idempotent. Il peut actualiser un message modifié ; un ré-export complet avec `dindon ingest --prune` peut retirer les messages absents de la fenêtre exportée. Les résultats dérivés des messages modifiés ou supprimés sont invalidés par l'ingestion. `dindon rebuild-edges` recalcule les liens depuis les messages si nécessaire.

## Sauvegarde et restauration

```sh
make backup                  # backups/dindon-AAAA-MM-JJ-HHMM.sql.gz
docker compose up -d --wait db
gunzip -c backups/SAUVEGARDE.sql.gz | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U dindon dindon
docker compose up -d --build
```

Restaurer dans une base vide, application arrêtée. La sauvegarde comprend les messages et peut contenir des opinions sensibles : chiffrer le support et limiter l'accès. `docker compose down` garde le volume ; `down -v` le supprime.
