# Les positions lues par l'IA, comparées à la consigne donnée à chaque auteur simulé

100 conversations lues, 269 positions évaluées (opinions avec une consigne connue), 46 propositions du modèle refusées faute de preuve exacte, 248 propositions créées.

La **direction de chaque proposition de l'IA** (même sens que la proposition de départ du sujet, sens opposé, sans rapport) a été jugée par un modèle : 56 propositions dans le même sens, 78 dans le sens opposé, 114 sans rapport (écartées). Un modèle qui en juge un autre : lisez-en quelques-unes.

| Mesure | Résultat |
| --- | --- |
| Bon sens (pour/contre) quand la consigne était tranchée et l'IA tranche | 205/238 (86%) |
| Sens **inverse** | 33/238 (14%) |
| Consigne tranchée, l'IA répond « nuancé » | 1/239 (0%) |
| Consigne « sans avis », l'IA répond nuancé | 10/30 (33%) |
| Consigne « sans avis », l'IA prend parti à tort | 20/30 (67%) |

| Origine des débats | Positions | Bon sens (consigne tranchée) |
| --- | --- | --- |
| gabarit | 205 | 174/197 (88%) |
| llm | 64 | 31/41 (76%) |

**Les propositions** (une proposition devrait correspondre à un sujet ; plusieurs propositions pour un même sujet = éparpillement) :

| Proposition créée par l'IA | Positions | Sujets réels |
| --- | --- | --- |
| Les pays qui sortent de l'UE finissent par regretter leur décision | 12 | europe 12 |
| Les normes européennes protègent mieux les consommateurs que les lois nationales. | 10 | europe 10 |
| L'État a un rôle nécessaire pour rééquilibrer les inégalités | 9 | economie 9 |
| La société a déjà changé, la loi doit s'adapter | 8 | societe 8 |
| Le solaire et l'éolien sont les énergies les moins chères | 8 | ecologie 8 |
| Continuer la croissance infinie sur une planète finie est mathématiquement impossible | 8 | ecologie 8 |
| Une armée européenne renforcerait l'autonomie des pays membres par rapport aux États-Unis. | 8 | europe 8 |
| Une assemblée à la proportionnelle représenterait enfin tout le monde | 7 | institutions 7 |
| Les villes doivent se refaire autour du vélo et du train, pas de la voiture | 7 | ecologie 7 |
| Un salaire minimum plus élevé relance la consommation | 7 | economie 7 |
| L'euro a évité des dévaluations en chaîne entre les pays membres. | 7 | europe 7 |
| L'égalité salariale exige des sanctions réelles pour être atteinte | 7 | societe 7 |
| Certaines traditions doivent être préservées sans être conservatrices | 6 | societe 6 |
| La privatisation de l'énergie entraîne une augmentation des prix et profite aux actionnaires | 6 | economie 6 |
| L'intégration réussit lorsque les migrants obtiennent des papiers et un emploi. | 6 | immigration 6 |
| L'aide à mourir avec des garde-fous garantit la liberté de choisir sa fin de vie | 6 | societe 6 |
| Les deux côtés d'un débat ont des arguments valables | 5 | immigration 2, societe 1, europe 1 |
| La sobriété coûte moins cher que de réparer les dégâts de la canicule | 5 | ecologie 5 |
| Le SMIC actuel est trop bas et conduit à des situations de précarité | 5 | economie 5 |
| Le marché commun crée des emplois dans les pays membres. | 5 | europe 5 |
| Les hôpitaux et les écoles doivent rester publics et non marchandises | 5 | economie 5 |
| Régulariser les travailleurs étrangers déjà employés est une mesure de bon sens, pas une charité | 5 | immigration 5 |
| Il faut être ferme sur les expulsions pour que la loi ait de l'effet | 5 | immigration 5 |
| Le 49.3 est un passage en force et non démocratique | 4 | institutions 4 |
| Ne pas se réarmer est naïf dans un monde plus dangereux | 4 | defense 4 |

Propositions par sujet réel : immigration 47, societe 37, laicite 27, institutions 24, defense 24, europe 22, technologie 21, economie 17, securite 16, ecologie 13.

Limites : la « vérité » est la consigne donnée à l'auteur simulé, pas une relecture humaine ; les débats « gabarit » sont plus faciles que les vrais messages.
