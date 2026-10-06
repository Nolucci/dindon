# Les droits des personnes enregistrées (RGPD) : ce que Dindon fait, et ce qu'il ne fait pas

Ce document dit **ce qui est implémenté** pour respecter les droits des personnes dont Dindon garde les messages, et **ce qui reste à votre charge**. Ce n'est **pas un avis juridique** : le cadre (base légale, AIPD, mineurs, article 9 pour les opinions politiques) est discuté dans [DINDON_JURIDIQUE_ET_AMELIORATIONS.md](DINDON_JURIDIQUE_ET_AMELIORATIONS.md) et doit être validé par un juriste ou un DPO avant tout usage sur de vraies personnes, a fortiori hors d'un cercle privé.

**Niveau de preuve : testé avec des données et un faux Discord inventés (`tests/test_privacy.py`, `tests/test_ui_privacy.py`). Jamais essayé sur le vrai Discord** : en particulier l'enregistrement et l'affichage de la commande `/dindon` par Discord, et la réception de ses interactions, sont **non vérifiés**.

## 1. Ce qui est en place

| Droit / besoin | Ce que fait Dindon |
| --- | --- |
| **Opposition : ne plus être enregistré** | Un **registre** (`privacy_subjects`) garde l'identifiant Discord de la personne, rien d'autre. Il est lu **avant** toute écriture : le bot jette ses messages sans les garder en mémoire ; l'ingestion (export déposé, import, rattrapage nocturne, bot) retire de ce qu'elle va écrire ses messages, ses réactions, les mentions d'elle, ses rôles, son profil, et ce que d'autres ont cité d'elle dans une réponse. Un nouvel export ne la fait **pas** revenir. |
| **Effacement** | `erase` supprime : la personne, ses messages, réactions, mentions, noms et pseudos vus, ses liens avec les autres, **ce qui en a été tiré** (les conversations qui contiennent un de ses messages, donc leurs vecteurs et leur rattachement aux thèmes : ils sont refaits sans elle à la prochaine analyse), ce que d'autres ont **cité** d'elle en répondant, et ses traces dans les fichiers de `inbox/` et `archive/` (réécrits sans elle). Elle est ensuite au registre : elle ne revient pas. |
| **Accès** | `export` donne tout ce qui est gardé d'une personne (compte, noms, rôles, messages avec leur salon, réactions, mentions), en JSON. **Jamais** les messages des autres. |
| **Retrait aussi simple que l'accord, par commandes** | Chaque membre gère **ses propres données depuis Discord**, sans passer par vous : `/dindon mes-donnees` (un fichier avec tout ce qui est gardé de lui), `/dindon stop` (on ne l'enregistre plus ; ce qui est gardé reste, réversible), `/dindon effacer` (arrêt **et** effacement, définitif : un bouton de confirmation est demandé), `/dindon reprendre`. Les réponses ne sont visibles que de lui, il ne peut agir que sur **son** compte (l'identifiant vient de Discord), une demande par personne toutes les 15 s. Le registre vaut pour **tous** les serveurs que suit le bot. |
| **Information** | `/dindon info` (réponse immédiate), et le texte prêt à publier [INFORMATION-MEMBRES.md](INFORMATION-MEMBRES.md). `DINDON_CONTACT` est affiché aux membres. |
| **Limitation de la durée** | `DINDON_RETENTION_DAYS=N` : les messages de plus de N jours sont supprimés chaque jour (avec ce qui en dérive). `0` (défaut) : aucune limite. |
| **Traçabilité** | `privacy_log` : date, acte, identifiant, source, **nombres** (jamais un contenu). Visible dans l'interface. |
| **Traiter une demande reçue autrement** | Mêmes actes depuis l'interface (page **Vie privée**) et la ligne de commande : `dindon privacy list|stop|erase|release|export|purge`. |

Les actes (arrêt, effacement, reprise, purge) prennent le **même verrou** que l'ingestion : un import qui tourne ne peut pas réécrire en même temps ce qui est effacé.

## 2. Ce que cela ne couvre pas (à savoir)

- **Les sauvegardes** (`backups/`, 14 jours) contiennent encore la personne jusqu'à leur expiration. Elles ne sont jamais restaurées sur la base en service sans repasser les effacements du registre : **après une restauration, relancez `dindon privacy erase ID` pour chaque personne `erased` du registre** (`dindon privacy list`).
- **Le registre garde l'identifiant** de la personne : c'est nécessaire pour ne pas la réenregistrer. C'est la seule trace.
- **Ce que d'autres ont écrit sur elle** (« Alice a dit que… ») est leur message : il reste.
- **Les thèmes** (regroupements de mots de nombreuses personnes) ne sont pas recalculés à l'effacement ; leurs conversations sources le sont. Une nouvelle recherche de thèmes les refait.
- **Les copies hors de Dindon** : exports faits à la main ailleurs, captures de la page Thèmes (qui montre des extraits de vrais messages).
- **Une personne ne peut pas être « retrouvée » si elle ne s'identifie pas** : `/dindon stop` agit sur le compte qui l'écrit ; une demande reçue par un autre canal doit être vérifiée **par vous** (que la personne est bien celle du compte) avant d'effacer.
- **L'accord préalable** : Dindon n'en recueille pas (il enregistre ce que le bot peut lire). Pour des données révélant des opinions, l'avis juridique du document ci-dessus demande un **consentement explicite**. Ce n'est **pas** fait : tant qu'aucune analyse de positions n'existe (l'extraction n'est pas construite), seuls les messages, les liens et les thèmes sont traités.
- **Les mineurs** : aucune vérification d'âge.
- **L'AIPD** (analyse d'impact) : à rédiger par vous avant l'analyse de positions.
- **Un import d'historique plus ancien que `DINDON_RETENTION_DAYS`** est supprimé à la prochaine purge : il ne sert à rien d'en importer.
- **La lecture automatique** ([LECTURE-AUTOMATIQUE.md](LECTURE-AUTOMATIQUE.md)) des positions n'est possible qu'après avoir confirmé que les personnes sont informées ; cette confirmation est une case à cocher, **pas une vérification** : elle ne remplace ni l'information des membres, ni le consentement explicite que demande l'article 9, ni l'AIPD.
- **Les modifications et suppressions faites par les membres sur Discord** sont appliquées **dès qu'elles arrivent** (une suppression retire aussi ce qui en avait été déduit : conversations, positions, scores). Si le bot est coupé à ce moment-là, le rattrapage nocturne s'en charge ; les **sauvegardes** gardent le message jusqu'à leur expiration (14 jours).
- **Le jeton, `.env`, la base** : leur protection (disque chiffré, accès) relève de la machine.

