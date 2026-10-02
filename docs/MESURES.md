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
