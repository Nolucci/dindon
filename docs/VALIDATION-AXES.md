# Validation des axes : ce qui a été vérifié, ce qui a été corrigé, ce qui reste

*Relecture du 4 octobre 2026, mise à jour le même jour après l'activation des 21 axes. Toutes les données sont **inventées** (serveur politique de test) ; la référence est le jugement d'**une seule personne (moi)**, pas une vérité ni une relecture indépendante. Rien n'a été mesuré sur un vrai serveur.*

## En bref

| Question | Réponse mesurée |
| --- | --- |
| Sur des phrases d'arguments isolées et claires, l'IA relie-t-elle la bonne phrase au bon axe, dans le bon sens ? | Oui, **90 % des liens corrects, 3 % dans le mauvais sens** (40 phrases écrites après avoir fixé la consigne) |
| Et sur les propositions réellement extraites des débats du serveur de test (phrases parfois nuancées, négatives ou sans parti pris) ? | **60 % des liens corrects, 8 % dans le mauvais sens, 33 % sur un axe que je n'ai pas retenu** (384 liens, 395 propositions relues) |
| Peut-on laisser les scores se calculer sans relecture ? | **Non.** Environ un lien sur treize envoie quelqu'un du mauvais côté (29 sur 384, dont 9 « forts »). Les poids doivent être validés par une personne |
| Les axes inactifs (Europe, écologie, genre, redistribution, animaux…) valaient-ils la peine d'être activés ? | **Oui, d'après la mesure** : sur 55 phrases, 61 % → 87 % de liens corrects et 37 % → 13 % de liens sur un mauvais axe quand l'IA les voit. **Les 21 axes sont maintenant actifs** (votre décision du 4 octobre). Sur les 396 vraies propositions : 60 % → 68 % de liens corrects, 8 % → 4 % à l'envers, mais avec une référence relue en voyant l'IA (voir §3 bis) |
| La vérification des rôles repère-t-elle les rôles qui ne correspondent pas à la personne ? | **Pas sur ce serveur de test** : 0 des 9 rôles faux repérés, 0 fausse accusation. Pour 7 des 9, la personne n'a rien dit sur les axes de son rôle ; les 2 autres disent réellement ce que dit leur rôle tiré au hasard (voir §4) |

## 1. Ce que l'IA fait, et ce qui a changé

Le modèle lit **une phrase** (une proposition) et les axes actifs ; il dit pour chaque axe sur lequel la phrase prend parti (au plus deux) **vers quel pôle (par son nom)** elle penche et avec quelle force (`forte`, `moyenne`). Le code transforme cela en poids (−1 / +1, 1,0 ou 0,6) et refuse tout ce qui n'est pas un pôle de cet axe. Détail : [ANALYSE.md](ANALYSE.md).

Pourquoi des noms de pôles : en demandant un nombre signé, le modèle donnait **le même signe à une phrase et à son contraire** (36 % de liens à l'envers sur mes premiers essais).

## 2. Mesure sur des phrases isolées (`tools/check_axes.py`)

| Jeu | Phrases | Phrases avec ≥ 1 lien correct | Liens corrects | Mauvais sens | Sur un autre axe |
| --- | --- | --- | --- | --- | --- |
| Réglage (120 phrases : 6 pour et 6 contre pour chacun des 10 sujets) | 120 | 68 % | 64 % (84/131) | 13 % | 23 % |
| **Après coup** (40 phrases écrites avec d'autres mots, consigne figée) | 40 | **95 %** | **90 %** (35/39) | **3 %** (1/39) | 8 % |
| Après coup + 15 phrases sur les axes inactifs, l'IA ne voit que les **12 axes actifs** | 55 | 69 % | 61 % (35/57) | 2 % | **37 %** |
| Les mêmes 55, l'IA voit **les 21 axes** | 55 | **91 %** | **87 %** (47/54) | **0 %** | **13 %** |

À lire avec prudence :

- Le jeu « réglage » a servi à écrire la consigne : ses chiffres sont optimistes par construction. Les chiffres à retenir sont ceux de la deuxième ligne.
- Les 40 phrases ont été écrites par la même personne, après avoir vu les erreurs du jeu de réglage ; ce sont des phrases claires et à un seul parti pris. 40 phrases, c'est peu : l'écart entre 90 % et 95 % ne veut rien dire.
- Le seul lien « à l'envers » du jeu après coup (« Sortir de l'Union européenne pour retrouver notre souveraineté » → `intervention` −) se discute : l'axe `intervention` ne sait pas dire « Europe ».
- Les rapports complets sont dans `political/RAPPORT-AXES-v3*.md` (dossier `political/`, données de test).

## 3. Mesure sur les vraies propositions du serveur de test (`tools/score_axes_reference.py`)

J'ai relu **les 396 propositions** de la base politique (une relecture ligne à ligne, dans `political/axes-reference.json`), puis comparé ce que l'IA propose, seule, à ce que j'ai jugé juste (lecture propre avec la consigne `axes-3` : `political/RAPPORT-AXES-PROPOSITIONS.md`).

| | |
| --- | --- |
| Propositions relues | 395 (1 laissée « à trancher ») : 287 prennent parti sur au moins un axe, 108 n'en prennent aucun |
| Liens proposés par l'IA | 384 |
| **Corrects** (bon axe, bon sens) | **229 (60 %)** |
| **Dans le mauvais sens** sur un bon axe | **29 (8 %)**, dont 9 « forts » |
| Sur un axe que je n'ai pas retenu | 126 (33 %) |
| Propositions qui prennent parti, avec au moins un lien correct | 224/287 (78 %) |
| Propositions **sans parti pris** qui n'ont aucun lien (à raison) | 41/108 : les 67 autres ont un lien qu'elles ne méritent pas |
| Liens que j'ai dû **ajouter** (l'IA ne les proposait pas) | 71 |

