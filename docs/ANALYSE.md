# L'analyse par IA locale

Ce que Dindon sait faire avec des modèles locaux **aujourd'hui** (les premières étapes de la cascade), comment l'installer et l'utiliser, comment elle marche, ce qui a été mesuré, et ce qui reste à faire. La vue d'ensemble de la cascade est au §6 de [RESUME.md](RESUME.md), l'architecture visée dans [DINDON_ARCHITECTURE_IA.md](DINDON_ARCHITECTURE_IA.md).

## 1. Où on en est

| Étape de la cascade | État |
| --- | --- |
| 1. **Conversations** : regrouper les messages d'un salon en discussions | **implémenté**, testé avec données simulées |
| 2. **Tri** : écarter robots, messages vides, « mdr », « oui » ; noter l'importance | **implémenté**, testé avec données simulées |
| 3. **Vecteurs** de chaque conversation (modèle `bge-m3`) | **implémenté**, testé avec un faux Ollama, **mesuré** avec le vrai modèle sur des données inventées |
| 3. **Thèmes** : regroupement, noms par un modèle de langue, **validation par vous** | **implémenté** (ligne de commande, API, page « Thèmes »), testé avec un faux Ollama, **mesuré** avec les vrais modèles sur des données inventées |
| 4. **Lecture des positions** : ce que chaque personne affirme, avec la citation qui le prouve | **implémenté**, testé avec un faux modèle, **mesuré** avec le vrai modèle sur le serveur de test inventé (§4 bis) ; **jamais sur de vrais messages** |
| 5. Normalisation en propositions (une proposition retrouvée dans plusieurs conversations) | **implémenté** (par proximité des vecteurs), éparpillement mesuré, propositions non validées |
| 6. **Axes** : le poids de chaque proposition sur chacun des 21 axes, puis la **position de chaque personne sur chaque axe** (calcul SQL) | **implémenté**, testé avec un faux modèle ; poids proposés par le modèle puis **validés par une personne** (page Positions) ; mesuré sur le serveur de test : 60 % des liens corrects et 8 % à l'envers sur les vraies propositions, voir [VALIDATION-AXES.md](VALIDATION-AXES.md) |
| 7. **Cohérence des rôles** : ce qu'attend chaque rôle d'idées sur chaque axe, comparé à la position de la personne | **implémenté** (SQL + page **Cohérence**) ; le tableau des attentes de chaque rôle est celui du projet, **à relire par vous** |
| 8. Relations entre réponses (accord, désaccord entre deux personnes) | **pas fait** (la fiche montre seulement avec qui la personne a parlé du sujet, et si l'autre a pris la même position) |
| 7. Scores par axe (SQL) et vérification avec les rôles | scores en SQL **faits et testés** auparavant ; rien ne les alimente encore |

**Jamais lancé sur les messages d'un vrai serveur.** Tout ce qui est mesuré l'a été sur des conversations inventées (`make demo`) : les noms de thèmes y sont faciles. La qualité sur de vraies conversations est **inconnue** tant que vous ne l'avez pas essayée (§3, §6).

## 2. Installer (Mac)

Ollama tourne **directement sur le Mac**, pas dans Docker : seul le Mac peut utiliser le GPU. L'application, elle, reste dans Docker et joint Ollama par `host.docker.internal:11434` (déjà réglé dans `docker-compose.yml`).

```console
brew install --cask ollama-app      # l'application Ollama (ou le téléchargement de ollama.com)
open -a Ollama                      # la lance ; si rien n'écoute sur le port 11434 : ollama serve
ollama pull bge-m3                  # 1,2 Go : les vecteurs (le schéma attend ses 1024 nombres)
ollama pull qwen3:14b               # 9,3 Go : les noms des thèmes
curl http://127.0.0.1:8000/health   # "ollama":{"reachable":true,"models":[…]}
```

Sur cette machine (M4 Pro, 24 Go), les trois modèles testés ont été installés en quelques minutes. `gemma4:12b` (8 Go) a aussi été téléchargé pour la comparaison (§6) ; `qwen3.6` (17 Go au minimum) est trop gros pour 24 Go avec Docker.

**Rien ne sort de la machine** : le texte des conversations n'est envoyé qu'à l'adresse `OLLAMA_URL`, qui doit rester celle de ce Mac (ou d'un conteneur du même Compose). Ne mettez pas là l'adresse d'un service distant.

