# Mettre le bot en production : la liste à suivre

Écrite le 5 octobre 2026. **Le contrôle automatique** : `docker compose exec app dindon preflight` (ou `.venv/bin/dindon preflight` depuis le dossier du projet). Il ne modifie rien, ne poste rien et n'affiche ni le jeton ni un mot de passe ; il dit `[BLOQUANT]` pour ce qu'il faut régler avant, `[à voir]` pour ce qu'il faut décider. Code de sortie 1 s'il y a un bloquant. À relancer après chaque changement de `.env`, et avant d'inviter le bot sur un nouveau serveur.

## 1. Ce que le contrôle vérifie (et qui a été vérifié le 5 octobre sur votre instance)

| Groupe | Vérifié | Résultat le 5 octobre |
| --- | --- | --- |
| Mots de passe | interface et base : pas un mot d'exemple, au moins 12 caractères | **ok** (24 et 32 caractères) |
| Jeton | c'est celui d'un **bot** (pas d'un compte : interdit par Discord) | **ok** |
| Droits du bot | « Message Content Intent » activé ; bot **privé** ; dans chaque serveur suivi : peut voir les salons et lire l'historique, et **rien d'autre de sensible** (ni administrateur, ni bannir, ni gérer les rôles/messages) | **ok** sur les 2 serveurs |
| Commande `/dindon` | enregistrée chez Discord | **ok** |
| Horloge | à moins de 30 s de celle de Discord | **ok** |
| Base | migrations appliquées, dossiers `inbox/` et `archive/` inscriptibles, place libre ≥ 5 Go | **ok** (75 Go) |
| Bot | vivant et connecté (signe de vie < 2 min) | **ok** |
| Conservation (`DINDON_RETENTION_DAYS`) | une durée est fixée | à voir : illimitée |
| Serveurs suivis (`DINDON_GUILD_IDS`) | une liste, pas « tous » | à voir : « all » |

## 2. Ce qui a été vérifié à la main le même jour

- **Aucun message manqué en direct** : pour chaque salon des 2 serveurs, j'ai comparé le dernier message que Discord annonce à ce que la base contient. Le salon où le bot reçoit les messages est à jour ; les 8 autres salons ont des messages **plus anciens que la première connexion du bot** (le plus récent date du 29 septembre) : ce n'est pas une perte, c'est l'**historique qui n'a jamais été importé** (voir §4).
- **Redémarrage du bot** : revenu « healthy » en 37 s, une session, aucune coupure comptée.
- **Journaux** : ni le jeton ni le mot de passe n'y figurent (0 occurrence dans ceux de l'application et du bot).
- **Secrets** : `.env` en lecture seule pour vous (`-rw-------`) et ignoré par Git.
- **Conteneurs** : `app` et `bot` ne tournent plus en root ; le bot a un contrôle de santé Docker.
- **Machine** : sur secteur, la mise en veille automatique est désactivée (un bot sur un ordinateur en veille ne reçoit rien) ; disque chiffré (FileVault) ; **sauvegarde de la base chaque nuit** (3 sauvegardes), restauration essayée le 4 octobre.
- **Mémoire du bot** : il ne garde ni cache de messages, ni liste de membres (`max_messages=None`, `chunk_guilds_at_startup=False`) : sa consommation ne grandit pas avec la taille du serveur.
- **Charge** : mesurée avec un faux Gateway à 300 messages par seconde sur 80 salons, aucune perte (un serveur très actif de plusieurs dizaines de milliers de membres produit bien moins).
- **Tests** : toute la suite (493 tests) passe ; elle ne prouve que le comportement face à des faux Discord, pas face à Discord (voir §5).

## 3. Avant d'inviter le bot sur le serveur de production (à faire par vous)

1. **Plus rien de bloquant** si `dindon preflight` dit « PRESQUE » ou « OUI » : il n'y a plus de contact à renseigner, `/dindon info` explique comment les données sont gérées.
2. **Fixer `DINDON_RETENTION_DAYS`** (par exemple 365) ou assumer « sans limite », et **le dire aux membres**.
3. **Lister le serveur dans `DINDON_GUILD_IDS=<identifiant>`** au lieu de « all » : un serveur ajouté par erreur ne sera pas enregistré. (Identifiant : mode développeur de Discord > clic droit sur le serveur > Copier l'identifiant.)
4. **Informer les membres avant que le bot ne lise** : publier le texte de [INFORMATION-MEMBRES.md](INFORMATION-MEMBRES.md) dans un salon lu de tous (remplacer les crochets, relire). Le texte modèle dit « aucune analyse de vos opinions » : si vous comptez utiliser l'analyse par l'IA, **changez cette phrase** et lisez §2 de [CONFORMITE.md](CONFORMITE.md) (accord explicite, mineurs, analyse d'impact) : ce n'est pas fait.
5. **Inviter le bot avec le lien de la page « Inviter le bot »** (droits : voir les salons + lire l'historique, rien d'autre ; portée `applications.commands`). Le bot n'a pas besoin d'être administrateur.
6. **Relancer `dindon preflight`** : il doit dire « OUI » ou « PRESQUE » sans bloquant.

## 4. Les premières heures

1. **Essayer les commandes avec votre propre compte** sur le serveur : `/dindon info` (doit expliquer comment les données sont gérées, avec la durée de conservation), `/dindon card @quelqu'un` (une carte s'affiche dans le salon), `/dindon mes-donnees` (un fichier), puis `/dindon stop` et `/dindon reprendre`. **Jamais essayé sur un vrai serveur par un membre** : c'est le test qui compte le plus (5 minutes).
2. **Écrire un message de test** dans un salon et vérifier qu'il apparaît sur la carte en quelques secondes (page Système : le bot doit être « connecté »).
3. **L'historique n'est pas importé tout seul.** Le bot ne reçoit que les nouveaux messages. Pour l'ancien : `docker compose exec app dindon backfill --guild <id>` (ou la fenêtre « Importer »). Sur un gros serveur c'est long (les réactions coûtent une requête chacune) ; essayez d'abord sur **un seul salon** (`--channel nom`) et regardez le temps et les erreurs. **L'exportateur n'a jamais été vu sur un gros salon ni avec les vraies limites de débit de Discord.**
4. Le **rattrapage nocturne** (03 h UTC) relit les 7 derniers jours : réactions, aperçus de liens, et ce qui a été manqué pendant une coupure. Les **modifications et suppressions** sont appliquées en direct par le bot ; testez-les : écrivez un message, modifiez-le, supprimez-le, et regardez la carte.
5. **Regarder la page Système** le lendemain : bot connecté, nombre de coupures, erreurs de collecte, place disque.

## 5. Ce qui n'est pas couvert (à connaître)

- **Les réactions** ne sont pas reçues en direct (le rattrapage nocturne les ajoute, sur 7 jours).
- **Une coupure du Gateway** fait manquer les messages écrits pendant ce temps jusqu'au rattrapage (la page Système compte les coupures).
- **L'ordinateur** : s'il s'éteint ou perd Internet, le bot est hors ligne. Il n'y a qu'une machine.
- **L'IA** n'a jamais tourné sur de vraies données ; ne la lancez pas avant d'avoir informé les membres (§3.4).
- **Annuler** : `docker compose --profile bot stop bot` arrête de lire. Il n'existe **pas de commande pour effacer d'un coup tout un serveur** : on efface par personne (`dindon privacy erase`, ou `/dindon effacer` par chaque membre), ou on fixe `DINDON_RETENTION_DAYS` à une durée courte (la purge supprime ce qui est plus vieux), ou on recrée la base. Les sauvegardes gardent les données 14 jours de plus.
