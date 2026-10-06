# Débat : `/dindon debat <sujet>`

Un débat encadré sur Discord : une personne lance `/dindon debat sujet` et choisit les paramètres dans une fenêtre ; Dindon ouvre le débat là où elle l'a demandé (**un fil seulement si elle le demande**, sinon le salon lui-même) ; chacun prend position avec trois boutons ; **il n'y a ni limite de temps ni vote** : le débat se termine avec un bouton, ou tout seul après un silence ; des statistiques le closent et, **si vous l'activez**, les affirmations de fait sont vérifiées sur Internet, avec des sources sur lesquelles on peut cliquer.

Ce document est la référence de cette fonction. **État au 2026-10-06 : tout est construit et testé avec un Discord, un modèle (pour les tests) et un Internet simulés. La lecture des messages et la vérification de bout en bout ont été mesurées avec le vrai modèle et le vrai Internet (voir « Mesure »). Rien n'a jamais tourné sur un vrai Discord.**

## Ce qui est demandé, et où c'est fait

| Demandé | Où |
|---|---|
| `/dindon debat sujet` : **une fenêtre** où la personne choisit les paramètres du débat | fenêtre Discord (sujet, contexte, fil ou non, vérification, silence) ; rien n'est créé avant qu'elle l'envoie |
| **Si on ne sait pas quoi débattre** : choisir un axe, et Dindon pose une question à laquelle les gens répondent | liste « axe » de la fenêtre (les axes actifs de Dindon) : la question de l'axe devient le sujet, et on répond par l'un de ses deux pôles |
| Un fil **seulement si on le demande**, **plus de limite de temps** | case « Ouvrir un fil » (**cochée par défaut**) ; décochée, le débat a lieu dans le salon ; aucun minuteur |
| Le fil **dans le forum des débats** du serveur, pour ne pas polluer le salon | `/dindon forum` (voir « Un forum pour les débats ») : chaque débat devient un post du forum, avec ses étiquettes |
| Dindon **répond sans aller chercher sur Internet quand il peut**, avec **Valide / Invalide** sous sa réponse ; plus d'Invalide : il cherche sur Internet | voir « Répondre d'abord, chercher ensuite » : niveau `answer` |
| Une fois la fenêtre remplie, Dindon fait un message, puis analyse tous les messages et intervient au cas où | message de lancement à trois boutons ✅ ❔ ❌ (compteurs à jour) ; lecture de chaque message du lieu du débat tant qu'il est ouvert (une file durable, si la vérification est activée) |
| Fin du débat | bouton « Terminer le débat » (la personne qui l'a lancé, ou un modérateur) **ou** fin toute seule si personne n'écrit pendant le silence choisi |
| À chaque infox, Dindon intervient et redonne les vraies informations, **avec des sources cliquables** | correction publique avec boutons-liens et citation exacte (mode `live`, verrouillé par une précision mesurée) |
| Il cherche sur Internet **sans aller chercher plus**, **impartial**, vers la vérité vraie ; rien d'autre ne sort | les trois principes, imposés par la structure du code |
| Statistiques : les personnes, leurs positions, leur nombre de messages, leurs messages phares, les messages vérifiés | message de fin paginé (boutons Précédent / Suivant), page **Débats** de l'interface avec toutes les preuves |

*Première version (2026-10-05) : un fil systématique, une limite de temps, un vote pour continuer ou arrêter. Remplacée le 2026-10-06 sur votre demande par ce qui précède.*

*Dans votre demande, « poulet » a été lu comme Dindon.*

## Décisions prises

La personne qui commande a répondu « fais selon ce qui te semble le plus pratique et précis » : les recommandations de l'audit sont retenues. Chacune se change sans refaire le reste.

| Sujet | Décision | Pourquoi |
|---|---|---|
| Les paramètres | Une **fenêtre** (fenêtre modale de Discord) montrée à la personne qui a fait la commande : **sujet** (celui qu'elle a tapé, modifiable, **facultatif si elle choisit un axe**), **contexte** (facultatif, publié dans le message de lancement), **axe** (liste, facultative), **options** (une seule rubrique : « Ouvrir un fil », cochée ; « Vérifier les affirmations », cochée, **seulement si vous avez activé la vérification**, et elle ne peut que la désactiver, jamais aller au-delà de votre réglage), **« Fin automatique après un silence de »** (1 h, 6 h, **24 h**, 3 j, 7 j) | Vous aviez choisi : sujet et contexte, vérification, temps ; l'axe a été ajouté le 2026-10-06. Discord limite une fenêtre à **5 champs** : le fil et la vérification partagent donc une rubrique |
| « **Temps** » | Lu comme **le silence après lequel le débat se termine tout seul** (il n'y a plus de limite de temps) ; 24 h par défaut. **À corriger si vous pensiez à autre chose** | Votre réponse libre était « Temps » ; avec « Bouton + fin si personne n'écrit », c'est la lecture qui tient |
| Ce qui n'est pas dans la fenêtre | Les positions restent **pour / ne sait pas / contre** (pour un axe : ses deux pôles, voir plus bas) ; le mode des corrections (observation ou publiques) reste celui de votre réglage `DINDON_DEBATE_CHECKS` | Vous n'avez pas choisi « intitulé des choix » ni « corrections publiques » |
| Un **axe** au lieu d'un sujet | Pour ceux qui ne savent pas quoi débattre : la liste de la fenêtre montre **les axes actifs de Dindon** (21 aujourd'hui ; jusqu'à 25, dans l'ordre de la page Axes ; chacun avec ses deux pôles en description). Le sujet est alors **la question de l'axe** (`axes.question`, déjà écrite et relue dans `docs/AXES.md`), précédée de « Question posée par Dindon · axe « … » ». **On y répond avec les deux pôles de l'axe** (le pôle −1 à gauche, le pôle +1 à droite, « Ne sait pas » au milieu) à la place de pour / ne sait pas / contre, et les statistiques les reprennent | Pour / contre n'a pas de sens sur « faut-il privilégier l'ordre ou la liberté ? » ; les deux pôles répondent à la question |
| Les deux pôles ne sont **jamais** ✅ / ❌ | Ce sont 🔵 et 🟠 : une coche et une croix diraient qu'un pôle est le bon | Impartialité : Dindon ne prend pas parti, même dans ses boutons |
| Un sujet écrit gagne sur l'axe | Si la personne écrit un sujet **et** choisit un axe, le sujet est gardé et l'axe ignoré (la liste le dit) ; ni l'un ni l'autre : la personne en est informée et rien n'est créé. Un axe désactivé entre-temps est refusé | Le texte tapé est ce que la personne veut le plus sûrement |
| Une copie, pas un lien | Le débat garde **une copie** de ce qu'il a affiché (code, nom, pôles : colonne `debates.axis`) : renommer ou éteindre un axe ne change pas les boutons d'un débat en cours | Un débat ne doit pas changer de sens en route |
| Où a lieu le débat | **Fil coché (par défaut, depuis le 2026-10-06 : vous l'avez demandé)** : Dindon crée un fil public sous le salon, ou un post dans le forum des débats si un modérateur en a réglé un (`/dindon forum`). **Fil décoché** : le débat a lieu **dans le salon**, et Dindon y lit **tous** les messages écrits tant qu'il est ouvert (le message de lancement le dit). Demandé **depuis un fil** : il a lieu dans ce fil, sans en créer un autre | Vous vouliez un fil seulement à la demande |
| Un seul débat par salon | Un débat dans un salon (fil décoché) empêche d'en ouvrir un second *dans ce salon* tant qu'il est ouvert (deux débats compteraient les mêmes messages) ; des fils, eux, peuvent coexister | |
| Fin du débat | **Bouton « Terminer le débat »** : la personne qui l'a lancé, ou un **modérateur** (administrateur, ou droit de gérer le salon, le serveur, les messages ou les fils) ; **ou le silence** choisi ; ou aucun participant | Votre réponse : « Bouton + fin si personne n'écrit » |
| Qui peut lancer | Tout le monde ; **un débat ouvert par personne, trois par serveur** | Chaque débat occupe l'IA locale, sur une machine partagée |
| Sources des faits | **Remplacée le 2026-10-06** (voir « Vérification sur Internet » plus bas) : l'IA cherche et vérifie **sur Internet**, et les gens cliquent sur les sources. *Ce qui était décidé le 2026-10-05 : une base de faits locale, sans recherche web, pour tenir la promesse « rien n'est envoyé à un service extérieur ».* **Reste vrai : jamais de chiffre venu du modèle seul** | Un modèle local n'a pas de source fiable |
| Démarrage des corrections | **Mode observation d'abord** (Dindon analyse et note, ne publie rien), mesure de la précision sur un jeu annoté, puis activation | On ne publie pas de corrections avant d'avoir mesuré qu'elles sont justes |
| Messages du débat sur la carte du serveur | Gardés, comme le reste du serveur | Les personnes sont informées par `/dindon info` |
| Personnes qui ont fait `/dindon stop` ou `effacer` | **Exclues du débat** : leurs messages ne sont pas analysés, elles ne peuvent ni prendre position ni lancer un débat | Leur demande prime |
| Fin du lieu | Un fil **créé par Dindon** est archivé après les statistiques (le verrouiller demanderait la permission « gérer les fils »). **Jamais** un salon, ni un fil qui existait déjà | |

## Un forum pour les débats (D9)

Beaucoup de serveurs rangent leurs débats dans un **forum** (un salon de type forum, où chaque débat est un *post* avec des **étiquettes** : Économie, Religion, Philosophie…). Un modérateur dit **une fois** à Dindon lequel :

- `/dindon forum salon:#Débats` (le choix de la liste ne propose que des forums), avec, si le forum l'exige ou si on le veut, `etiquette:Politique` (celle que porte **chaque** débat). Sans option, la commande **montre** le réglage ; `retirer:Oui` remet les débats dans des fils sous le salon. **Réservé aux modérateurs** (administrateur, ou droit de gérer le salon, le serveur, les messages ou les fils) ; la réponse n'est vue que par la personne.
- Ensuite, un débat ouvert **dans un fil** (case cochée) est créé **dans le forum**, en un seul appel à Discord : le post et son premier message (le message de lancement, avec les boutons) naissent ensemble. Plus rien ne se crée sous le salon où la commande a été tapée. Sur un débat ouvert depuis un axe, Dindon ajoute les étiquettes du forum dont **tout le nom** est fait de mots du nom de l'axe (« Religion » pour « Religion et État », « International » pour « Commerce international ») ; il ne devine rien d'autre et n'applique jamais, de lui-même, une étiquette réservée aux modérateurs. Cinq étiquettes au plus.
- Un forum qui **exige** une étiquette n'est pas accepté sans `etiquette:` : Dindon liste celles du forum. Les étiquettes sont relues **au moment de créer le débat**, pas gardées en mémoire (une étiquette renommée ou supprimée ferait refuser le post).
- Si le forum ne répond pas (supprimé, plus accessible, étiquette introuvable), le débat s'ouvre **dans un fil sous le salon** et la personne en est prévenue. Un débat « dans le salon » (case décochée) ou lancé depuis un fil existant **ignore** le forum. À la fin, le post est archivé comme un fil.
- Ce qui est gardé : le salon, son nom et l'étiquette choisie, par serveur, dans `runtime_settings` (clé `debate_forum.<serveur>`) ; rien d'une personne. Retirer le bot d'un serveur l'efface. Le bot a besoin, dans le forum, de : voir le salon, envoyer des messages (créer des posts), envoyer des messages dans les posts : ce sont des droits de l'invitation actuelle.
- La fenêtre le dit : la case « Ouvrir un fil » précise « Dans le forum « Débats » ; sinon ici… ».
- **Le message de lancement tient en deux ou trois lignes** : le sujet, puis « Prenez position avec les boutons (modifiable). Fin : « Terminer le débat » (lanceur ou modérateur) ou après 1 jour sans message », puis **une ligne** sur ce que fait Dindon (🔎 …) avec « Détails : `/dindon info` » ; l'avertissement « Dans ce salon, Dindon lit tous les messages » s'ajoute quand le débat a lieu dans le salon. Le texte complet reste dans `/dindon info`.

## Répondre d'abord, chercher ensuite (D10)

**Demandé** : *« Si Dindon peut répondre sans aller chercher sur Internet, qu'il le fasse ; sous sa réponse, un emoji Valide et Invalide ; s'il y a plus de Valide, il ne va pas plus loin ; s'il y a plus d'Invalide, il approfondit et cherche sur Internet. »* Et : *« je peux dire n'importe quoi, Dindon n'intervient pas »*. **Cause de ce dernier point : la vérification est désactivée par défaut** (`DINDON_DEBATE_CHECKS=off`, rien dans le `.env` à l'époque) ; même en `observe`, rien n'est publié.

**Lu ainsi** (*à confirmer : « sous son message » a été lu comme « sous le message de Dindon »*) : Dindon répond d'abord avec **son IA locale, sans Internet** ; les participants jugent **sa réponse** ; l'Internet n'intervient que si elle est rejetée.

### Les niveaux de `DINDON_DEBATE_CHECKS`

| Niveau | Ce que fait Dindon | Ce qui sort de la machine |
|---|---|---|
| `off` (défaut) | rien n'est lu | rien |
| `observe` | vérifie **chaque** affirmation sur Internet, **note** dans la base, ne publie rien (comme avant) | une phrase de recherche neutre par affirmation |
| `answer` | **répond d'abord, sans Internet**, quand il est **certain** qu'une affirmation est fausse ; les participants jugent ; Internet seulement si plus d'Invalide. Marche **sans** service de recherche (il ne pourra simplement pas chercher, et le dit) | rien tant que personne n'a jugé la réponse invalide ; ensuite une phrase de recherche neutre |
| `live` | `answer`, **et** les corrections que les sources de confiance font d'elles-mêmes (l'ancien mode ; il demande une précision mesurée : sans elle, le bot reste à `answer`) | idem |

### Le déroulement (testé : `tests/test_debate_answers.py`, `tests/test_debate_local.py`)

1. **Lecture à l'aveugle** de chaque message (inchangée) : les affirmations de fait.
2. **Pour chaque affirmation, le modèle local seul** (`debate/local.py`, aveugle : l'affirmation, rien d'autre) dit `true`, `false` ou `unsure`, avec son degré de certitude. **Il se tait** (`unsure`) quand : sa certitude déclarée est sous 90, l'affirmation **compare un chiffre à un seuil** (« plus de 50 % », « inférieur à 1 000 euros » : il n'est même pas interrogé), sa « correction » **garde tous les chiffres de l'affirmation**, ou elle contient une adresse, un crochet, une mention. Il ne dit jamais « vrai » en public : une affirmation exacte est seulement notée.
3. **Certain qu'elle est fausse** : Dindon répond **sous le message** (une réponse au message, sans nommer ni mentionner personne) : l'affirmation, la phrase exacte qu'il connaît, et en clair : **« sans recherche sur Internet et sans source : elle peut se tromper »**. Dessous : **✅ Valide · n** et **❌ Invalide · n**.
4. **Pas sûr** : l'affirmation part sur Internet comme avant et est **notée** (publiée seulement en `live`, derrière le verrou).
5. **Les participants jugent sa réponse** (un vote chacun, modifiable ; l'auteur du message peut voter ; jamais quelqu'un qui a demandé l'arrêt, dont le vote déjà donné ne compte plus ; plus de vote quand le débat est terminé). Les compteurs sont remis à jour sur le message (au plus toutes les 5 secondes).
6. **Plus de Valide, ou autant** : rien de plus, jamais. **Plus d'Invalide que de Valide** (strictement, à tout moment) : Dindon cherche sur Internet, **une seule fois**, avec le budget et les sources de confiance de toute vérification (2 recherches, 3 pages, citation vérifiée), prise sur le même quota horaire que les autres vérifications (20 par heure et par débat). Puis il **réécrit son propre message** avec ce qu'il a trouvé, **quel que soit le résultat** : « les sources contredisent : ma réponse se confirme », « les sources confirment l'affirmation : **ma réponse était fausse** », « en partie », « les sources se contredisent », « pas de source de confiance qui tranche », ou « je ne peux pas chercher sur Internet (aucun service de recherche) » ; avec les sources à cliquer et leurs citations exactes, et sa première réponse rappelée. Les boutons Valide / Invalide disparaissent.
7. **Mêmes garde-fous que les corrections** : une réponse par affirmation, publiée une seule fois même après un redémarrage, espacée de 20 secondes, 10 par heure et par débat au plus, jamais plus de 30 minutes après l'affirmation, jamais pour quelqu'un qui a demandé l'arrêt, retentée avec des attentes croissantes puis abandonnée après 5 essais, **retirée de Discord** si le message est modifié ou supprimé ou si son auteur est effacé.
8. **Statistiques** : la page de résumé dit combien de réponses Dindon a données, combien de votes Valide / Invalide, combien de recherches ont suivi ; la page Débats liste ces réponses avec les votes.

### Ce qu'on sait de la fiabilité du modèle seul (mesuré le 2026-10-06)

`python tools/measure_claims.py local` : `qwen3:14b` répond **seul**, sur les 37 affirmations du jeu de référence (*mes étiquettes, non vérifiées par un humain ; petit échantillon*).

| | « faux » dit | justes | à tort | « vrai » dit d'une fausse |
|---|---|---|---|---|
| Première version, moitié `dev` | 11 | 9 | **2**, sur des affirmations vraies | 0 |
| Première version, moitié `test` (mesurée une fois, avant tout réglage sur elle) | 7 | 6 | **1**, sur une affirmation vraie (un seuil mal comparé) | 0 |
| Version actuelle (certitude ≥ 90, chiffres répétés, **seuils non traités**), ensemble | **9** | **8** | **1**, sur une affirmation vraie (une date : 1944 ou 1945) | 0 |

**Lecture honnête** : quand l'IA locale seule dit « faux », elle se trompe **encore une fois sur neuf environ**, et chaque erreur est **une accusation à tort d'une affirmation vraie** (sur 9 réponses : beaucoup trop peu pour une précision fiable). Elle se prononce sur **62 %** des affirmations tranchables, **repère la moitié** des fausses, et se tait sur 100 % de celles qu'on ne peut pas trancher. **C'est pourquoi sa réponse est étiquetée « sans source, elle peut se tromper », jugée par les participants et corrigée par Internet si elle est rejetée.** Le garde-fou « seuils » a été ajouté après avoir vu une erreur de `dev` **et** une de `test` : la dernière ligne n'est donc **pas** une mesure indépendante. Le seuil de 90 % de précision (`DINDON_DEBATE_MIN_PRECISION`) ne s'applique **pas** à ce niveau : il ne verrouille que les corrections que les sources font d'elles-mêmes.

### Pourquoi un message peut rester sans réponse de Dindon

Une affirmation fausse n'obtient une réponse que si elle passe **toutes** ces portes ; chacune se tait plutôt que de se tromper :

1. **Le débat vérifie** (case cochée dans la fenêtre) et le niveau n'est pas `off`.
2. **La lecture** y trouve une affirmation de fait (pas une opinion, une question, une personne privée) : message d'au moins 16 caractères.
3. **L'IA locale est certaine** (certitude déclarée ≥ 90) que c'est faux, et propose une correction qui **change** quelque chose (pas les mêmes chiffres).
4. L'affirmation **ne compare pas un chiffre à un seuil** (« plus de 50 % »).

Essai réel du 2026-10-06 (`qwen3:14b`) : **réponse** à « La Terre est plate », « Paris est la capitale de l'Allemagne », « La Révolution française a eu lieu en 1889 », « Il y a 10 continents sur Terre », « L'eau bout à 50 degrés au niveau de la mer » ; **silence** sur « 90% des élèves ne vont pas à l'école » (le modèle n'est pas sûr : quel pays ? quelle période ?). Sans service de recherche, une affirmation dont l'IA locale n'est pas sûre **reste sans réponse** ; avec un service (SearXNG), elle est cherchée sur Internet mais **seulement notée** tant que le niveau n'est pas `live` (verrou de précision).

### À savoir

- **C'est une décision de ma part, à confirmer** : les réponses sans source de l'IA locale sont **publiques** dès le niveau `answer`, sans passer par le verrou de précision mesurée. Le verrou garde la même fonction qu'avant (corrections automatiques par des sources) ; ce qui tient lieu de garde-fou pour les réponses locales, c'est le jugement des participants et leur étiquette « sans source ».
- Le texte aux membres change selon le niveau (`texts.NOTICE_ANSWER`, `NOTICE_LOCAL`) : **écrit par moi, à valider**.
- Sans service de recherche, un débat en `answer` ne fait rien sortir de la machine ; avec, la phrase de recherche neutre ne sort que si les participants rejettent une réponse (ou en `observe` / `live`, comme avant).
- `dindon preflight` dit le niveau réel, et la page Débats aussi.

## Vérification sur Internet

**Demandé** : que l'IA vérifie sur Internet ce qu'une personne affirme, et que les gens qui débattent puissent aller voir les sources en cliquant dessus. Cela remplace la base de faits locale. **Trois principes, donnés par la personne qui commande**, que le code fait respecter autant que possible par sa structure :

1. **Périmètre : vérifier, sans chercher plus.** L'IA ne sort sur Internet que pour vérifier ce qu'une personne a dit. Elle ne cherche ni le contexte, ni les sujets voisins, ni les personnes.
2. **Impartialité : elle ne prend pas parti.** Elle n'est ni pour ni contre dans le débat. Son seul objectif est la vérité vraie, quand elle est établissable ; sinon elle dit qu'elle ne l'est pas.
3. **Rien d'autre ne sort.** Hors cette vérification, rien ne quitte la machine, sauf ce que Dindon écrit sur le serveur Discord où le bot est branché.

### 1. Le périmètre, tel qu'il est tenu

- **Une affirmation, un budget** (`debate/scope.py`, testé) : au plus **2 recherches** et **3 pages lues** par affirmation, une recherche ratée comptée, aucune nouvelle tentative cachée. Les pages lues sont **uniquement celles que la recherche a renvoyées** : jamais une adresse écrite par un membre dans un message, jamais un lien trouvé dans une page, jamais une adresse inventée par le modèle. Rien n'est parcouru de page en page. Une recherche vide n'envoie rien.
- **Ce qui n'est pas vérifié sur Internet** (décidé par la lecture du message, avant toute recherche) : les opinions, jugements de valeur, prévisions, questions et plaisanteries ; **toute affirmation qui porte sur une personne privée** (un membre du serveur, un inconnu), ou qui contient des données personnelles. Seuls des faits publics (chiffres, dates, événements, lois, propos publics de personnalités) sont vérifiés.
- **Rien ne se déclenche sans affirmation** : pas de recherche hors d'un débat ouvert, pas de veille, pas de recherche « pour comprendre le sujet ».
- **Les liens que les membres écrivent ne sont pas ouverts** (*choix par défaut, à confirmer par vous*) : l'affirmation est vérifiée de façon indépendante, auprès de sources de confiance. Ouvrir le lien d'un membre enverrait l'adresse de cette machine à un site choisi par lui.
- **Un compte rendu en chiffres** (`Lookup.spent()`) : combien de recherches, combien de pages, jamais leur contenu.

### 2. L'impartialité, telle qu'elle est tenue (testée)

- **Aveugle** : le modèle qui lit un message reçoit **le texte de ce message et rien d'autre** : ni l'auteur, ni sa position, ni les camps du débat, ni les autres messages. Celui qui rend le verdict reçoit **l'affirmation et les passages vérifiés**, rien de plus. Un test vérifie que les consignes envoyées au modèle ne contiennent aucun nom, aucune position, aucun camp.
- **Même exigence dans les deux sens** : « confirmé » demande la même chose que « contredit » (une source de confiance ET une citation vérifiée), et les deux sont notés. Aucune affirmation n'est vérifiée plus ou moins facilement selon son camp.
- **Vocabulaire du verdict** : *confirmé*, *contredit*, *en partie* (vrai à une autre date, ou incomplet), *contesté* (des sources de confiance se contredisent) et *non vérifiable*. En cas de désaccord entre sources, ou de silence, Dindon **ne tranche pas** et le dit. Chaque verdict donne la **période ou la date du chiffre** et la date de la page : une affirmation sur « maintenant » est comparée au chiffre le plus récent.
- **Même modèle de message pour tous** : « Affirmation vérifiée : « … ». Ce que disent les sources : « … » + les liens. » Aucun adjectif, jamais « X ment », jamais un avis sur la question débattue.
- **Une correction publique seulement quand c'est *contredit*** (comme demandé au départ : « à chaque fois qu'une infox est détectée »). Les affirmations *confirmées*, *en partie*, *contestées* ou *non vérifiables* ne déclenchent aucun message mais sont **toutes notées et comptées dans les statistiques de fin, par position**, pour que le tableau soit équilibré et visible : (*choix par défaut ; on peut aussi publier les confirmations*).
- **Un contrôle de parité** : les statistiques de fin et la mesure (D4c) donnent, par position, combien d'affirmations ont été vérifiées, confirmées, contredites, non tranchées. La mesure comprend des **paires d'affirmations équivalentes mais favorables à des camps opposés** : elles doivent recevoir la même catégorie de verdict, et les erreurs sont comptées camp par camp.

### 3. Ce qui sort de la machine, et rien d'autre

**Pour vérifier une affirmation** : une courte phrase de recherche, neutre, écrite par le modèle à partir de l'affirmation seule (jamais du message, jamais du nom de l'auteur), nettoyée de toute mention, adresse, e-mail, téléphone et identifiant Discord (`search.scrub_query`), envoyée à un service de recherche et, par lui, aux moteurs qu'il interroge ; plus, pour le service de fact-checking, la clé d'API. Dindon **lit** ensuite au plus 3 des pages renvoyées, et les sites contactés voient l'adresse IP de cette machine et le nom « DindonBot ».

