# Import des données

Tous les modes d'import passent par `app/dindon/ingest/loader.py` et le format **JSON v2**. Le contrat vérifiable est [JSON-format.schema.json](../contracts/JSON-format.schema.json) ; [JSON-format.template.json](../contracts/JSON-format.template.json) illustre les champs. Le document contient notamment `schemaVersion: 2`, `guild`, `channel`, `users`, `roles`, `emojis`, `messageCount` et `messages`. `dateRange` est présent quand une fenêtre est exportée. Chaque message a un identifiant, un auteur, une date, un type et un contenu ; les réponses, mentions, réactions, pièces jointes et autres structures peuvent être ajoutées. Les identifiants Discord sont représentés par des chaînes décimales dans le JSON ; les dates sont en UTC. Les tables `users`, `roles` et `emojis` évitent de répéter leurs propriétés dans chaque message. Les champs nuls ou vides peuvent être omis.

## Déposer un fichier

Déposer des fichiers `.json` complets dans `inbox/`, monté dans le conteneur d'application. Le surveillant attend que le fichier soit stable, l'importe, puis le déplace vers `archive/AAAA-MM/` avec un préfixe issu de son empreinte SHA-256. Un fichier encore en cours d'écriture attend ; s'il reste illisible une minute, il passe dans `inbox/failed/` avec un `.error.txt`. On peut aussi importer directement :

```sh
docker compose exec app dindon ingest /data/inbox/export.json
```

La commande accepte plusieurs fichiers ou dossiers. Un même fichier est reconnu par son empreinte et n'est pas réimporté. Les messages déjà présents peuvent être actualisés lorsqu'un export plus récent apporte une modification. `--prune` ne convient qu'à un **ré-export complet** d'une fenêtre : les messages absents de cette fenêtre peuvent être supprimés.

## Importer depuis Discord

Avec un jeton de bot et les serveurs configurés, la fenêtre **Importer** de l'interface ou `dindon backfill` lit l'historique via l'exportateur REST. Sans filtre, ce premier import marque les salons complets et permet la surveillance continue. `--channel` sélectionne un salon par nom ou ID ; `--from` et `--mentioning` sélectionnent des personnes par ID ; `--after` et `--before` sélectionnent des dates incluses. Ces options sont répétables lorsque indiqué par `--help`. Un filtre de personne ou de date crée un import partiel, qui ne remplace pas le premier import complet.

Le collecteur `DINDON_COLLECTOR=on` relève périodiquement les salons modifiés (`DINDON_POLL_SECONDS`, 30 secondes par défaut) et effectue un rattrapage nocturne. `catchup` conserve seulement le rattrapage, utile avec le bot Gateway ; `off` désactive le collecteur sans arrêter l'import de `inbox/`. `dindon catchup` déclenche un rattrapage immédiat. Le bot Gateway reçoit les nouveaux messages, modifications et suppressions en direct ; le rattrapage compense les déconnexions et relit les changements.

L'exportateur est limité aux salons et fils que le jeton peut lire. `DINDON_THREADS` vaut `active` par défaut ; `all` ajoute les fils publics archivés accessibles. Les messages privés et fils privés archivés ne sont pas couverts. Pour les réactions, `DINDON_EXPORT_REACTIONS=recent` ne récupère par défaut les identités que sur la fenêtre récente ; le nombre de réactions reste conservé. Voir [API et export](api-export.md).

## Vérifier et reprendre

`dindon check` confirme que la base et ses migrations sont accessibles ; `/health` fournit un état succinct. La page **Système** affiche l'état du collecteur et des serveurs. Un import interrompu se relance : les fichiers connus sont sautés et les messages ne sont pas dupliqués. Consulter `docker compose logs app` et `inbox/failed/*.error.txt` en cas d'échec. Les messages d'une personne inscrite au registre d'arrêt ne sont pas enregistrés, même si un ancien export la contient.
