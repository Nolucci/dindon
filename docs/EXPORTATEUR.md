# L'exportateur de Dindon

Dindon lit lui-même l'API de Discord pour importer l'historique et faire le rattrapage nocturne. **Ce code est à Dindon** (`app/dindon/export/`, Python) : il remplace DiscordChatExporter, un programme .NET écrit pour les besoins de quelqu'un d'autre, qui était lancé comme un processus à part. Plus de second environnement d'exécution dans l'image (`libicu` n'est plus installée), plus de binaire à compiler pour chaque machine, plus de dépendance au code d'un autre.

Il produit **le même JSON version 2** ([contracts/JSON-format.md](../contracts/JSON-format.md)) que l'ingestion lit déjà, et passe par **le même adaptateur** que le bot (`bot/adapter.py`) : un message est écrit de la même façon, qu'il arrive par le Gateway ou par l'exportateur.

**Niveau de preuve : testé contre un faux Discord qui répond comme l'API REST (`tools/fake_discord.py`) ET essayé en lecture seule sur le vrai Discord, sur 2 salons réels (474 messages), comparés à ce que l'ancien exportateur avait écrit en base (§6).** Pas essayé : un gros serveur, les limites de débit réelles, les fils archivés, les sondages et les messages transférés réels.

## 1. Ce qui le rend économe pour ce que Dindon en fait

| | |
| --- | --- |
| **Seulement ce qui est demandé** | `after` et `before` partent chez Discord (le relevé ne demande que les messages après le plus récent connu) ; le **filtre** d'un import restreint (auteurs, mentions) est appliqué **avant** de demander quoi que ce soit d'autre pour un message |
| **Peu de requêtes** | 100 messages par requête ; le profil d'une personne dans le serveur (pseudo, rôles) est demandé **une seule fois** (gardé une heure, partagé par les salons exportés en même temps) ; un ancien membre coûte une requête, une fois ; les rôles et salons du serveur sont lus une fois par dix minutes |
| **Seulement les gens utiles** | profil demandé pour qui **a écrit**, a été **mentionné** ou a reçu une **réponse** (ce qu'il faut au texte des messages et aux rôles des auteurs) ; **pas** pour qui n'a fait que réagir |
| **Qui a réagi : au choix** | le nombre de chaque réaction est toujours écrit ; *qui* a réagi est **une requête par réaction** : par défaut seulement pour les messages **récents** (`DINDON_EXPORT_REACTIONS=recent`, 30 jours), ou `all`, ou `none` |
| **En parallèle** | les profils et les réactions d'une page sont demandés pendant qu'on lit la suivante (`DINDON_EXPORT_WORKERS`, 6 par défaut) ; une connexion ouverte est gardée par fil (pas de poignée de main TLS à chaque requête) |
| **Les limites de Discord respectées avant d'être atteintes** | chaque réponse dit combien de requêtes restent dans le seau (`X-RateLimit-Remaining`) et quand il se remet : une requête qui serait refusée **attend** à la place ; plafond global de 40 requêtes par seconde ; un `429` quand même : on attend ce que Discord demande, puis on reprend ; au-delà de 2 minutes d'attente demandées, l'export s'arrête en le disant |
| **Rien de moitié écrit** | un fichier n'apparaît dans le dossier que complet (écrit sous un nom temporaire, puis renommé) |

Un fichier n'est **pas** écrit pour un salon qui n'a rien de nouveau.

## 2. Ce qu'il fait, et ce qu'il ne fait pas

**Il fait** : un salon (texte, vocal, annonces, fils, scène) ; ses **fils** avec lui (`DINDON_THREADS` : `none`, `active` : les fils actifs, `all` : et les fils publics archivés) ; un **forum** (ses fils seulement, un forum n'a pas de messages) ; le texte mis en forme comme l'exportateur d'origine (mentions en noms, salons, rôles, émojis personnalisés, dates), les messages système, les réponses (qui, et quoi), les pièces jointes, **les aperçus (embeds), les sondages, les messages transférés**, les réactions, les interactions, les épinglés, les modifications ; le **filtre** d'un import restreint ; la **partition** en fichiers (50 000 messages au premier import) ; l'arrêt immédiat (« Annuler » de la fenêtre Importer).

**Il ne fait pas** :
- les messages privés ;
- les fils **privés** archivés (seuls les publics le sont) ;
- les **émojis Unicode du texte** (`inlineEmojis`) et le **nom court** (`code`) d'un émoji standard : l'exportateur d'origine avait un index complet des émojis, pas lui ; les émojis des **réactions** et des sondages, eux, sont écrits (avec leur image Twemoji) ;
- **qui a réagi** hors de ce que dit le réglage (§1), et les profils des personnes qui n'ont fait que réagir (elles gardent ce qu'on savait d'elles) ;
- télécharger les pièces jointes ni les images (jamais fait par Dindon).

## 3. Les réglages

| `.env` | |
| --- | --- |
| `DINDON_EXPORT_REACTIONS` | `recent` (défaut), `all`, `none` |
| `DINDON_EXPORT_REACTIONS_DAYS` | 30 : « récent » pour les réactions |
| `DINDON_EXPORT_WORKERS` | 6 : requêtes en parallèle par export |
| `DINDON_THREADS` | `active` (défaut), `none`, `all` |

**Attention aux réactions** : si l'on ré-exporte avec `none` un message qui avait déjà ses réactions nominatives, l'ingestion remplace les réactions du message et **oublie qui avait réagi**. Le rattrapage nocturne (7 derniers jours) reste dans la fenêtre des 30 jours par défaut ; ne mettez pas `DINDON_EXPORT_REACTIONS_DAYS` en dessous de `DINDON_CATCHUP_DAYS`.

## 4. En ligne de commande

```console
dindon export CHANNEL_ID --out dossier/                       # tout le salon
dindon export CHANNEL_ID --after ID_DE_MESSAGE --reactions none
dindon export CHANNEL_ID --filter "(from:111 | from:222) (mentions:333)" --threads all --partition 50000
```

Il écrit les fichiers JSON v2 et dit combien de messages, de requêtes, de profils et de listes de réactions il a fallu. Les fichiers se déposent dans `inbox/` ou s'importent avec `dindon ingest`. Le jeton est dans `DISCORD_TOKEN` (`.env`) : il ne figure jamais dans une erreur, un fichier ou un journal.

## 5. Où est le code

| | |
| --- | --- |
| `export/exporter.py` | l'exportateur : le serveur, les profils, les réactions, les pages, les fils, les fichiers |
| `export/client.py` | le client HTTP : connexions gardées, limites, reprises, erreurs en mots |
| `export/filters.py` | le filtre (auteurs, mentions) |
| `export/writer.py` | la mise en page du JSON v2 (une ligne par élément) |
| `bot/adapter.py` | message Discord → document JSON v2 (partagé avec le bot) |
| `collector/watch.py` | le relevé, le premier import et le rattrapage, qui appellent l'exportateur |
| `tools/fake_discord.py`, `tools/rest_payloads.py` | le faux Discord qui répond comme l'API REST |
| `tests/test_exporter.py` | 27 tests : le document dit ce que dit le serveur, le nombre de requêtes, les erreurs, l'arrêt |

## 6. Essai réel (4 octobre 2026) et à refaire

**Fait, en lecture seule** (`dindon export` dans le conteneur, avec le jeton du bot ; rien n'a été écrit dans la base) sur les deux salons « général » de vos deux serveurs : **474 messages**, 20 requêtes pour 430 messages (et 15 profils). Comparé champ par champ à ce que **l'ancien exportateur** avait écrit en base pour les mêmes messages :

| | Résultat |
| --- | --- |
| Type, texte, auteur, heure, épinglé, réponse (message, auteur, texte cité), mentions | **identiques sur les 474 messages** |
| Nombre de réactions | identique ; **qui a réagi** (`--reactions all`) : identique sur la seule réaction réelle trouvée |
| Pièces jointes, aperçus (embeds), autocollants : présence et contenu | identiques, **sauf** : la liste `images` d'un aperçu (corrigée depuis, l'adaptateur l'écrit) et les `inlineEmojis` Unicode d'un aperçu (7 messages, **lacune connue**, §2) |
| Une personne | un rôle de moins qu'en base : probablement un rôle retiré depuis l'ancien export (la base garde ce que le bot a vu), non vérifié |
| Messages système (`GuildMemberJoin`) | identiques |

**Ce que cet essai ne prouve pas** : un gros salon (plusieurs milliers de messages : la pagination est la même, mais jamais vue longue), les limites de débit réelles (aucun 429 reçu), les fils (aucun dans ces salons), les sondages, les messages transférés, les épinglés, les interactions réelles.

**À refaire avant de se fier au rattrapage nocturne sur un gros serveur** : `dindon export ID_SALON --out /tmp/essai --reactions none` sur un salon de plusieurs milliers de messages, puis comparer au contenu de la base comme ci-dessus (ou `tools/compare_with_export.py` sur des messages écrits par le bot) ; essayer `--reactions all` et `--threads all` sur un salon qui en a.

## Mesures (faux Discord avec une latence par requête : ce que coûterait un réseau, **pas** la vitesse du vrai Discord)

`tools/bench_export.py 5000 100` (5 000 messages, 721 avec réactions, 100 ms par requête, plafond global de 40 requêtes/s) :

| Qui a réagi | Fils | Secondes | Requêtes |
| --- | --- | --- | --- |
| aucun | 6 | 6,6 | 116 |
| 7 derniers jours | 1 | 17,2 | 209 |
| 7 derniers jours | 6 | 8,3 | 209 |
| 30 derniers jours (**défaut**) | 6 | 14,1 | 514 |
| tous les messages | 1 | 84,9 | 837 |
| tous les messages | 6 | 21,4 | 837 |

Le fond du coût est *qui a réagi* (une requête par réaction) : 116 requêtes sans, 837 avec. Les fils en parallèle divisent le temps par 4 quand chaque requête prend 100 ms ; avec 25 ms par requête le plafond de 40 requêtes/s (celui de Discord) devient la limite et plus de fils n'aident plus. Sur un vrai Discord le débit sera borné par ses limites par route.

## 7. Le code d'origine

La source de l'exportateur d'origine (C#, avec les modifications faites pour Dindon) n'est **plus** dans ce dépôt. Elle est dans la branche locale `archive/avant-nettoyage` du dépôt parent (`strategio`, jamais poussée), pour qui voudrait comparer un comportement. Le format JSON v2 et ses cas particuliers sont décrits dans `contracts/`.