**Tout le reste reste ici** : les messages, les positions, les statistiques, les affirmations notées. Ni télémétrie, ni service tiers, ni copie. Le modèle d'IA est local. **C'est un test qui le garantit** (`tests/test_outbound.py`) : il liste les neuf modules du programme qui peuvent ouvrir une connexion, chacun avec son but (l'IA locale, Discord, et les deux modules de vérification), et **échoue si un dixième apparaît** sans qu'on l'ait ajouté exprès. Le moteur du débat, ses règles et son stockage n'en font pas partie.

**Dit aux membres dès que c'est activé (texte validé le 2026-10-06)** : dans `/dindon info` (en deuxième message, car le premier approche la limite de 2 000 caractères de Discord), dans le message de lancement de chaque débat dont les affirmations sont vérifiées, et dans `INFORMATION-MEMBRES.md` :

> **Vérification des affirmations (débats).** Pour vérifier ce qu'une personne affirme dans un débat, Dindon envoie à un moteur de recherche une phrase neutre qui décrit l'affirmation — sans votre nom, sans votre message — et lit au plus trois des pages trouvées. Il ne cherche rien d'autre, ne vérifie rien de ce qui concerne une personne privée, n'ouvre pas les liens que vous écrivez, et ne prend pas parti : il dit ce que des sources de confiance établissent, ou qu'il ne peut pas trancher. Rien d'autre ne quitte cet ordinateur, à part ce que Dindon écrit dans les débats de ce serveur.

*Un seul mot a changé depuis le texte que vous aviez validé : « dans les fils de débat » est devenu « dans les débats », puisqu'un débat peut maintenant avoir lieu dans un salon. **À confirmer.***

**Désactivé par défaut** (`DINDON_DEBATE_CHECKS=off`) : tant que vous ne l'avez pas activé, **rien n'est lu et rien ne sort**, et ni `/dindon info` ni les débats ne parlent de vérification.

### Services de recherche, sources de confiance, citations (D4a, testé)

**Deux services de recherche derrière une même interface** (on en change sans toucher au reste) :

| Service | Ce que c'est | Ce qu'il demande |
|---|---|---|
| `FactCheckSearch` | L'API *Fact Check Tools* de Google : les **vérifications déjà publiées par des rédactions** pour une affirmation (note, rédaction, lien) | Une clé d'API (`DINDON_FACTCHECK_API_KEY`, à mettre vous-même dans `.env`). La page officielle ne donne **ni quota ni prix** : à lire à la création de la clé |
| `SearxSearch` | Une instance **SearXNG que vous hébergez** : recherche générale, sans compte ni clé, qui interroge d'autres moteurs pour vous | Rien, sinon la lancer. Ces moteurs finissent par bloquer une machine qui demande trop : des sources disent que cela tient pour moins de 50 recherches par jour, ce qui suffit à un bot de débat, pas à un gros serveur |

*Écarté pour l'instant* : Brave Search (selon des sites tiers, plus d'offre gratuite pour les nouveaux comptes depuis février 2026, environ 5 $ les 1 000 requêtes, carte bancaire exigée et pas de plafond de dépense : à vérifier sur leur page officielle).

