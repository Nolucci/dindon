# La lecture automatique

Dindon peut **lire de lui-même ce que le bot enregistre**, un peu à la fois, sans que vous lanciez les analyses à la main. **Éteinte par défaut.** Page **Système** → panneau **Lecture automatique**.

## Ce qui est lu (au choix)

| Case | Ce que ça fait | Regarde les personnes ? |
| --- | --- | --- |
| **Conversations et vecteurs** (cochée par défaut) | Les nouveaux messages deviennent des conversations (après 20 minutes de silence) et chaque conversation reçoit son vecteur. | Non |
| **Thèmes** | Une nouvelle recherche de thèmes quand 25 conversations ne sont dans aucun thème de la dernière recherche. Elle remplace seulement les propositions que personne n'a touchées (voir ANALYSE.md). | Non |
| **Positions des personnes** | Ce que chacun pense, avec citations ; puis les axes et la cohérence des rôles. | **Oui : les opinions** |

**Les positions ne s'allument pas sans une confirmation** : il faut cocher que les personnes du serveur *sont informées* et que le cadre juridique est validé ([CONFORMITE.md](CONFORMITE.md)). Sans cela, l'interface refuse d'enregistrer et le serveur ramène la case à « éteinte ». Les messages d'une personne qui a demandé à ne plus être enregistrée (`/dindon stop`) **ne sont jamais lus** (par la lecture automatique comme à la main).

## Réglages

- **Tous les** : 10, 15, 30 minutes, 1, 3, 6 heures, 1 jour. Un cycle ne fait que ce qu'il y a à faire : **s'il n'y a rien de nouveau, il ne demande rien aux modèles.**
- **Conversations lues par cycle** (positions, 1 à 500) : un gros retard se résorbe sur plusieurs cycles, les plus importantes d'abord.
- **Heures de lecture** : de *h* à *h* dans le fuseau `DINDON_TIMEZONE` (Europe/Paris par défaut). 0 h → 24 h : à toute heure ; 22 h → 6 h : la nuit (le passage de minuit est géré).
- **Lancer un cycle maintenant** : démarre un cycle dans les secondes qui suivent, quels que soient l'intervalle et les heures, même si la lecture est éteinte ; ce qui est lu suit toujours les cases cochées.
- La page dit ce qu'il reste à lire, quand a eu lieu le dernier cycle et son résultat, et quand viendra le prochain.

## Comment ça se comporte

- **Une analyse à la fois.** Un cycle ne démarre pas si une analyse tourne (la vôtre ou la précédente), et reprend à l'intervalle suivant. L'interface continue d'afficher l'avancement dans les pages Thèmes et Positions.
- **Les limites de performance s'appliquent** ([PERFORMANCE.md](PERFORMANCE.md)) : un cycle en mode *Économe* est lent par construction.
- Si Ollama ne répond pas ou si un modèle manque, le cycle le dit (panneau et page Système) et recommence à l'intervalle suivant ; il ne bloque ni le bot ni l'application.
- Un redémarrage de l'application ne relance pas un cycle en double : le début du cycle est noté avant qu'il commence.
- Les cycles passent les serveurs un par un. Les journaux ne disent que des nombres et des noms d'étapes, jamais un message.

## Ce que ça ne règle pas

- La lecture des positions reste la plus lourde (environ 15 secondes par conversation à pleine vitesse) : sur un serveur très actif, choisissez des heures de nuit, un petit lot et le profil *Équilibré* ou *Économe*.
- **La qualité de la lecture n'a été mesurée que sur des données inventées** (ANALYSE.md, SERVEUR-DE-TEST.md) : ne vous fiez pas à un score avant d'avoir relu des citations sur vos vraies conversations.
- Les propositions et leurs poids sur les axes restent **proposés** : rien ne les valide automatiquement.
