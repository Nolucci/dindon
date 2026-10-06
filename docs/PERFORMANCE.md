# Limiter ce que Dindon prend de la machine

Dindon peut tourner **plus doucement** pour ne pas saturer la machine (processeur, GPU, mémoire, base de données), **au prix de sa vitesse**. Rien n'est perdu : l'IA met plus de temps, et les messages du bot apparaissent un peu plus tard sur la carte.

**Où** : page **Système** → panneau **Performance**. Quatre profils (*Économe*, *Équilibré*, *Plein régime*, *Personnalisé*) et cinq réglages. Un changement est pris en compte par le **bot dans la demi-minute** et par **l'IA pendant qu'elle travaille** (au plus 5 secondes après) : rien à redémarrer. Les réglages sont gardés dans la base (`runtime_settings`).

| Réglage | Ce qu'il fait | Prix |
| --- | --- | --- |
| **IA : part du temps où elle travaille** (10 à 100 %) | Après chaque appel au modèle qui a duré *t* secondes, l'IA attend *t* × (100 / part − 1) secondes. À 50 %, elle prend le double du temps et la machine souffle la moitié du temps ; à 25 %, quatre fois. Une pause se coupe tout de suite si on arrête l'analyse. | Plus lent |
| **IA : fils de calcul** | Limite les fils des modèles (0 : Ollama décide). Sur un Mac, le GPU fait l'essentiel : l'effet est faible. | Plus lent |
| **IA : modèles gardés en mémoire** | Combien de temps un modèle reste chargé après usage (de « libéré tout de suite » à 30 minutes). | Recharger le modèle à chaque reprise |
| **IA : conversations traitées à la fois** | Taille des lots de vecteurs (1 à 32). | Plus d'appels |
| **Bot : regroupement des écritures** (0,1 à 10 s) | Les messages d'un salon attendent ce temps puis sont écrits **ensemble** : moins de transactions, moins de travail pour la base. | Un message apparaît jusqu'à ce temps plus tard |

Profils : **Plein régime** = comme avant (100 %, 10 minutes, lots de 16, 0,3 s) ; **Équilibré** = 60 %, 5 minutes, lots de 8, 1 s ; **Économe** = 25 %, modèles libérés tout de suite, un quart des fils, lots de 4, 3 s.

## Ce que ça ne règle pas

- Le **bot** consomme très peu (environ 50 Mo et presque aucun processeur) : le seul réglage utile est le regroupement des écritures. Il ne ralentit jamais la **réception** des messages.
- L'IA tourne dans **Ollama**, hors de Dindon : si Ollama est utilisé par autre chose, ou si plusieurs lectures tournent en même temps, la machine peut quand même être chargée. Une seule analyse à la fois est permise par Dindon.
- Ce réglage limite l'IA **par appel** : un seul appel très long (un gros modèle sur un long texte) charge la machine pendant sa durée.
- La **lecture des positions** (environ 15 secondes par conversation à pleine vitesse) est de loin le plus gros consommateur : en mode Économe, comptez de l'ordre d'une minute par conversation.
- Rien ne tient compte de la **batterie** : sur un portable, branchez-le, ou choisissez *Économe*.