**Ce qui fait qu'une page peut fonder un verdict** (`debate/trust.py`) : sa source doit être **officielle** (INSEE, administrations, parlements, organisations internationales : `insee.fr`, `gouv.fr`, `europa.eu`, `who.int`…) ou une **rédaction de vérification** (AFP Factuel, Les Décodeurs, CheckNews, Vrai ou faux…). Un journal n'est pas un vérificateur en entier : seule la rubrique compte. Toute autre page peut s'afficher comme contexte, **jamais seule comme preuve**. Ces listes sont un point de départ à relire et à modifier.

**Ce qui fait qu'une citation est une preuve** (`web.contains_quote`) : le modèle doit citer **mot pour mot** (25 à 400 caractères) un passage de la page, et le programme **vérifie que ce passage y est** (espaces, majuscules, apostrophes et espacement français avant « % : ; ? ! » ne comptent pas ; un chiffre différent ou un ordre différent, si). Un modèle peut inventer une phrase, pas que la page la dise.

**Ce qu'on suppose du contenu des pages** : c'est du texte écrit par n'importe qui, jamais une consigne. Il n'est lu que par une question étroite au modèle (verdict dans un vocabulaire fermé, citation obligatoire et vérifiée), sans outil, sans lien suivi, sans rien d'exécuté. *Aucune garantie contre une page qui ment ou qui cherche à tromper le modèle : c'est pourquoi un verdict exige une source de confiance ET une citation vérifiée, et pourquoi le mode observation et la mesure précèdent toute correction publique.*