**Où l'IA se trompe** (ce que j'ai vu en relisant) :

1. **L'Europe.** Il n'y a pas d'axe `europe` actif : les phrases pour ou contre l'UE sont rangées dans `intervention`, `economie` ou `commerce`, et souvent dans le mauvais sens (« Ensemble, les pays européens ont plus de poids… » → `intervention` Nationaliste). C'est la cause de la plupart des liens à l'envers ; le test du §2 le confirme (61 % → 87 % en voyant l'axe).
2. **Les critiques et les négations.** « La Ve République concentre trop de pouvoir dans les mains d'un seul homme » → `representation` Autocratie ; « Les lois sécuritaires dépassent souvent leur but initial » → Sécurité. L'IA lit le sujet de la phrase, pas son sens (critique de…).
3. **L'axe `economie` proposé à tort** (42 fois) pour des phrases sur la dépense publique, la dette ou le coût des choses, et `representation` (18), `pouvoir` (15), `technologie` (13) pour des phrases de méthode (« on doit réfléchir et agir, pas faire des discours vides »).
4. **Les phrases « méta » sans parti pris** (« La vision de P2 est un peu simpliste », « Il faut trouver un équilibre… ») reçoivent un lien dans 62 % des cas. Ce sont des propositions mal extraites (étape précédente) plus qu'une faute des axes, mais elles font bouger les scores.

**Réserves sur cette mesure.** Une seule personne a jugé, et c'est celle qui a écrit la consigne. Pour la moitié des propositions environ, j'ai gardé les liens tels qu'affichés quand ils me paraissaient justes (à ce moment-là, un mélange de deux versions de la consigne : voir §6), ce qui avantage un peu l'IA. Les phrases viennent de débats inventés (quelques-uns écrits par un modèle, le reste par gabarits), plus propres que de vrais messages.

## 3 bis. Avec les 21 axes (même méthode, après activation)

Les 396 propositions ont été relues par l'IA avec **les 21 axes** (rythme équilibré, mêmes propositions) ; toutes ses réponses ont été gardées (`political/axes21-answers.jsonl`). J'ai relu les **201 propositions** où ce que l'IA proposait différait de ma première référence et mis la référence à jour (98 changées : surtout des phrases sur l'Europe, l'écologie, la redistribution, la participation, la méthode de changement, les alliances, le genre, que je ne pouvais pas ranger ailleurs que sur un axe approchant). Résultat (`political/RAPPORT-AXES-PROPOSITIONS-21.md`) :

| | 12 axes (§3) | **21 axes** |
| --- | --- | --- |
| Liens proposés par l'IA | 384 | 354 |
| Corrects (bon axe, bon sens) | 229 (60 %) | **242 (68 %)** |
| Dans le mauvais sens | 29 (8 %), dont 9 « forts » | **14 (4 %)**, dont 2 « forts » |
| Sur un axe non retenu | 126 (33 %) | 98 (28 %) |
| Propositions qui prennent parti, avec ≥ 1 lien correct | 224/287 (78 %) | 238/297 (80 %) |
| Liens que j'ai dû ajouter | 71 | 77 |

**Ce que cela dit, et ne dit pas.**

- Les liens à l'envers **diminuent de moitié** et presque tous les « forts » disparaissent : l'Europe a enfin un axe (30 liens `europe` dans la référence) au lieu d'être rangée à l'envers dans `intervention`.
- Le gain de **liens corrects est plus modeste que sur les 55 phrases isolées** (61 % → 87 %), et il est **surestimé** : cette référence a été relue **en voyant les propositions de l'IA**, et je ne pouvais juger les liens vers les axes ajoutés qu'en les voyant. Prenez « +8 points » comme un maximum.
- Reste **28 % de liens sur un axe que je n'ai pas retenu**, surtout `representation` (16), `redistribution` (15), `economie` (12) et `rupture` (11), sur des phrases méta ou sans parti pris : c'est le point faible, que l'activation n'a pas réglé. Et 77 liens que l'IA ne propose pas.
- J'ai ensuite **validé** la référence mise à jour : 319 liens sur 395 propositions (1 laissée « proposée »), scores recalculés (468 scores sur 20 axes). Trace : `political/axes-decisions-final-21.json`.

## 3 ter. Améliorer la précision de l'IA elle-même (5 octobre 2026)

Objectif : que l'IA se trompe moins, **sans relire tous les messages**. Deux défauts mesurés, deux corrections ; chacune se mesure sur un jeu de référence, sans relancer l'analyse d'un serveur.

**1. Le sens de la position (pour / contre) était souvent inversé.** Mesuré sur 121 vraies positions du serveur de test que j'ai relues à la main (`political/stance-gold.json`, `tools/check_stances.py`) : la première lecture (l'extraction) avait le bon sens dans **70 %** des cas. Elle jugeait si le *sujet* est apprécié (« le 49.3 est antidémocratique » → *contre*) au lieu de juger si la personne est d'accord avec la *proposition* (elle écrit la même chose : *pour*). Sur l'échantillon, **toutes** les positions « contre » étaient fausses (36 sur 36 relues) ; elles représentent environ 10 % de toutes les positions. Correction : **une seconde lecture étroite** (`analysis/stances.py`, migration 0012) : le modèle ne voit que les mots de la personne et la proposition, et répond en un mot (accord, désaccord, nuance, aucune position). Une simple question (« tu as une source ? ») n'est plus comptée comme une position. Résultat sur le même jeu (169 phrases, dont 29 écrites à la main avec 20 vrais désaccords) : **93 %** (98 % sur le seul pour/contre : 126 sur 128, tous les 20 désaccords écrits à la main retrouvés). Réserve : quelques phrases d'exemple du prompt (des questions, « les deux côtés ont des points ») viennent du jeu, donc le chiffre sur « nuance » et « aucune position » est un peu flatteur ; celui du pour/contre ne l'est pas.

