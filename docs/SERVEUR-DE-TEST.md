# Le serveur de test politique (inventé)

Un serveur Discord **inventé** qui ressemble à un serveur politique francophone, avec une **vérité connue** pour mesurer l'IA. Tout est fait de personnes et de messages imaginaires ; il tourne dans sa propre base (`dindon_politique`), jamais mélangée à vos vrais serveurs.

## Le voir

```console
.venv/bin/python tools/make_political_server.py build     # (re)fait political/exports et political/truth.json
make politique                                           # importe et sert l'interface : http://127.0.0.1:8012 (mot de passe : test)
tools/politique-analyse.sh                               # l'IA (conversations, vecteurs, thèmes) puis la comparaison avec la vérité
```

Même interface que le vrai Dindon : **Carte** (points colorés par rôle, `Personnes sans lien` coché pour tous les voir), **Thèmes** (ceux que l'IA propose, à valider), **Système**, **Vie privée** (les commandes `/dindon` n'existent pas ici : pas de Discord). Le mot de passe du vrai serveur n'est pas celui-ci.

## Ce qu'il contient

| | |
| --- | --- |
| Personnes | **100**, 13 types (socialiste, radical, écologiste, libéral, souverainiste, nationaliste, conservateur, centriste, laïc, libertarien, humaniste, apolitique, provocateur), avec un ton (posé, sarcastique, passionné, concis, pédant, fautes de frappe, blagueur, agacé), un âge, un genre, une activité très inégale (quelques-uns écrivent beaucoup, beaucoup peu) |
| Opinions | chacun a une position de −2 à +2 sur **10 propositions** (économie, Europe, immigration, écologie, laïcité, sécurité, institutions, défense, société, technologie). 4 personnes **changent d'avis** à une date |
| Rôles | idéologie (28 rôles réels des serveurs politiques), âge, genre, équipe (3 personnes), notifications. **9 personnes portent un rôle qui ne correspond pas à ce qu'elles disent** et **27 n'en ont aucun** : c'est ce que la « vérification avec les rôles » doit repérer |
| Salons | 14, en 3 catégories (Politique, Société, Détente), un salon par sujet + actualité + détente |
| Messages | environ **3 300** sur 150 jours, dont réponses, mentions, réactions, modifications, pièces jointes, un robot de modération, de la conversation sans enjeu |
| Débats | **342**. Chaque débat a des participants qui ne sont pas d'accord quand c'est possible, un déclencheur (une actualité inventée), et des messages de genres variés : affirmation, question, **ironie** (dire le contraire de ce qu'on pense), accord, désaccord |

**Deux sources de débats**, gardées séparées dans la vérité (`source`) :
- **`llm`** : écrits par le modèle local (`qwen3:14b`), langage varié, c'est la partie réaliste. C'est lent (de 1 à 2 minutes par débat) et ça vide une batterie : `tools/make_political_server.py generate --count N` les écrit un par un, **reprend où il s'est arrêté**, et **se met en pause sous 30 % de batterie** (branchez le Mac). `build` utilise tout ce qui a été écrit.
- **`gabarit`** : composés à partir de phrases écrites à la main (6 arguments pour et 6 contre par sujet). Ils donnent du volume avec une vérité exacte, mais leur langage est pauvre et répétitif : **un score d'IA dessus est trop optimiste**.

À la date de ce document : **7 débats écrits par le modèle** sur 342 (le reste en gabarit). Pour un test plus réaliste, laissez tourner `generate` (branché) puis refaites `build` et `make politique`.

## La vérité (`political/truth.json`)

Pour chaque message : le débat, le sujet, le genre de message, et **`stance_told`** : l'opinion que l'auteur simulé **avait pour consigne** de tenir. Pour chaque personne : son type, ses rôles, ses positions, ses changements d'avis. **C'est une consigne, pas une relecture humaine** : un modèle peut dériver (une personne « plutôt d'accord » peut sonner neutre). Lisez quelques débats à la main avant de vous fier à un score.

## Ce qui a été mesuré

**Le bot** (`tools/replay_through_bot.py`) : les messages sont joués au vrai moteur du bot, comme le Gateway les annoncerait, puis comparés aux exports. 3 309 messages en 11 s, **3 202 identiques sur 3 202 comparés** (type, texte, auteur, heure, réponse, mentions), 0 refusé, 0 perdu ; les 101 personnes qui ont écrit ou ont été mentionnées ont les mêmes noms et les mêmes rôles. **Niveau : simulé** : le moteur, l'adaptateur, l'ingestion et PostgreSQL sont les vrais, mais Discord ne l'est pas (les trames sont fabriquées ici d'après les formes que les tests de l'adaptateur supposent). Cela ne remplace pas l'essai sur un vrai serveur.

**Les thèmes** (`tools/politique-analyse.sh`, vrais modèles `bge-m3` et `qwen3:14b`) : 341 conversations, 9 thèmes proposés, **pureté 87 %** (information mutuelle 0,88). Les sujets les plus nets sont retrouvés sans mélange (économie, Europe, immigration, écologie, société, sécurité, laïcité, défense). **Institutions et technologie ont été fondus en un seul thème** (« Réforme du vote et représentation citoyenne ») : le nombre de thèmes choisi (9) est plus petit que les 10 sujets. Sur les 6 conversations issues de débats écrits par le modèle : 83 % : trop peu pour conclure.

**Ce que dit l'IA de chaque personne** (une **expérience** préliminaire, depuis remplacée par l'étape « positions » de Dindon, voir [ANALYSE.md](ANALYSE.md) ; son script a été supprimé) : le modèle lit un débat (noms et messages seulement) et donne la position de chacun avec une citation. Sur 29 cas (8 débats écrits par le modèle) : **bon sens (pour/contre) 94 %**, **à ±1 de la consigne 97 %**, mais **position exacte 41 %**, personne « sans avis » reconnue 55 %, preuve recopiée exacte 100 % (la citation est toujours dans les messages de la personne), ironie bien lue 3 sur 3. **29 cas, c'est trop peu** : l'étape « positions » a été mesurée depuis sur 269 positions (voir [VALIDATION-AXES.md](VALIDATION-AXES.md)).

**La lecture des positions** (page **Positions**, `tools/politique-analyse.sh`, `qwen3:14b`) : 100 conversations lues, 505 positions retenues avec leur citation, 46 propositions du modèle refusées par le code faute de preuve exacte. Comparées à la consigne donnée aux auteurs simulés (`political/RAPPORT-POSITIONS.md`), après qu'un modèle a jugé le sens de chaque proposition :

| | Résultat |
| --- | --- |
| Bon sens (pour/contre), consigne tranchée, l'IA tranche | **205/238 (86 %)** ; 33 en sens inverse (14 %) |
| … sur les débats écrits par le modèle (langage varié, le chiffre le plus honnête) | **31/41 (76 %)** : trop peu pour conclure |
| … sur les débats de gabarit | 174/197 (88 %), optimiste |
| Personne sans avis tranché : l'IA **prend parti à tort** | **20/30 (67 %)** |
| Propositions créées | 248 pour 10 sujets : très éparpillées (thèses précises) ; 114 jugées sans rapport avec la proposition du sujet, 78 formulées dans le sens opposé |

**À lire avec** : la vérité est une consigne, pas une relecture humaine ; le sens des propositions est jugé par un modèle ; 269 positions seulement ; les débats de gabarit sont plus faciles que de vrais messages.

**Les axes et la cohérence des rôles** (fiche d'une personne, page **Cohérence**) : sur le serveur de test, **118 conversations sur 343 sont lues et 150 propositions sur 268 sont reliées aux axes** (la machine, saturée par un autre conteneur et passée plusieurs fois sur batterie, n'a pas pu aller plus loin ; `tools/politique-analyse.sh` finit le travail, il se met en pause sous 35 % de batterie). Résultat à ce stade, **trop peu de propos pour juger** : sur 73 personnes avec un rôle d'idées, 4 sont jugées cohérentes et 69 « pas assez de propos » (3 positions au moins sur un même axe sont exigées). Avec des seuils assouplis (2 positions) : sur les 9 personnes dont le rôle ne leur correspond pas, **1 est signalée en contradiction** (8 non jugeables) ; 1 personne au rôle conforme est aussi signalée (à relire). **Il n'est donc pas encore possible de dire si le contrôle des rôles repère les bonnes personnes** : il faut lire toutes les conversations puis relancer `tools/evaluate_political.py --coherence-report`.

## Ce qui manque encore

- La **vérification avec les rôles** (les 9 personnes au rôle trompeur, les 27 sans rôle) : la lecture des positions existe, mais une proposition ne charge pas encore d'axe, donc pas de score par axe à comparer aux rôles.
- Les propositions ne sont pas encore **regroupées ni validées** par une personne.
- Le serveur n'est pas un vrai serveur : pas de vraies personnes, un vocabulaire que le modèle a produit lui-même (le même modèle qui lira ensuite : un biais favorable). Les vrais messages seront plus bruités.