Les modèles se changent dans `.env` (`DINDON_EMBED_MODEL`, `DINDON_NAMING_MODEL`) puis `docker compose up -d`. Changer le modèle de vecteurs oblige à tout recalculer (les vecteurs sont rangés par modèle) et il doit donner 1024 nombres.

## 3. Lancer l'analyse

**Depuis l'interface** : page **Thèmes** (barre de gauche) → **Lancer l'analyse**. La page dit si Ollama répond et si les modèles sont là, montre l'étape en cours avec sa progression, permet d'**annuler**, et on peut la quitter : l'analyse continue.

**En ligne de commande** :

```console
dindon analyze                    # tout : conversations, vecteurs, thèmes
dindon analyze --stage embeddings # une étape seulement (--stage répétable)
dindon analyze --topics 12        # choisir le nombre de thèmes au lieu de le laisser trouver
dindon analyze --rebuild          # oublier les conversations (et ce qui en dérive) et les refaire
```

Chaque étape peut être relancée : **ce qui est fait n'est pas refait** (une conversation qui a son vecteur ne le recalcule pas ; on peut arrêter et reprendre). Une seule analyse à la fois.

## 4. Comment ça marche

**Conversations** (SQL, une seule requête). Les messages d'un salon, dans l'ordre, sont coupés après **20 minutes de silence** et tous les **40 messages**. Les robots et les messages système sont écartés. Une conversation n'est faite qu'une fois **finie** (le dernier message a plus de 20 minutes) : tant que quelqu'un peut répondre, elle attend. Un message n'appartient qu'à une conversation et n'est jamais déplacé ; relancer ne fait que les conversations des messages nouveaux.

**Tri**. Un message « dit quelque chose » s'il a au moins **15 lettres** une fois les liens, les emoji personnalisés et les mentions retirés. Une conversation est **retenue** si elle a deux messages qui disent quelque chose, ou un seul d'au moins 300 lettres. Rien n'est supprimé : une conversation non retenue reste en base, les étapes suivantes ne la lisent pas. Elle a une note d'importance (log du nombre de lettres, plus pour plusieurs participants).

**Vecteurs**. Le texte envoyé à `bge-m3` est ce qui a été dit, dans l'ordre, **sans les noms des personnes** (mentions et liens retirés) et seulement les messages qui disent quelque chose, coupé à 6 000 caractères. Une mention est retirée **en entier**, y compris un nom de plusieurs mots (« @Jean Dupont » : on retire les noms des personnes que le message mentionne, puis tout ce qui suit un « @ »). Les noms écrits **sans** « @ » dans le texte restent : rien ne permet de les reconnaître. Les vecteurs sont rangés par modèle (`conversation_embeddings`).

**Thèmes**, **sans tenir compte de qui parle** :