**2. Le rattachement aux axes se trompait sur environ un lien sur trois, et abandonnait ce qu'il ne savait pas trancher.** Les variantes de consigne seules ne font que déplacer le curseur entre précision et rappel. Ce qui améliore *les deux* : **lire chaque proposition plusieurs fois, de façons différentes** (la consigne de base, une consigne prudente et, dès qu'une personne a décidé les axes de 30 propositions, la même question avec les propositions voisines qu'elle a décidées comme exemples : migration 0013, ce que vous validez améliore les lectures suivantes), **garder ce que toutes les lectures disent, et trancher le reste par une question étroite** (`axes.decide`) : pour chaque axe discuté, pris seul, « où se range cette phrase : pôle négatif, pôle positif, ou nulle part ? ». Sa réponse **est** la réponse, même si c'est l'autre pôle que celui d'une lecture (ce qui corrige aussi des liens à l'envers). On ne s'abstient donc plus quand les lectures divergent. Mesuré sur la moitié « test » de mes 396 propositions, que le réglage n'a **jamais vue** (entre parenthèses : la moitié « réglage ») :

| | Précision | Rappel | À l'envers | F1 |
| --- | --- | --- | --- | --- |
| Une lecture (axes-3) | 64 % (72 %) | 73 % (78 %) | 4,4 % (3,4 %) | 0,69 (0,75) |
| Vote 2 lectures sur 3, le reste abandonné | 72 % (77 %) | 77 % (76 %) | 4,2 % (4,4 %) | 0,74 (0,76) |
| L'arbitre seul, sur tous les candidats | 80 % (74 %) | 59 % (60 %) | 8,5 % (7,6 %) | 0,68 (0,66) |
| **Retenu : 3 lectures, les unanimes gardés, le reste tranché** | **82 % (77 %)** | **76 % (79 %)** | **4,1 % (3,7 %)** | **0,79 (0,78)** |
| Avant tout exemple validé (2 lectures), le reste tranché | 74 % (78 %) | 72 % (76 %) | 5,9 % (3,8 %) | 0,73 (0,77) |
| Avant tout exemple validé, les deux doivent s'accorder (ancienne version) | 75 % (82 %) | 63 % (68 %) | 5,2 % (3,0 %) | 0,68 (0,75) |

À retenir : l'arbitre seul est trop prudent (il dit « nulle part » trop souvent) et le vote abandonne des liens justes ; **la combinaison est à la fois plus précise et plus décisive** (+18 points de précision et +3 de rappel par rapport à une lecture sur la moitié test). Coût : 2 à 3 lectures et en moyenne 1 à 2 questions d'arbitrage par *proposition* (quelques centaines), pas par message. Un consensus « 3 lectures sur 3 ou rien » donnerait 87 % de précision pour 59 % de rappel : refusé, c'est précisément l'indécision.

**3. Ne plus attendre pour donner un verdict sur une personne.** La vérification des rôles exigeait 3 positions et un poids de preuve de 1,5 sur un axe : 88 % des cas restaient sans verdict. Mesuré sur le serveur de test (`tools/evaluate_scores.py`, la « vérité » étant l'opinion donnée à chaque auteur simulé), **une fois le sens de chaque position relu deux fois** (127 → 996 positions relues, 115 corrigées, 49 écartées car c'étaient des questions) : le signe du score d'une personne sur un axe est le bon dans **93 %** des cas avec une seule proposition derrière (**86 % avant** la seconde lecture du sens), 95 % avec deux, 96 % avec trois. Attendre n'achetait donc que 2 à 3 points de précision pour dix fois moins de verdicts. Seuils ramenés à **1 position et un poids de 0,5** (migration 0014) : l'intervalle d'incertitude (jamais sous 0,35, large pour une seule remarque) garde le verdict de se prononcer à la légère, et une remarque dont le modèle n'est presque pas sûr ne suffit toujours pas. Effet sur la vérification des rôles : personnes « cohérentes » **9 → 30**, « pas assez de propos » **64 → 41**, contradictions **0 → 2** (un faux rôle donné exprès repéré, et un « Républicain » qui défend la place de la religion, signalé par le tableau des attentes du projet : à relire, ce n'est pas un verdict).