## 3. Ce qui a été mesuré (données inventées, voir [MESURES.md](MESURES.md))

Serveur inventé de 300 000 messages et 5 000 personnes : effacer une personne moyenne **0,24 s**, la plus active (40 000 messages) **1,5 s**, sa copie **0,04 s** ; le registre ne change pas le temps d'un import (1 500 personnes : 637 ms contre 639 ms par fichier) ; purge de tout (300 000 messages, par lots de 20 000, liens refaits) **6 s**. **Le point lent est la réécriture des fichiers d'`archive/`** : 126 s pour 4,2 Go dont la personne est dans tous les fichiers (la plupart des personnes sont dans une fraction). Pour cela les commandes **répondent tout de suite** (Discord ne laisse que 3 s), puis donnent le résultat. Le bot tient **300 messages par seconde** sur 80 salons sans rien perdre (le vidage prend 4 s après le dernier).

## 3 bis. Les débats et la vérification sur Internet ([DEBAT.md](DEBAT.md))

**Ce qu'un débat garde d'une personne** : ses messages comptés (qui, quand, pas le texte, qui est dans les messages), **ses positions** (pour / ne sait pas / contre, dans l'ordre : les changements d'avis sont gardés), **ses votes Valide / Invalide sur les réponses de Dindon** (niveau `answer`), **les réponses que Dindon lui a faites** (l'affirmation, ce que Dindon a répondu sans source, les votes reçus), et, si la vérification est activée, **les affirmations de fait vues dans ses messages** avec leur verdict et leurs sources. Les positions sur un sujet politique sont des **opinions politiques** (article 9 du RGPD) : voir « ce qui reste à votre charge » plus bas.

**Ce qui est couvert** (testé, `tests/test_debate*.py`) : `/dindon stop` exclut la personne de tout (messages non comptés, pas de position, **messages jamais lus** pour la vérification, absente des statistiques, plus corrigée en public) ; `/dindon effacer` supprime ses messages comptés, positions, **affirmations et sources**, et **les corrections que Dindon avait publiées sur Discord à leur sujet sont supprimées de Discord** par le bot ; `/dindon mes-donnees` donne ses positions, messages comptés et affirmations vérifiées avec leurs sources ; une suppression ou une modification d'un message **retire ses affirmations et la correction publiée** (celle-ci est supprimée de Discord) ; la durée de conservation (`DINDON_RETENTION_DAYS`) supprime les débats terminés ; retirer le bot d'un serveur supprime ses débats.

**Ce qui sort de la machine** quand la vérification est activée : une courte **phrase de recherche neutre**, écrite à partir de l'affirmation seule (jamais le message, jamais un nom ou un identifiant), envoyée à un service de recherche et par lui aux moteurs qu'il interroge ; la **lecture** de pages (les sites voient l'adresse IP de la machine). **Rien d'autre** (un test lit le code et échoue si un module de plus peut ouvrir une connexion : `tests/test_outbound.py`). La vérification est **désactivée par défaut** ; les membres en sont informés par `/dindon info` et dans le message de lancement de chaque débat vérifié dès qu'elle est active. **Dans un salon (fil décoché), Dindon lit tous les messages écrits tant que le débat est ouvert**, même ceux qui n'ont rien à voir avec le sujet : le message de lancement le dit, et c'est pourquoi un fil est proposé à part.

**Ce qui reste à votre charge** : (1) **informer les membres avant** de lancer un débat (le texte est dans [INFORMATION-MEMBRES.md](INFORMATION-MEMBRES.md)) ; (2) l'**analyse d'impact (AIPD)** : positions politiques et vérification d'affirmations de personnes identifiables ; (3) **l'accord préalable** pour des données qui révèlent des opinions (Dindon n'en recueille pas : participer à un débat et cliquer sur un bouton n'est pas un accord écrit) ; (4) ce que Dindon a **publié et qui n'est pas une correction** (le message de statistiques de fin) **reste sur Discord** : seuls les modérateurs du serveur peuvent le supprimer ; (5) les copies faites par des membres (captures) ; (6) les **mineurs** : aucune vérification d'âge.

## 4. Mise en service (à faire une fois)

1. Choisir `DINDON_RETENTION_DAYS`.
2. **Réinviter le bot** avec le nouveau lien (page **Inviter le bot**) : il demande maintenant aussi `applications.commands`, nécessaire à `/dindon`. Un bot invité avant n'a pas cette portée.
3. `docker compose --profile bot up -d --build`. Au démarrage, le bot enregistre la commande `/dindon` (le journal du bot dit `the command /dindon is registered`). Discord peut mettre quelques minutes à l'afficher.
4. Publier [INFORMATION-MEMBRES.md](INFORMATION-MEMBRES.md) sur le serveur **avant** d'enregistrer : les gens doivent savoir qu'ils sont enregistrés et comment arrêter.
5. Essayer vous-même, avec un compte de test, `/dindon info`, `/dindon mes-donnees`, `/dindon stop`, `/dindon reprendre` puis `/dindon effacer` (bouton compris) : c'est la seule vérification qui compte, et elle n'a jamais été faite. Si la commande n'apparaît pas : le bot a-t-il été réinvité (étape 2) ? la ligne `the command /dindon is registered` est-elle dans `docker compose logs bot` ?
