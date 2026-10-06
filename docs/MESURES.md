# Mesures

Ce qui a été **mesuré** (avec la commande pour le refaire) et ce qui n'est qu'**estimé**. Machine : Mac Apple M4 Pro, 24 Go ; PostgreSQL 17 dans Docker Desktop (8 Go de mémoire alloués à Docker) ; données inventées. Les durées sont celles d'une seule série, sur une machine par ailleurs occupée.

## Import de 500 000 messages (mesuré)

```console
python tools/make_demo_server.py --out big/ --people 400 --messages 500000 --channels 40 --days 365
dindon ingest big/
```

| Mesure | Résultat |
| --- | --- |
| Génération des 500 000 messages (40 fichiers) | 6,3 s ; 147 Mo, soit environ 294 octets par message (le prompt annonçait environ 350) |
| **Import** (analyse du JSON, écriture, liens du graphe) | **26,5 s**, soit environ 18 900 messages par seconde. Pour comparaison, l'insertion SQL seule du §8 du prompt prenait 11 s : ici le JSON, les réactions et les liens sont compris |
| Mémoire de l'importateur | 149 Mo au plus avec des fichiers de 12 500 messages en moyenne (voir plus bas pour un seul gros fichier) |
| Temps du processus Python | 2,1 s de calcul : le reste est l'attente de PostgreSQL |
| Taille de la base après import | 276 Mo ; table des messages et ses index : 214 Mo, soit **428 octets par message** (le prompt annonçait environ 430) |
| Contenu | 500 000 messages, 400 personnes, 160 508 réactions avec leurs auteurs, 76 786 mentions, 70 345 liens (une ligne par paire et par type) |
| Liens calculés pendant l'import contre liens reconstruits depuis zéro | **0 différence** sur 70 345 |