**Réserves.** La référence est mon jugement, relu en voyant les propositions de l'ancienne consigne (elle l'avantage un peu) ; les données sont inventées ; les exemples des consignes sont des phrases nouvelles, aucune ne vient de la référence. Je n'ai **pas** relancé la relecture de tout le serveur de test avec ces versions : seuls 127 des 1 123 positions ont été relues par la seconde lecture, le reste le sera à la prochaine analyse.

## 4. Ce qui a été validé, et ce que cela change

- **395 propositions** ont leurs liens **validés par relecture** : **319 liens** validés (avec les 21 axes ; 300 avant l'activation), et 98 propositions validées « ne pèse sur aucun axe » (ce sont des décisions aussi). Une proposition est laissée « proposée » (la 215, « Les exceptions ouvrent la porte à la dérive » : sans contexte, impossible à trancher). Rien n'a été validé sans lecture. Traces : `political/axes-decisions-final.json` (12 axes) puis `political/axes-decisions-final-21.json` (21 axes).
- Les scores des personnes ont été recalculés. Le réglage `only_validated_loadings` reste à 0 (tous les poids comptent) : les poids validés sont les seuls qui existent, sauf le 215.
- **Rôles contre positions** (`political/RAPPORT-ROLES.md` ; avant l'activation : `RAPPORT-ROLES-12-axes.md` ; avant toute validation : `RAPPORT-ROLES-avant-validation.md`) : 93 personnes ont une position lue, 89 un score. Sur les 73 qui portent un rôle d'idées : **0 « contradiction »**, 9 « cohérent » (13 avec 12 axes), 64 « pas assez de propos ». Les 9 personnes à qui j'ai donné **un rôle faux exprès** : 0 repérée.
  **Le contrôle ne se trompe pas, mais il ne détecte rien ici.** Il exigeait au moins 3 positions et un poids de preuve de 1,5 sur un axe avant de se prononcer (`scoring_settings` ; ramenés à 1 et 0,5 le 5 octobre, voir §3 ter, point 3), et les débats de test ne donnent qu'une ou deux positions par personne et par axe. **Plus d'axes, moins de preuves par axe** : avec 20 axes qui reçoivent des propos au lieu de 12, moins de personnes atteignent les 3 positions sur un même axe (13 → 9 personnes « cohérentes ») : c'est le prix, pour ce contrôle, d'axes plus fins.
  J'ai regardé les 9 faux rôles un par un : **2 sont « cohérents » parce que le rôle tiré au hasard correspond en fait à ce que dit la personne** (Louis_off, faux « Eurosceptique », a −0,66 sur Europe avec 4 positions ; Gabriel_off, faux « Humaniste », +0,69 sur l'immigration avec 4 positions) : la « vérité » du test est imparfaite, ce n'est pas une erreur du contrôle. **Pour les 7 autres, la personne n'a rien dit sur les axes de son rôle** (un faux « Communiste » sans une position sur l'économie) : il n'y a rien à vérifier. Sur un vrai serveur où les gens parlent davantage, il en dira plus ; descendre ces seuils le fait parler plus tôt, au prix de fausses accusations.
- **Fourchettes des idéologies** (`ideology_axis_ranges`) : relecture rapide, aucune erreur évidente repérée (pas une relecture exhaustive : à vous de la faire, voir [AXES.md](AXES.md)). Deux rôles n'ont **aucun axe** et ne seront jamais vérifiables (Spiritualité, Autre voie ; « Pragmatique » n'avait qu'un axe, qui était éteint), et **17 idéologies sur 28 avaient au moins une fourchette sur un axe éteint** (Européiste, Eurosceptique, Écologiste, Féministe, Animaliste, Socialiste, Communiste, Keynésien, Gaulliste…) : avec les 21 axes actifs, leur vérification porte maintenant sur tout ce qu'elles attendent.

## 5. Ce que je recommande

1. **Les 21 axes sont actifs** (fait : jeu de départ `seed-axes.sql`, migration `0011_all_axes_active.sql` pour les bases existantes, base de test relue et validée). Pour éteindre un axe : `UPDATE axes SET is_active = false WHERE code = '…';`. Sur votre instance réelle, la migration s'applique au prochain démarrage de l'application. Aucune proposition n'y est lue pour l'instant (l'IA n'y a jamais tourné) : rien à relire.
2. **Valider avant de faire confiance** : sur un vrai serveur, valider au moins les propositions qui pèsent le plus (la page Positions les liste, `tools/review_axes.py dump` aussi) et cocher « Ne compter que les poids validés » tant que ce n'est pas fait.
3. **Corriger à la source** les propositions sans parti pris : l'étape « positions » les produit ; les filtrer évite des liens à tort (voir §3, point 4).
4. **Ne pas lire un score comme une mesure précise** : la marge d'incertitude (le crochet sous la barre) ne descend jamais sous 0,35 exprès.
5. **Relire les 28 fourchettes d'idéologie** dans [AXES.md](AXES.md) : le contrôle des rôles s'appuie dessus et elles sont toutes marquées « non validées ».

## 6. Un défaut trouvé et corrigé pendant la relecture

Relire une proposition (après un changement de consigne) **ajoutait** les nouveaux liens **sans retirer les anciens** : `assign_axes` utilisait `ON CONFLICT DO NOTHING` et ne supprimait jamais les liens non validés d'une lecture précédente. Sur la base de test, au moins 196 des quelque 460 liens que je relisais venaient de consignes plus anciennes (des poids comme −0,4 ou −0,5 que `axes-3` ne produit jamais ; les autres ne se distinguent pas). Corrigé dans `app/dindon/analysis/axes.py` : une nouvelle lecture **remplace** les liens non validés de la proposition, les liens **validés par une personne sont conservés** ; test `test_reading_again_replaces_what_an_earlier_reading_proposed_but_keeps_what_a_person_validated`. Les chiffres du §3 viennent d'une lecture propre après ce correctif. Ce défaut n'affectait que les relectures forcées (changer de consigne, remettre `axes_read_at` à NULL), pas la première lecture d'une proposition.

## Refaire cette mesure

```bash
export DATABASE_URL=… OLLAMA_URL=http://127.0.0.1:11434
.venv/bin/python tools/check_axes.py --set held-out --report rapport.md            # phrases isolées (--set extended --all-axes : avec tous les axes, même éteints)
.venv/bin/python tools/review_axes.py dump --limit 100                              # relire ce que l'IA propose, 100 propositions à la fois
.venv/bin/python tools/review_axes.py apply decisions.json                          # enregistrer ce que vous décidez (valider, corriger, laisser)
.venv/bin/python tools/score_axes_reference.py reference.json                       # comparer les propositions de l'IA à une relecture
```
