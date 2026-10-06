# Les axes de l'IA : vérification sur un jeu de référence

Version de la consigne : `axes-3`.
120 phrases (6 pour et 6 contre pour chacun des 10 sujets de la politique inventée), modèle `qwen3:14b`, la même question qu'en production. Les axes acceptables et leur sens ont été écrits par une personne (moi, le 4 octobre 2026) : c'est une référence à discuter, pas une vérité.

| | |
| --- | --- |
| Phrases avec au moins un lien correct (bon axe, bon sens) | **81/120 (68%)** |
| Liens corrects | 84/131 (64%) |
| Liens **dans le mauvais sens** sur un bon axe (le pire) | **17/131 (13%)** |
| Liens sur un axe hors de la liste | 30/131 (23%) |
| Phrases sans aucun lien | 0/120 |

| Sujet | Corrects | Mauvais sens | Ailleurs | Rien |
| --- | --- | --- | --- | --- |
| economie | 13 | 1 | 0 | 0 |
| europe | 1 | 5 | 10 | 0 |
| immigration | 6 | 2 | 5 | 0 |
| ecologie | 9 | 3 | 2 | 0 |
| laicite | 9 | 1 | 2 | 0 |
| securite | 10 | 2 | 0 | 0 |
| institutions | 10 | 2 | 1 | 0 |
| defense | 10 | 1 | 2 | 0 |
| societe | 6 | 0 | 6 | 0 |
| technologie | 10 | 0 | 2 | 0 |

Axes les plus souvent choisis hors de la liste : economie (9), pouvoir (9), representation (6), structure (3), diplomatie (1).

**Liens dans le mauvais sens (à relire)** :

- (economie) « la dette c'est nos enfants qui la paieront, il faut réduire les dépenses » → economie −
- (europe) « sur le climat, la défense, le numérique : seuls on pèse rien, ensemble on peut » → intervention +
- (europe) « l'euro nous a évité des dévaluations en chaîne, demande aux Grecs ce qu'ils en pensent » → intervention +
- (europe) « les normes européennes protègent les consommateurs plus que n'importe quelle loi nationale » → commerce −
- (europe) « les pays qui sortent de l'UE finissent par le regretter, regarde les exemples » → intervention +
- (europe) « le Royaume-Uni s'en sort très bien, on nous avait promis l'apocalypse » → intervention −
- (immigration) « régulariser ceux qui bossent déjà c'est du bon sens, pas de la charité » → immigration −
- (immigration) « l'intégration marche quand on donne des papiers et un travail, pas quand on laisse dans le flou » → immigration −
- (ecologie) « le solaire et l'éolien sont devenus les énergies les moins chères, faut arrêter de se mentir » → technologie −
- (ecologie) « l'écologie punitive va nous mettre les gens dans la rue, regarde les gilets jaunes » → technologie +
- (ecologie) « la Chine pollue plus que nous tous réunis, nos efforts ne changent presque rien » → technologie +
- (laicite) « la liberté religieuse est dans la déclaration de 1789, on l'oublie souvent » → religion −
- (securite) « les lois sécuritaires sont toujours étendues bien au-delà de leur but initial » → pouvoir −
- (securite) « des policiers mieux formés ça compte plus que des policiers plus armés » → pouvoir −
- (institutions) « la Ve République concentre trop de pouvoir dans les mains d'un seul homme » → representation +
