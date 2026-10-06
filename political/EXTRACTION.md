# Expérience : l'IA lit un débat et dit ce que chaque personne pense

8 débats, 29 (personne, débat) évalués, modèle `qwen3:14b`, sans rôle ni indication : seulement les noms et les messages.

| Mesure | Résultat |
| --- | --- |
| Position exacte (écart 0) | 12/29 (41%) des cas où l'IA se prononce |
| Position à ±1 | 28/29 (97%) |
| Bon sens (pour / contre) quand la consigne était tranchée | 15/16 (94%) |
| Sens **inverse** (pour au lieu de contre) | 1/16 (6%) |
| Personne « sans avis » (consigne 0) classée sans position ou à 0 | 6/11 (55%) |
| Preuve recopiée qui est bien dans les messages de la personne | 29/29 (100%) |
| L'IA ne se prononce pas (null) | 0/29 (0%) |

## Par type de personne

| | Cas | Exact | ±1 |
| --- | --- | --- | --- |
| apolitique | 5 | 4/5 (80%) | 5/5 (100%) |
| ecologiste | 2 | 1/2 (50%) | 2/2 (100%) |
| humaniste | 1 | 0/1 (0%) | 1/1 (100%) |
| laic | 6 | 1/6 (17%) | 5/6 (83%) |
| liberal | 1 | 0/1 (0%) | 1/1 (100%) |
| libertarien | 3 | 0/3 (0%) | 3/3 (100%) |
| nationaliste | 1 | 0/1 (0%) | 1/1 (100%) |
| provocateur | 2 | 1/2 (50%) | 2/2 (100%) |
| socialiste | 3 | 2/3 (67%) | 3/3 (100%) |
| souverainiste | 5 | 3/5 (60%) | 5/5 (100%) |

## Par ton

| | Cas | Exact | ±1 |
| --- | --- | --- | --- |
| agacé et direct | 1 | 0/1 (0%) | 1/1 (100%) |
| blagueur | 7 | 4/7 (57%) | 7/7 (100%) |
| concis, phrases très courtes | 4 | 2/4 (50%) | 4/4 (100%) |
| passionné, écrit parfois en majuscules | 4 | 2/4 (50%) | 4/4 (100%) |
| posé et argumenté | 2 | 0/2 (0%) | 2/2 (100%) |
| pédant, cite des chiffres | 3 | 2/3 (67%) | 3/3 (100%) |
| écrit vite avec des fautes de frappe et des abréviations | 8 | 2/8 (25%) | 7/8 (88%) |

**Messages d'ironie** : sens correct pour 3/3 (100%) des personnes qui en ont écrit un (là où le sens s'inverse si l'IA lit l'ironie au premier degré).

Limites : la « vérité » est la consigne donnée à l'auteur simulé, pas une relecture humaine ; un auteur simulé peut avoir dérivé. Lire quelques débats à la main avant de se fier à un chiffre.