**Accès au web en sécurité** (`debate/web.py`, testé) : jamais d'adresse de cette machine ni de son réseau (privées, boucle locale, lien local, CGNAT, réservées, multicast, et les formes IPv6 qui cachent une IPv4 : mappée, 6to4, Teredo, NAT64), vérifiées **à chaque redirection** et **sur toutes les adresses du nom** ; la connexion va à l'adresse vérifiée (pas de seconde résolution : rebond DNS) alors que le certificat TLS reste vérifié contre le vrai nom ; seulement les ports 80 et 443, pas d'identifiants dans l'adresse ; limites de taille (1 Mo lu), de durée (y compris contre un serveur qui distille un octet à la fois) et de redirections (3) ; seulement du texte (HTML, texte brut), rien de compressé ; `robots.txt` respecté (un fichier inaccessible ferme le site, comme le dit la norme) ; le programme dit qui il est.

**Cliquer sur les sources** (D5) : chaque correction publiée portera des **boutons-liens** Discord vers les pages (l'adresse exacte lue), avec la **citation vérifiée** et le nom de la source ; les statistiques de fin (D6) les listeront. Discord n'ouvre un lien qu'au clic de la personne.

**Ce qui ne change pas** : jamais de chiffre venu du modèle seul ; mode observation avant toute correction publique ; seuil de précision à fixer avec vous avant d'activer ; les personnes qui ont fait `/dindon stop` restent exclues de tout.

### 4. Corrections publiques (mode `live`)

Quand des sources de confiance **contredisent** une affirmation (et seulement alors : jamais pour « confirmé », « en partie », « contesté » ni « non vérifiable »), Dindon répond **au message** avec : « **Affirmation vérifiée** : « … » », « **Ce que disent les sources** (la période) » et, pour chaque source (trois au plus, les officielles d'abord), son nom cliquable et **sa citation exacte**, plus un **bouton-lien** par source. Le même modèle de message pour tout le monde ; il **ne nomme personne** et **ne mentionne personne** (réponse sans `replied_user`) ; il n'exprime aucun avis (« Dindon ne prend pas parti : il rapporte ce que disent des sources de confiance »).

- **Une seule fois par affirmation**, espacées de 20 secondes, **10 par heure et par débat au plus**, jamais pour une affirmation lue il y a plus de 30 minutes ni dans un débat terminé, jamais pour une personne qui a demandé l'arrêt.
- **Seulement dans un débat dont la vérification n'a pas été décochée** dans la fenêtre : un débat lancé sans vérification ne lit rien, ne note rien et ne corrige rien, même si vous avez activé les corrections publiques.
- Une correction qui ne peut pas être postée est retentée avec des attentes croissantes, puis abandonnée après 5 essais.
- **Retirée de Discord** quand ce sur quoi elle repose disparaît : le message d'origine est modifié ou supprimé, ou son auteur est effacé. La correction ne survit pas à ce qu'elle cite.
- **Verrou** : `DINDON_DEBATE_CHECKS=live` ne suffit pas. Il faut aussi `DINDON_DEBATE_PRECISION`, la précision de « contredit » que **vous** avez mesurée avec `tools/measure_claims.py verify`, et qu'elle atteigne le seuil (0,90 par défaut). Sinon le bot reste en observation, **le dit dans son journal**, dans `dindon preflight` et dans la page Débats.

### 5. Statistiques de fin

Le message de fin est la première page des statistiques ; ses boutons Précédent / Suivant changent de page et **chaque page est recalculée depuis la base au clic** (une personne effacée ou qui a demandé l'arrêt disparaît au clic suivant ; un message supprimé aussi). Si la vérification est active, il **attend** que les messages restants soient lus (5 minutes au plus).

- **Résumé** : pourquoi le débat s'est terminé, nombre de participants et de messages, durée, positions finales, personnes qui ont changé de position, bilan des affirmations vérifiées.
- **Participants** (6 par page) : sa position (et celle d'avant s'il a changé), ses messages et leur part, ce qui a été vérifié de lui (des nombres), et son **message phare**. Critère unique, sans modèle : le message de la personne qui a reçu le plus de réponses (×3) et de réactions dans le fil, parmi ceux d'au moins 40 caractères ; le même pour tout le monde, écrit sur la page.
- **Affirmations vérifiées** : le **tableau de parité par position**, puis chaque affirmation avec son verdict, la date du chiffre, le lien du message et les liens des sources. **Sans nom accusateur** : la liste renvoie aux messages, elle ne pointe pas une personne.
- La page **Débats** de l'interface donne la même chose en détail, avec les noms, les citations et l'état de la vérification.

## Les règles du débat (`debate/rules.py`, `debate/store.py`)

- Un débat est **`preparing`** (écrit, son lieu n'est pas encore fait), **`open`**, puis **`closed`**, avec la raison : `ended` (le bouton), `silence`, `no_participants` ou `failed` (il n'a pas pu être ouvert, ou son fil ou salon a été supprimé).
- **Aucune limite de temps.** Seul le **silence** peut le terminer : si ni message ni position pendant la durée choisie (1 h à 7 j), le débat se termine. Le silence est mesuré **depuis l'heure du dernier message compté ou de la dernière position** ; chaque débat a le sien ; il survit à un redémarrage (tout est en base).
- Un **participant** est quelqu'un qui a écrit dans le débat ou pris position. Jamais quelqu'un qui est dans le registre « ne pas enregistrer ».
- À la fin, **personne n'a participé** → le débat se ferme comme tel (`no_participants`), quelle que soit la raison de la fin.
- **Le bouton « Terminer le débat »** : la personne qui l'a lancé, ou un modérateur (droits lus dans l'interaction : administrateur, gérer le salon, le serveur, les messages ou les fils). Les autres sont prévenus en privé. Un second clic, ou la fin par silence au même moment, ne fait rien de plus. **Les messages écrits dans les dernières secondes sont comptés avant la fin.**
- **Le lieu** : un fil public créé sous le salon, ou le salon lui-même, ou le fil depuis lequel la commande a été faite (`debates.thread_id` dit où ; `in_thread` dit si Dindon a créé le fil). Deux débats ouverts ne partagent jamais un lieu (index unique, migration 0018) ; un salon héberge des débats **l'un après l'autre**.
- **Dans un salon, ce qui a été écrit avant le message de lancement n'est pas lu** : le débat commence à ce message.
- **Un message supprimé ne compte plus** : ni dans le nombre de messages, ni pour faire de son auteur un participant s'il n'a rien écrit d'autre. Sa position reste (ce n'est pas un message). Ceci vaut pour toute suppression, en direct comme découverte par le rattrapage nocturne (`ingest/loader.py`, un seul endroit), et même si la carte n'avait jamais enregistré le message.
- **Un message modifié compte comme avant** : il a été écrit. Si la vérification est active, une modification **retire ses affirmations (et la correction publiée) et le message est relu avec son nouveau texte**.
- **Un message n'est lu que pendant une heure** : en cas de retard (modèle absent, salon très actif), ce qui a attendu plus d'une heure n'est plus lu (il reste compté) : les vérifications sont pour ce qui se dit maintenant.
- **Le message de lancement** supprimé par un modérateur est **republié** avec les chiffres du moment. Un **fil ou salon supprimé** ferme le débat, sans rien à annoncer.
- **Après une coupure** (le bot était arrêté, ou Discord a ouvert une nouvelle session du Gateway : ce qui s'est écrit entre-temps n'est jamais arrivé), le lieu de chaque débat en cours est **relu depuis Discord, depuis le dernier message compté (ou le message de lancement), avant que le silence soit regardé** : un débat ne doit pas se terminer sur un compte auquel il manque des messages. Si Discord ne répond pas, la relecture est retentée toutes les 30 secondes. Une session reprise (`resumed`) ne manque rien et ne relit rien.

## Les données (migrations 0015 à 0018, 6 tables)

`debates` (l'état, les paramètres choisis dans la fenêtre : contexte, fil ou salon, vérification, silence ; le lieu ; le message de lancement ; la dernière activité ; **l'axe d'où il vient**, copié), `debate_messages` (qui a écrit quoi, quand ; **pas le texte**, qui est dans `messages`), `debate_positions` (chaque position prise, dans l'ordre : la dernière est l'actuelle, les autres montrent un changement d'avis). La migration 0018 a **supprimé** la table des votes et les colonnes de durée, de période et de fin : rien de réel n'y avait encore tourné.

Volontairement **sans clé étrangère** vers `users`, `messages`, `channels`, `guilds` : l'effacement d'une personne supprime sa ligne là-bas, et les messages arrivent par un autre chemin un instant plus tard. Chaque table qui porte un identifiant de personne est nettoyée **par son nom** dans `privacy.py`, et un test échoue si une migration future en ajoute une sans le dire.

Si le bot s'arrête entre un changement d'état et son annonce sur Discord, `store.unannounced()` dit ce qu'il reste à poster (un message de lancement supprimé, un débat fermé sans statistiques).

S'y ajoutent, pour la vérification : `debate_claims` (l'affirmation reformulée, les mots du message qui la portent, le verdict, la date du chiffre, ce que cela a coûté en recherches et pages : des nombres), `debate_sources` (l'adresse exacte lue, la citation vérifiée, l'empreinte de la page, la nature de la source) et, pour les corrections publiques, `debate_corrections` (un numéro de message à répondre, un numéro de message posté, jamais un nom). `debate_messages.read_at` est la **file de lecture** : un message à lire est une ligne dont `read_at` est vide.