**Un seul gros fichier** (mesuré : un salon de 300 000 messages dans un fichier de 86 Mo) : 16 s, mais **856 Mo de mémoire**, soit environ **10 fois la taille du fichier**, car il est lu en entier (l'arbre JSON, puis les lignes à écrire). Un salon d'un million de messages exporté d'un seul tenant demanderait donc plusieurs Go. Le premier import (`dindon backfill`) coupe en fichiers de 50 000 messages ; pour un export à la main d'un très gros salon, utiliser l'option `--partition 50000` de l'exportateur. Une lecture ligne par ligne (le format s'y prête : un message par ligne) supprimerait cette limite : non fait.

## Le graphe (mesuré, base de 500 000 messages)

| Mesure | Résultat |
| --- | --- |
| Reconstruction complète des liens (`SELECT rebuild_edges()`, 3 essais) | 1,27 à 1,70 s. **Plus lent que les 183 ms du prompt** : ce n'est pas le même calcul (ici : les trois types de liens depuis les messages et les réactions, avec la fonction de décroissance, 70 345 lignes). Elle ne sert qu'au besoin (changement de demi-vie, vérification), pas à chaque message |
| Un petit lot arrive en direct (fichier d'export compris) | 10 messages : 84 ms ; 100 : 98 ms ; 1 000 : 153 ms. La majeure partie est un coût fixe par fichier, pas par message. Pour comparaison le prompt annonçait 5 ms pour 1 000 messages, mais pour la mise à jour des liens seule |

## L'API et l'interface (mesuré, même base)

| Requête | Temps (5 essais) | Taille |
| --- | --- | --- |
| Graphe, tout le temps (400 personnes, 20 000 liens) | 201 à 299 ms | 3,5 Mo |
| Graphe, 30 derniers jours (recompté depuis les messages) | 166 à 201 ms | 1,1 Mo |
| Graphe, 7 derniers jours | 42 à 60 ms | 0,5 Mo |
| Fiche de la personne la plus active (environ 70 000 messages) | 375 à 429 ms | 3 Ko |
| Recherche d'une personne | 47 à 50 ms | 1 Ko |
| Liste des serveurs (comptes) | 160 à 236 ms | — |
| Interface : 400 personnes et 20 000 liens, après la connexion | affichée en 1,8 s (Chromium sans carte graphique) | — |

Par défaut l'interface ne demande que les 2 500 liens les plus forts : 20 000 traits ne se lisent pas. Elle n'a **pas été mesurée au-delà de 400 personnes** : « fluide à plusieurs milliers de personnes » reste un objectif non vérifié.

## Du faux Discord à la page (mesuré)

`python tools/check_ui.py` : un échange est posté sur le faux Discord, on attend que le lien s'allume dans le vrai navigateur.

| Intervalle de relevé | Délai mesuré |
| --- | --- |
| 2 s (12 essais, instants aléatoires) | de 0,15 à 1,99 s, médiane 1,26 s |
| 2 s (6 essais, autre série) | de 0,16 à 1,96 s, médiane 0,30 s |

Le délai est **environ la moitié de l'intervalle de relevé, plus 0,3 s**. Avec l'intervalle par défaut de 30 s, il faut s'attendre à **15 s en moyenne, 30 s au pire** : c'est « quelques secondes » seulement avec un intervalle court. Réduire l'intervalle accélère l'affichage et augmente les requêtes faites à Discord (une par serveur et par relevé) : à régler selon le type de jeton (voir [COLLECTE.md](COLLECTE.md)).

## Estimé, pas mesuré

- Débit réel de l'exportateur contre Discord, et durée du premier import d'un vrai serveur (le prompt estime environ une heure pour un million de messages, plus les réactions : **non vérifié**).
- Durée du rattrapage nocturne sur un vrai serveur.
- Tout ce qui touche à l'IA locale (phase 2) : aucun modèle n'est installé.

## L'analyse locale (mesuré, données inventées, vrais modèles)

Même machine (Mac M4 Pro, 24 Go, GPU Metal : 17,8 Go de mémoire vidéo utilisable). Ollama 0.35.1 sur le Mac, `bge-m3` (vecteurs), `qwen3:14b` et `gemma4:12b` (noms). Données : un serveur inventé de 3 000 messages et 40 personnes (`tools/make_demo_server.py`, graine 11). Commande : voir [ANALYSE.md](ANALYSE.md). **Ce sont des conversations fabriquées à partir de modèles de phrases : elles se regroupent très facilement. Aucune de ces mesures ne dit comment les modèles se comportent sur de vraies conversations.**

| Mesure | Résultat |
| --- | --- |
| Découpage en conversations (SQL) | 3 000 messages → 436 conversations (6,9 messages en moyenne), dont **360 retenues** (deux messages qui disent quelque chose, ou un long) |
| **Vecteurs** (`bge-m3`, lots de 16) | **360 conversations en 22 s**, soit environ 16 par seconde (médiane 0,45 s par lot). Premier lot : 8,9 s (chargement du modèle) |
| Nombre de thèmes trouvé par la silhouette | 19 (scores des candidats : 4 → 0,197 ; 9 → 0,348 ; 14 → 0,343 ; **19 → 0,364** ; 25 → 0,325 ; 30 → 0,300 ; 35 → 0,292 ; 40 → 0,307). Les scores sont **proches** de 9 à 25 : le nombre n'est pas net, il se règle à la main (`--topics`) |
| Regroupement + nom de 19 thèmes (`qwen3:14b`) | 204 s en tout, dont environ 11 s par nom (médiane 11,1 s sur 21 appels, premier chargement compris) |
| Comparaison des deux modèles de noms sur 10 thèmes | `qwen3:14b` : **6,2 s** par nom ; `gemma4:12b` : **9,4 s** ; voir [ANALYSE.md](ANALYSE.md) §6 pour la qualité |

**Estimé (non mesuré)** pour un vrai serveur de 100 000 messages : environ 15 000 conversations, donc environ **15 minutes** de vecteurs, puis 20 à 40 thèmes à nommer, soit **4 à 7 minutes**. La taille d'un vecteur est d'environ 5 Ko (voir `db/schema-vector.sql`) : 15 000 conversations ≈ 75 Mo.

## Vie privée et charge d'un gros serveur (mesuré, données inventées)

`tools/measure_privacy.py` et `tools/measure_bot_load.py`, sur le Mac (M4 Pro, PostgreSQL dans Docker), base temporaire supprimée ensuite. Serveur inventé : **300 000 messages, 5 000 personnes, 60 salons**, 120 000 liens.

| | Mesuré |
| --- | --- |
| Import de ces 300 000 messages (60 fichiers) | 29,8 s |
| Un import d'un fichier, registre vide / registre de 1 500 personnes | 637 ms / 639 ms (le registre ne coûte rien) |
| Effacer une personne moyenne (15 messages) / la plus active (40 518 messages), base seule | 0,24 s / 1,52 s |
| Copie des données d'une personne active | 0,04 s |
| Réécrire les fichiers d'`archive/` sans la personne (2 400 fichiers, 4,2 Go, la personne dans tous) | **126 s** : le seul point lent ; la personne moyenne est dans une fraction des fichiers |
| Purge de tout (300 000 messages, lots de 20 000, liens refaits) | 6,2 s |
| Le bot en direct, 100 messages/s sur 40 salons pendant 20 s | 2 000 sur 2 000 écrits, vidé 1,1 s après le dernier, aucune perte ni reprise |
| Le bot en direct, **300 messages/s** sur 80 salons pendant 20 s | 6 000 sur 6 000 écrits, vidé 3,9 s après le dernier, aucune perte ni reprise |

Limites de cette mesure : un seul poste, base chaude, données inventées (messages courts), un seul serveur ; le débit réel de Discord vers le Gateway n'est pas mesuré ici.

## Un gros serveur : 5 000 personnes, 300 000 messages (mesuré le 5 octobre 2026, données inventées)

| Mesure | Résultat |
| --- | --- |
| Génération des 40 fichiers (98 Mo) | 12 s |
| Import | **18 s** pour 300 000 messages, 4 994 personnes, 122 084 liens ; base de 196 Mo |
| API : le graphe (3 000 personnes et 20 000 liens affichés, le reste masqué et compté) | 0,32 à 0,43 s, 4,2 Mo |
| API : liste des serveurs, état du système, recherche d'une personne | 0,13 s, 0,07 s, 0,04 s |
| Interface (Chromium sans carte graphique) | comptes affichés **2,9 s** après la connexion ; mémoire JS 37 Mo ; 20 mouvements de souris traités en 1,5 s ; aucune erreur dans la page |

La carte ne dessine que les 3 000 personnes les plus liées et dit combien elle en masque. Non mesuré : un vrai Discord de cette taille, l'analyse par l'IA sur ce volume.

## Les débats : lecture et vérification des affirmations (2026-10-06, vrai modèle, vrai Internet)

Détail, méthode et limites dans [DEBAT.md](DEBAT.md) § « Mesure ». Jeu de référence `tools/claims_reference.json` (étiquettes de Claude, de mémoire, **à faire vérifier par une personne**), moitié « réglage » et moitié « test » (mesurée une seule fois). Machine : Mac M4 Pro, `qwen3:14b` via Ollama, SearXNG local.

| Mesure | Résultat (moitié test) | Remarque |
|---|---|---|
| Lecture : affirmations retrouvées / précision des affirmations rendues | **100 % / 86 %** (22 messages, 12 avec une affirmation) | 36 % / 75 % avant le réglage de la consigne ; environ 3 s par message |
| Lecture : messages sans affirmation où le modèle en trouve une ; **fuites** vers une personne privée ou des données personnelles | **0 % ; 0** | |
| Vérification : précision de « contredit » | **100 % sur 2 corrections** (réglage : 100 % sur 6) | trop peu de corrections pour être une mesure ; le verrou exige au moins 8 |
| Vérification : vrai déclaré faux / fausse déclarée vraie | **0 / 0** | aucune erreur de sens sur 37 affirmations (les deux moitiés) |
| Vérification : tranchées dans le bon sens / laissées sans verdict | **56 % / 44 %** | pages illisibles par un robot, pages sans le chiffre, extraits en anglais, résultats de recherche variables |
| Vérification : invérifiables restées invérifiables | **100 %** | une erreur (« confirmé » à tort) corrigée pendant le réglage |
| Durée de la vérification | environ 15 s par affirmation | recherche, jusqu'à 3 pages, appels au modèle |

**Niveau de preuve : mesuré, sur un petit jeu aux étiquettes non vérifiées. Pas une garantie sur votre serveur.**