1. les vecteurs sont regroupés par leur direction (k-moyennes sphériques, départ k-means++, plusieurs essais) ;
2. le nombre de thèmes est celui qui donne la meilleure **silhouette** (à quel point chaque conversation ressemble à son groupe plutôt qu'au groupe voisin) parmi huit candidats de 4 à 40, sauf si vous le fixez. C'est une heuristique : tous les scores sont gardés avec la recherche (`topic_runs.parameters`) ;
3. un groupe de moins de 3 conversations est du bruit : ses conversations restent sans thème ;
4. chaque groupe est nommé par un modèle de langue local à partir de ses **mots caractéristiques** et de ses 6 conversations les plus typiques, **sans noms**. Le nom est une proposition : si le modèle échoue deux fois, les mots caractéristiques en tiennent lieu (et la ligne n'est pas comptée comme « nommée par le modèle »).

**Valider**. Chaque thème est **proposé** ; vous le **validez**, le **renommez**, le **fusionnez** dans un autre (rien n'est perdu, c'est réversible) ou le **rejetez** (il est caché, on peut le remettre). Dès que vous agissez sur un thème (renommer, valider, rejeter, fusionner, remettre en proposition, ou fusionner un autre thème dedans), **il est à vous** : une nouvelle recherche ne le remplace jamais (`topics.touched_at`). Elle ne remplace que les propositions que **personne n'a touchées**. Aucune étape ne se sert d'un thème non validé (aujourd'hui, aucune étape n'en consomme).

## 4 bis. Lire les positions (étapes 4 et 5)

**Lancer** : page **Positions** (barre de gauche) → **Lire les positions** (20, 40, 150 conversations ou toutes, les plus importantes d'abord), ou `dindon analyze --stage claims --limit 40`. Il faut avoir fait les conversations et leurs vecteurs (page Thèmes). C'est long : environ 15 secondes par conversation avec `qwen3:14b`. Ce qui a été lu n'est pas relu ; on peut arrêter et reprendre.

**Comment** : le modèle lit **une conversation à la fois**, avec les personnes sous la forme P1, P2… (**ni nom ni identifiant**) et les messages numérotés. Pour chaque personne qui prend position il écrit : une *proposition* générale (« L'État doit augmenter le SMIC »), une position (pour, nuancé, contre), le genre (opinion, fait, question, humour), une phrase, et une à trois **preuves** : le numéro du message et la **citation copiée mot pour mot**.

**Le code ne croit pas le modèle** (`analysis/extraction.py`) : une position n'est gardée que si chaque citation se retrouve (sans tenir compte de la casse, des espaces et de la ponctuation aux bords) **dans un message de cette personne-là, dans cette conversation**, et fait au moins 6 caractères. Sinon elle est refusée et comptée (« Refusées » sur la page). Une opinion sans position, un genre inconnu, un participant inexistant, plus de 4 positions par personne et par conversation : refusés. Une ironie ou une question n'est **jamais** une position (genre `humour` : gardée comme fait sur le message, sans position).

**Les propositions** : le modèle écrit des thèses **précises** (« L'État doit augmenter le SMIC », « Taxer les très hauts revenus »), pas un grand sujet par thème. Celle du modèle est rapprochée d'une proposition existante si leurs vecteurs sont assez proches (cosinus ≥ 0,80), sinon elle devient une nouvelle proposition **proposée** (rien ne la valide). Sur le serveur de test, deux formulations d'une même idée ont rarement plus de 0,65 de proximité : il y a donc **beaucoup de propositions** (de l'ordre de 3 par conversation lue), peu de personnes sur chacune. La page Positions les range **sous le thème** des conversations où elles ont été lues pour que ce soit lisible. La position affichée d'une personne sur une proposition est **la dernière**; les précédentes sont gardées (et montrées si elle a changé d'avis).

**Où le voir** : page **Positions** (les propositions, une barre pour/nuancé/contre, et en dépliant : chaque personne avec ses rôles d'idées, sa confiance et ses citations) ; **fiche d'une personne** sur la carte : « Positions lues par l'IA ».

**Effacement** : les positions lues dans une conversation dépendent de cette conversation : effacer une personne efface les conversations où elle a écrit, donc **aussi les positions des autres personnes qui y avaient été lues** (elles se relisent à la prochaine lecture).

**Le sens de chaque position est relu** (`analysis/stances.py`, étape « positions : relecture du sens ») : le modèle ne voit que les mots de la personne et la proposition, et dit accord, désaccord, nuance ou « pas une position » (une question). Mesuré : 93 % de bonnes réponses contre 70 % pour la première lecture ([VALIDATION-AXES.md](VALIDATION-AXES.md) §3 ter).

**Des propositions aux axes** (`analysis/axes.py`, étape « axes », comprise dans « Lire les positions » ou seule : `dindon analyze --stage axes`) : le modèle lit **une phrase** (la proposition : jamais une personne ni un message) et les axes actifs, **deux ou trois fois de façons différentes ; ce que toutes les lectures disent est gardé, et ce sur quoi elles divergent est tranché par une question étroite posée sur cet axe seul** (la troisième lecture montre les propositions voisines dont une personne a décidé les axes),, chacun avec la question qu'il pose, **ce que veut dire chacun de ses deux pôles en une phrase** (les ancres de la base) et ce qu'il ne couvre pas. Pour chaque axe sur lequel la phrase **prend parti** (au plus 2), il écrit **le nom du pôle** vers lequel penche ce qu'elle défend et un mot de force (`forte`, `moyenne`) ; le code en fait le poids : −1 ou +1 selon le pôle, 1,0 ou 0,6 selon la force. *Pourquoi des noms de pôles et pas un nombre signé* : mesuré (tools/check_axes.py), un modèle à qui l'on demande « −1 ou +1 » donne le **même signe à une phrase et à son contraire** (36 % de liens dans le mauvais sens) ; avec les noms et le sens des pôles, c'est tombé à 13 % sur les phrases d'arguments qui ont servi à régler la consigne, **3 % sur 40 phrases écrites après coup** (§ « Vérifier les axes »). Le code refuse un pôle qui n'est pas **celui de cet axe**, une force inconnue, un axe inexistant. Ces poids sont **proposés** (`proposition_axis.is_validated` reste faux) : une personne les valide, les corrige, les retire (page Positions, en dépliant une proposition ; `tools/review_axes.py` pour relire une liste). Puis le SQL (`refresh_person_axis_scores`) calcule la **position de chaque personne sur chaque axe** : la moyenne de ses positions sur les propositions qui pèsent sur l'axe, pondérée par la confiance et le poids, tirée vers 0 par un peu de doute, avec une **incertitude** qui ne descend jamais sous 0,35 et ne baisse qu'avec la quantité de propos. Le réglage `only_validated_loadings` (case de la page Positions) fait ne compter **que les poids validés**.

**Vérifier les axes** (`tools/check_axes.py`) : un jeu de référence écrit à la main (120 phrases d'arguments, 6 pour et 6 contre pour chacun des 10 sujets de la politique inventée, avec les axes acceptables et leur sens) sert à mesurer la consigne ; 40 phrases **écrites après coup, avec d'autres mots** donnent les chiffres honnêtes (voir [VALIDATION-AXES.md](VALIDATION-AXES.md)). Les réponses du modèle sont gardées par version de consigne : un recalcul ne redemande rien.

**La cohérence des rôles** : pour chaque **rôle d'idées** qu'une personne s'est donné (« Féministe »…), le tableau `ideology_axis_ranges` dit ce que ce rôle **attend** sur chaque axe (par exemple « Féministe » : Progressiste, entre −1 et −0,2, sur l'axe Morale et mœurs). Le verdict par axe : **incompatible** si toute la zone d'incertitude de la personne est hors de l'attendu, **confirmé**, **compatible**, ou **insuffisant** (aucune position sûre sur l'axe : une seule position suffit si le modèle en est assez sûr, poids cumulé d'au moins 0,5 ; seuils réglables dans `scoring_settings`, mesurés dans [VALIDATION-AXES.md](VALIDATION-AXES.md) §3 ter). Par rôle : **contradiction** (au moins un axe incompatible), **cohérent**, **pas assez de propos**. Les rôles qui s'excluent entre eux (« Européiste » et « Eurosceptique ») sont signalés à part. **Le tableau des attentes est celui du projet (`db/seed-axes.sql`, relu dans `AXES.md`) : c'est à vous de le relire**, et un axe inactif (Europe, Écologie, Genre…) n'est pas calculé tant que vous ne l'avez pas activé.

**Où le voir** : fiche d'une personne (carte) : une barre par axe du pôle de gauche (rouge) au pôle de droite (vert) avec un point, sa marge d'incertitude et le cadre de ce qu'attend chaque rôle ; en cliquant l'axe, les propositions qui l'ont fait bouger ; ses rôles avec leur verdict ; **par sujet** (thème) ses positions avec les citations et les personnes avec qui elle en a parlé (celles qui ont écrit dans les mêmes conversations, et si elles ont pris la même position ou la position inverse). Page **Cohérence** : la liste des personnes dont un rôle est contredit, les contradictions d'abord.

**Ce que ça ne fait pas encore** : la validation des propositions et de leurs poids par une personne ; les relations entre réponses ; le regroupement de propositions voisines.

## 5. Ce que ça écrit

Migration `0003_analysis_pipeline.sql` : colonnes de `conversations` (participants, messages qui disent quelque chose, importance, retenue), tables `conversation_embeddings` et `topic_assignments`, trois fonctions SQL (`analysis_clean_text`, `analysis_letters`, `analysis_substantive`). Les tables `topics` et `topic_runs` existaient déjà. Rien n'est écrit dans `messages`. Le code est dans `app/dindon/analysis/`.

## 6. Le choix des modèles (mesuré)

`tools/bench_models.py` fait renommer par chaque modèle les mêmes thèmes (mots caractéristiques et extraits) et affiche les noms côte à côte avec des contrôles faits par machine. Résultat sur les 10 plus gros thèmes de la démonstration (données inventées) :

| | `qwen3:14b` | `gemma4:12b` |
| --- | --- | --- |
| Temps médian d'un nom | **6,2 s** | 9,4 s |
| Réponse JSON valide | 10/10 | 10/10 |
| 2 à 6 mots | 6/10 | **10/10** |
| Ni mention, ni mot générique, ni nom de personne, avec description | 10/10 | 10/10 |
| Style | précis et concret (« Réforme du SMIC et régulation des prix ») | plus concis mais plus **générique** (« Partage de loisirs et vie quotidienne » pour une recette de tarte) |

**Choix provisoire : `qwen3:14b`** (plus rapide, plus précis). `gemma4:12b` respecte mieux la longueur demandée. Ce choix repose sur dix thèmes de conversations inventées et sur mon jugement de lecture : **refaites la comparaison sur vos propres conversations** avant de lui faire confiance, avec la même commande (les données restent sur la machine) :

```console
.venv/bin/python tools/bench_models.py qwen3:14b gemma4:12b
```

## 7. Mesures

Voir [MESURES.md](MESURES.md), section « L'analyse locale ».

## 8. Limites connues, et ce qui vient ensuite

**Limites**

- Un message **modifié ou supprimé après** la création du vecteur de sa conversation n'est pas répercuté (les vecteurs ne sont pas recalculés).
- Un historique importé **après coup** (par exemple l'import d'une période plus ancienne, une fois le bot en marche) donne de nouvelles conversations à côté des anciennes, pas des conversations fusionnées. `--rebuild` les refait toutes.
- Les noms de thèmes sont des propositions de modèles qui peuvent se tromper ou généraliser : c'est pour cela qu'on les valide. Des conversations hors sujet (salon de détente) donnent des thèmes mélangés (« tarte aux poires et retards de train » dans la démonstration).
- Une nouvelle recherche ne rapproche pas ses thèmes de ceux que vous avez déjà validés : elle en propose de nouveaux à côté.
- **`--rebuild` efface aussi les rattachements** des thèmes (les conversations qui y étaient classées) : un thème validé garde son nom mais n'a plus de conversations jusqu'à la prochaine recherche. À ne faire que si les règles de découpage ont changé.
- La recherche lit les textes par paquets de 500 conversations (la mémoire ne dépend pas de la taille du serveur, sauf les vecteurs : environ 4 Ko par conversation en mémoire).
- **Proposition à l'envers** : une proposition formulée dans le sens contraire (« Il ne faut pas augmenter le SMIC ») a un vecteur proche de son contraire et peut être fusionnée avec lui alors que la position garde le sens de la formulation. Le modèle a pour consigne de tout formuler dans le sens positif, ce qui réduit le problème sans le supprimer ; les mesures du serveur de test disent combien de fois le sens a été inversé.
- **Effacement** : l'effacement d'une personne (`dindon privacy erase`, page **Vie privée**, `/dindon stop`) supprime les conversations qui contiennent un de ses messages, donc leurs vecteurs et leur rattachement aux thèmes, et la réécrit hors des archives (voir [CONFORMITE.md](CONFORMITE.md)). Les conversations ne sont **pas** refaites tout de suite : relancez `dindon analyze`. Les thèmes eux-mêmes ne sont pas recalculés.
- Les extraits montrés dans la page Thèmes sont des morceaux de vrais messages, sans les noms mais pas toujours sans indice : ne partagez pas cette page.

**Ce qui vient ensuite**, et ce qu'il faut de votre part :

1. **Extraction** (étape 4) : un modèle liste ce que chaque personne affirme, avec les identifiants des messages qui le prouvent ; une affirmation sans preuve vérifiable (identifiant absent de la conversation, citation qui n'y est pas) est refusée par le code. Il faut d'abord **relire les axes et les idéologies** ([AXES.md](AXES.md)) : c'est ce qui décide le plus de la qualité, et le code ne les modifie jamais.
2. **Un jeu d'exemples relus par vous** (quelques dizaines de conversations avec ce qu'il faut en tirer) pour **mesurer** l'extraction avant de montrer le moindre résultat sur une personne. Sans cela, une extraction ne serait qu'« estimée ».
3. **Le consentement et l'effacement durable** (P4), et le mode pseudonymisé, avant de produire des fiches de positions sur des personnes.
4. Ensuite seulement : normalisation, relations, scores, vérification avec les rôles.