## Vie privée

- **Effacer une personne** (`/dindon effacer`, `dindon privacy erase`) supprime ses messages comptés et ses positions dans les débats ; le débat reste, sans elle comme auteur (le sujet et le contexte, écrits pour le débat, restent avec lui). **Ce que Dindon a déjà posté dans Discord (statistiques, corrections) reste dans Discord** : seuls les modérateurs du serveur peuvent le supprimer.
- **Retirer le bot d'un serveur** (avec `DINDON_ERASE_ON_REMOVAL`) supprime ses débats.
- **Durée de conservation** (`DINDON_RETENTION_DAYS`) : les débats fermés depuis plus longtemps sont supprimés.
- **`/dindon mes-donnees`** : le fichier contient maintenant les débats auxquels la personne a pris part (ses positions dans l'ordre, ses messages comptés), jamais ce que font les autres.
- **À faire avant tout test réel avec des inconnus** : les positions sur un sujet politique sont des opinions (article 9 du RGPD) ; le consentement n'est pas traité dans Dindon (voir `docs/CONFORMITE.md`). Le message de lancement dit que Dindon compte les messages du débat et que `/dindon stop` en exclut.
- **Dans un salon (fil décoché), tout ce qui s'écrit est lu** tant que le débat est ouvert : les messages sont comptés et, si la vérification est active, analysés, même ceux qui n'ont rien à voir avec le sujet. Le message de lancement le dit en gras. Un fil à part limite cela aux personnes qui y viennent : **c'est la raison pour laquelle le fil est proposé**.

## Mesure (D4c)

Deux étapes, mesurées à part (`tools/measure_claims.py`, calculs dans `debate/measure.py`, jeu de référence `tools/claims_reference.json`). Le jeu est séparé en deux moitiés : **réglage** (pour améliorer les consignes) et **test** (mesurée une seule fois, qu'on ne regarde pas en réglant). Les paires miroirs restent entières d'un côté.

**Les étiquettes du jeu de référence sont de moi (Claude), de mémoire : elles doivent être vérifiées par une personne contre les sources**, car une étiquette fausse compte comme une erreur de Dindon.

### Lecture d'un message (modèle local seul, rien ne sort) : `qwen3:14b`, mesuré le 2026-10-06

44 messages de débat : 24 avec une affirmation de fait, 20 sans (opinions, questions, prévisions, plaisanteries, anecdotes, personnes privées, données personnelles, lignes citées, liens seuls).

| | Avant réglage (tout le jeu) | Réglage (22 messages) | **Test (22 messages, une seule mesure)** |
|---|---|---|---|
| Affirmations retrouvées | 36 % | 100 % | **100 %** |
| Précision des affirmations rendues | 75 % | 93 % | **86 %** (14 rendues) |
| Messages sans affirmation où le modèle en a trouvé une | 0 % | 0 % | **0 %** |
| **Fuites** (affirmation rendue sur une personne privée ou des données personnelles) | 0 | 0 | **0** |

**Mise à jour du 2026-10-06 (texte `claims-4`)** : un message écrit par un membre (« 90% des élèves ne vont pas à l'école ») n'était **jamais lu**. Cause : le modèle recopiait l'affirmation **entre guillemets « … »** (il voit le message entre guillemets) et le code, qui vérifie que les mots viennent bien du message, la jetait. Corrigé (les guillemets autour sont ignorés, six variantes testées). Deux élargissements à la même occasion : la lecture retient aussi **un fait scientifique, géographique ou historique** (« la Terre est plate »), et le minimum d'un message passe de 25 à **16 caractères** (compté sans les mentions, liens et salons). Mesure : moitié `dev` **100 %** retrouvées, **88 %** de précision (16 rendues), 0 fuite ; moitié `test` (mesurée une fois avec ce texte, après réglage sur `dev`) **100 %**, **86 %** (14 rendues), 0 fuite, 0 message sans affirmation pris pour une affirmation. Les chiffres de la colonne « Test » ci-dessus sont ceux de `claims-3` : ils n'ont pas bougé.

Ce que le réglage a corrigé : un champ mal compris par le modèle (`public_subject` signifiait pour lui « personnalité publique » : renversé en `about_private_person`), trois exemples ajoutés (absents du jeu), et le refus des affirmations qui ne se comprennent pas seules. **Petit échantillon (12 messages avec affirmation par moitié) : un intervalle d'incertitude large.** Durée : environ 3 secondes par message.

### Vérification de bout en bout (SearXNG local, vraies pages, vrai modèle) : mesuré le 2026-10-06

37 affirmations (14 vraies, 20 fausses, 3 invérifiables ; 10 en 5 paires miroirs). Durée : environ 15 secondes par affirmation.

| | Réglage (18) avant | Réglage (18) après | **Test (19, une seule mesure)** |
|---|---|---|---|
| **Précision de « contredit »** | 100 % sur 4 | 100 % sur 6 | **100 % sur 2** |
| « Contredit » à tort (vrai déclaré faux) | 0 | 0 | **0** |
| Fausse déclarée vraie | 0 | 0 | **0** |
| Tranchées dans le bon sens | 38 % | 50 % | **56 %** |
| Laissées sans verdict (jamais à tort) | 62 % | 50 % | **44 %** |
| Invérifiables restées invérifiables | 50 % | 100 % | **100 %** |

Ce que le réglage a corrigé : le modèle jugeait « confirmer » sur une ressemblance de surface (une page sur les courses de 2010 pour « la moitié des Français préfèrent le vendredi », un chiffre de 69 millions « confirmant » « plus de 100 millions »). Il écrit maintenant d'abord ce que dit l'extrait et si c'est **le même objet et la même période** ; le code refuse tout avis sinon. Les pages lues sont aussi choisies selon la ressemblance de leur titre et de leur extrait avec l'affirmation (gratuit : aucune requête de plus), et les blocs faits de liens (menus) sont retirés du texte.

**Ce que ces chiffres permettent de dire, et rien de plus** : sur ce petit jeu, **Dindon n'a jamais donné raison à une affirmation fausse ni tort à une affirmation vraie** ; il préfère se taire (44 à 50 % des affirmations tranchables restent sans verdict : pages illisibles par un robot, pages qui ne portent pas le chiffre, extraits en anglais pour une affirmation en français, résultats de recherche qui varient d'un essai à l'autre). Mais la **précision de « contredit » repose sur 2 à 6 corrections** : **beaucoup trop peu** pour déverrouiller les corrections publiques, et le verrou le dit (minimum 8). Les étiquettes sont non vérifiées, et le moteur de recherche donne des résultats qui changent. **Ce n'est pas une mesure de ce que fera Dindon sur votre serveur** : c'est une preuve que la chaîne marche et se trompe rarement dans le sens dangereux.

### À faire pour déverrouiller les corrections publiques (vous)

1. **Faire vérifier les étiquettes** de `tools/claims_reference.json` par une personne contre les sources, et **ajouter vos propres affirmations** (au moins 30 fausses et 30 vraies, des paires miroirs de vos sujets de débat réels).
2. `python tools/measure_claims.py verify --split all --searxng <adresse>` (ou avec `DINDON_FACTCHECK_API_KEY`) : le rapport dit **« PRÊT POUR LES CORRECTIONS PUBLIQUES : OUI/NON »** et pourquoi (précision ≥ 0,90 sur au moins 8 corrections, aucun vrai déclaré faux, écart de précision entre les deux camps ≤ 0,10).
3. Si OUI : mettre la précision affichée dans `DINDON_DEBATE_PRECISION` et `DINDON_DEBATE_CHECKS=live`.

## Comment l'activer (vous)

La vérification est **désactivée par défaut** et ne peut rien envoyer tant que vous ne faites pas ces choses.

1. **Un service de recherche** (au moins un) : soit la clé de Google *Fact Check Tools* (`DINDON_FACTCHECK_API_KEY` dans `.env`, que **vous** y mettez ; ne me la montrez pas), soit un SearXNG à vous : `docker compose --profile search up -d searxng`, avec `SEARXNG_SECRET` (un long texte au hasard) dans `.env`, et `DINDON_SEARXNG_URL=http://searxng:8080`. *SearXNG tient pour quelques recherches par heure ; ses moteurs finissent par bloquer une machine qui en demande trop (pendant l'essai, l'un d'eux a répondu « too many requests »).*
2. **Le modèle local** : `ollama pull qwen3:14b` (déjà installé) ; Ollama doit tourner sur le Mac.
3. **Le mode** : `DINDON_DEBATE_CHECKS=answer` (Dindon répond d'abord et les participants jugent : le niveau qui répond à « Dindon n'intervient pas ») ou `observe` (il note seulement), puis `docker compose --profile bot up -d --build`. Cela applique les migrations 0015 à 0018 et reconstruit l'interface. **Le bot doit avoir été réinvité** avec les 6 permissions (« Inviter le bot » dans l'interface) pour ouvrir un fil ; sans fil, il lui suffit d'écrire dans le salon.
4. **Vérifier** : `dindon preflight` (il dit ce qui sera envoyé, si le modèle est là, si les corrections publiques sont verrouillées).
5. **Informer les membres avant** (texte dans [INFORMATION-MEMBRES.md](INFORMATION-MEMBRES.md) ; `/dindon info` et chaque débat vérifié le disent aussi).
6. Sur un serveur de test avec des participants informés : lancer un débat, écrire des affirmations de fait, lire `docker compose exec bot dindon debate-report` ou la page **Débats**.
7. Pour les corrections publiques : voir « À faire pour déverrouiller » dans « Mesure ».

**Limites connues** : une seule lecture à la fois (quelques secondes par message avec un Mac branché) ; au plus 20 affirmations vérifiées par débat et par heure ; les messages de plus de 1 500 caractères sont coupés ; deux affirmations au plus par message ; les pages en PDF ne sont pas lues ; certains sites officiels refusent les robots ; une affirmation sur une personne privée ou qui renvoie à un lien n'est jamais vérifiée.

## Niveau de preuve, par fonction

Étiquettes : implémenté / testé avec données simulées / testé avec vrai Discord / mesuré / estimé.

| Fonction | État |
|---|---|
| Tables, règles (limites, un débat par salon, fin par bouton ou par silence), effacement, export, retrait d'un serveur, conservation | **Implémenté, testé avec données simulées** (vrai PostgreSQL, horloge déplacée à la main, deux vraies connexions pour les accès simultanés) |
| Commande, fenêtre de paramètres (et sa version plus simple), fil ou salon, boutons, compteurs (au plus toutes les 5 s), bouton « Terminer » et ses droits, fin par silence, archivage ; reprise après arrêt ; erreurs de Discord (limites de débit, droits manquants, fil supprimé) ; suppressions, modifications, messages du bot supprimés, rattrapage après coupure | **Implémenté, testé avec données simulées** (Discord en mémoire ; le client HTTP lui-même contre un vrai serveur local) |
| Accès au web en sécurité (adresses interdites, redirections, rebond DNS, TLS, taille, durée, `robots.txt`), citations vérifiées, sources de confiance, deux clients de recherche, budget par affirmation, liste des modules qui peuvent sortir | **Implémenté, testé avec données simulées** (serveur local, vraie poignée de main TLS) ; **essayé sur de vraies pages** de l'INSEE et d'Eurostat (lues), de `service-public.fr` (refusée par son `robots.txt`, ce qui est le bon comportement) |
| Lecture à l'aveugle, vérification sur pages de confiance, verdicts, file durable, plafond de 20 affirmations par débat et par heure, mode observation | **Implémenté, testé avec données simulées** ; **mesuré avec le vrai modèle et le vrai Internet** (voir « Mesure ») |
| Corrections publiques (neutres, sans nom, boutons-liens), une seule par affirmation, espacées, plafonnées, **retirées** si leur origine disparaît ; verrou par précision mesurée | **Implémenté, testé avec données simulées**. **Jamais publié sur un vrai Discord** |
| **Réponses de Dindon sans Internet**, Valide / Invalide, recherche sur demande, message réécrit, retrait ; le forum des débats (`/dindon forum`, post et étiquettes) | **Implémenté, testé avec données simulées** (Discord en mémoire, un faux forum construit d'après la documentation de Discord). **Fiabilité du modèle seul : mesurée sur 37 affirmations (voir « Répondre d'abord »)** : peu, et pas assez pour parler sans le jugement des participants |
| Statistiques de fin (pages, boutons, message phare, parité par position) ; page Débats de l'interface | **Implémenté, testé avec données simulées** ; la page dans un vrai navigateur (Playwright) |
| SearXNG (`docker/searxng/settings.yml`, profil `search`) | **Essayé en vrai** : démarre avec cette configuration et renvoie du JSON ; une recherche de test a été faite |
| Fact Check Tools de Google | **Jamais essayé** (pas de clé) : la forme de sa réponse est celle de sa documentation |
| Quoi que ce soit sur un vrai Discord | **Jamais** |

### À vérifier sur un vrai Discord (hypothèses, non prouvées)

1. **Le bot reçoit les messages du fil qu'il a créé** (membre de son fil). *Si ce n'est pas le cas, aucun message ne serait compté.* Le code envoie aussi `PUT …/thread-members/@me`.
2. Un fil public se crée **sans message de départ** (`POST /channels/{id}/threads`, type 11) avec « créer des fils publics ».
3. Les **boutons** restent utilisables pendant des heures, y compris dans un fil archivé automatiquement (24 h d'inactivité).
4. Le bot peut **archiver son propre fil** (sinon c'est ignoré).
5. **La fenêtre** : Discord accepte une fenêtre dont les champs sont enveloppés dans un composant `Label` (type 18), avec des champs de texte (type 4), des listes (type 3), un **groupe de cases** (type 22) et une **case seule** (type 23), et il renvoie les réponses sous la forme que le code lit (`data.components[].component`, `value` pour un texte ou une case, `values` pour une liste ou un groupe). *Lu dans la documentation de Discord le 2026-10-06 (pas essayé) : un groupe de cases demande **au moins 2 options** (avec une seule option, Dindon met une case seule) ; une case et un groupe sont **obligatoires par défaut** (`required` vaut `true`), donc Dindon met `required: false` partout, sinon une case décochée empêcherait d'envoyer ; une liste peut être facultative (`required: false`, `min_values: 0`) et porte 25 choix au plus. Le nombre maximal de champs d'une fenêtre (5) n'est pas dit dans la partie de la documentation que j'ai pu lire. Si Discord refuse la fenêtre (HTTP 400), Dindon en montre une plus simple (une liste à choix multiples à la place des cases) ; si elle est refusée aussi, la personne est prévenue qu'une erreur est survenue.*
6. Une modification de message toutes les 5 secondes passe les **limites de débit** de Discord.
6 bis. **Les droits du modérateur** : l'interaction d'un bouton contient `member.permissions` (les droits de la personne dans ce salon, en nombre écrit comme du texte). Le bouton « Terminer » s'en sert ; *s'il manquait, seule la personne qui a lancé le débat pourrait terminer*.
6 ter. **Un salon actif** : le bot reçoit bien tous les messages du salon (il les reçoit déjà pour la carte) ; la lecture et la vérification suivent le rythme, et ce qui attend plus d'une heure n'est plus lu.
7. Les événements **`MESSAGE_DELETE`, `MESSAGE_DELETE_BULK`, `THREAD_DELETE`, `CHANNEL_DELETE`** arrivent pour un fil où le bot est membre ; `GET /channels/{fil}/messages?after=` marche avec « lire l'historique » ; les codes 10003 (salon inconnu) et 10008 (message inconnu) sont ceux attendus.
8. **Un bouton-lien** (style 5) dans un embed publié par le bot s'ouvre au clic ; le bot peut **supprimer ses propres messages** sans « gérer les messages » ; une réponse avec `replied_user: false` ne prévient personne.
9. **Les statistiques** : un `UPDATE_MESSAGE` (type 7) avec des embeds remplace bien le message au clic sur un bouton de page.
10. La commande `/dindon debat` apparaît avec ses options (l'enregistrement de `/dindon` n'a jamais été vérifié non plus).
11. Les mentions `<@id>` dans l'embed des statistiques s'affichent comme des noms (et ne préviennent personne).
13. **Le forum** : `POST /channels/{forum}/threads` avec `message` et `applied_tags` crée bien le post et son premier message en un appel (réponse : le post, dont le numéro est aussi celui du premier message, que Dindon modifie ensuite) ; le bot, créateur du post, y est déjà membre ; il peut le modifier, l'archiver ; le choix `channel_types: [15]` de `/dindon forum` ne propose que des forums ; l'interaction contient `member.permissions` pour la commande aussi. *Lu dans la documentation de Discord, jamais essayé.*
14. **Valide / Invalide** : une réponse de Dindon modifiée par Dindon (PATCH) garde son numéro ; `application_id` suffit pour répondre aux clics (déjà le cas des autres boutons).
12. Les pages de l'INSEE ne sont pas toutes lisibles par ce lecteur : certaines (`economie.gouv.fr`, `legifrance.gouv.fr`) ont répondu une erreur à une requête qui se présente honnêtement comme un robot.

## Étapes (toutes faites)

- **D1** base de données et règles (`debate/rules.py`, `debate/store.py`, vie privée). **D2** côté Discord (`bot/debate_commands.py`, `bot/rest.py`, `debate/texts.py`, invitation à 6 permissions). **D3** suppressions, modifications, messages du bot, fil supprimé, rattrapage après coupure.
- **D4a** accès au web en sécurité (`debate/web.py`, `search.py`, `trust.py`, `scope.py`, `tests/test_outbound.py`). **D4b** lecture à l'aveugle (`reading.py`), vérification (`verify.py`), orchestration (`checker.py`, `Debates.check_next`), file durable (`claims.py`), mode observation. **D4c** jeu de référence et outil de mesure (`measure.py`, `tools/measure_claims.py`), mesures réelles.
- **D7** (2026-10-06, sur votre demande) : débat libre : fenêtre de paramètres, fil facultatif, plus de minuteur ni de vote, fin par bouton ou par silence (`bot/debate_commands.py`, `debate/rules.py`, `debate/store.py`, `debate/texts.py`, migration 0018).
- **D9** (2026-10-06, sur votre demande) : le forum des débats (`debate/forum.py`, `/dindon forum`). **D10** (2026-10-06, sur votre demande) : Dindon répond d'abord sans Internet, Valide / Invalide, recherche si plus d'Invalide (`debate/local.py`, `debate/answers.py`, migration 0020) ; case « fil » cochée par défaut.
- **D8** (2026-10-06, sur votre demande) : un axe au lieu d'un sujet : liste des axes dans la fenêtre, question de l'axe posée par Dindon, réponses = les deux pôles (migration 0019 ; les cases deviennent facultatives et se regroupent pour tenir en 5 champs).
- **D5** corrections publiques (`claims.py`, `texts.correction`, `Debates._corrections`, migration 0017), verrou de précision (`checker.resolve_mode`). **D6** statistiques de fin (`stats.py`, `texts.stats_page`), API et page Débats, préflight.
- **Ensuite : un test réel sur un serveur de test avec des participants informés** (il vous revient : voir le rapport de fin de cette étape).
