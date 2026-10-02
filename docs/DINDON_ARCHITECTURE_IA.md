# Dindon --- architecture IA recommandée

**Date : 2 octobre 2026**\
**Objet :** proposition dédiée à la chaîne d'analyse IA de Dindon.

## 1. Objectif

Dindon ne doit pas demander à un unique modèle de « comprendre une
personne » et de produire directement un classement.

L'approche recommandée est une chaîne spécialisée où chaque composant
réalise une tâche limitée, vérifiable et mesurable :

**SQL → embeddings → LLM extracteur → System One classifieur →
vérificateur contradictoire → agrégation SQL → interface avec preuves**

Principe central :

> **Chaque étage doit pouvoir répondre : « je ne sais pas ».**

Une absence de conclusion est préférable à une position attribuée sans
preuves suffisantes.

------------------------------------------------------------------------

## 2. Séparer extraction et jugement

### Étape A --- Extraction

Le LLM reçoit une conversation ou un petit ensemble de messages et doit
uniquement identifier les affirmations effectivement soutenues par le
texte.

Sortie structurée possible :

-   personne ;
-   affirmation ;
-   identifiants des messages justificatifs ;
-   passage pertinent ;
-   contexte nécessaire ;
-   degré d'ambiguïté ;
-   éventuelle indication qu'aucune affirmation exploitable n'est
    présente.

Le modèle ne produit pas encore de score idéologique.

### Étape B --- Classification

Un autre composant reçoit l'affirmation extraite et doit décider si elle
correspond à une proposition connue.

Exemple :

-   affirmation : « le salaire minimum devrait être augmenté » ;
-   proposition normalisée : « augmenter le SMIC » ;
-   position : favorable ;
-   confiance ;
-   preuve source.

Cette séparation permet de mesurer indépendamment les erreurs
d'extraction et les erreurs de classification.

------------------------------------------------------------------------

## 3. Rôle du LLM principal

Le modèle le plus capable doit être réservé aux tâches où la
compréhension du langage et du contexte est indispensable :

-   extraction d'affirmations ;
-   négations complexes ;
-   citations d'autres personnes ;
-   ironie et sarcasme ;
-   changement d'opinion ;
-   nuances ;
-   contexte conversationnel ;
-   distinction entre opinion personnelle et opinion rapportée ;
-   résumé explicatif ;
-   identification des preuves.

Il ne devrait pas produire directement les scores finaux.

Le LLM produit des **observations structurées** que les étapes suivantes
peuvent contrôler.

------------------------------------------------------------------------

## 4. Rôle d'un modèle System One

Les modèles rapides de type Jev, Laya, Kev ou équivalent sont
intéressants pour les tâches à choix fermé et répétitives.

Exemples :

### Position

-   pour ;
-   contre ;
-   nuancé ;
-   insuffisant / inconnu.

### Nature d'une réponse

-   accord ;
-   désaccord ;
-   soutien ;
-   information ;
-   moquerie ;
-   autre ;
-   insuffisant.

### Attribution à un thème

Lorsque la liste des thèmes existe déjà :

-   thème A ;
-   thème B ;
-   thème C ;
-   aucun ;
-   ambigu.

### Routage

Le System One peut aussi décider :

-   cas simple → résultat accepté ;
-   cas incertain → envoyer au gros LLM ;
-   cas contradictoire → vérification supplémentaire.

Le System One ne remplace donc pas nécessairement le LLM. Il peut servir
de **filtre extrêmement rapide** devant lui.

------------------------------------------------------------------------

## 5. Architecture en cascade

Une architecture possible :

### Niveau 0 --- SQL

Travail déterministe :

-   regrouper les messages en conversations ;
-   supprimer les messages manifestement inutiles ;
-   gérer les fenêtres temporelles ;
-   calculer les agrégations ;
-   appliquer les règles finales.

### Niveau 1 --- Embeddings

Objectif principal :

-   trouver les messages et affirmations sémantiquement proches ;
-   regrouper les discussions par thème ;
-   retrouver des preuves potentielles.

Les embeddings ne devraient pas décider seuls qu'une personne possède
une opinion.

### Niveau 2 --- System One

Traiter les cas simples et très nombreux.

Exemple :

`message/proposition → pour / contre / nuancé / inconnu`

Si confiance suffisante :

→ continuer.

Sinon :

→ envoyer au LLM.

### Niveau 3 --- LLM

Traiter :

-   ambiguïtés ;
-   extraction complexe ;
-   conversations longues ;
-   sarcasme ;
-   négations ;
-   citations ;
-   conflits contextuels.

### Niveau 4 --- Vérificateur contradictoire

Une seconde analyse cherche volontairement pourquoi la première
conclusion pourrait être fausse.

### Niveau 5 --- Agrégation SQL

Une fois les observations validées :

-   agréger les preuves ;
-   pondérer leur ancienneté si nécessaire ;
-   gérer les contradictions ;
-   calculer les scores ;
-   comparer éventuellement avec les rôles déclarés.

------------------------------------------------------------------------

## 6. Vérificateur contradictoire

Pour les conclusions importantes, utiliser un second passage dont la
mission n'est pas de confirmer le premier modèle.

Question conceptuelle :

> « Voici la conclusion proposée et les messages utilisés comme preuves.
> Existe-t-il une raison textuelle ou contextuelle pour laquelle cette
> conclusion serait incorrecte ? »

Le vérificateur cherche notamment :

-   citation d'une autre personne ;
-   sarcasme ;
-   négation ;
-   hypothèse ;
-   question ;
-   opinion rapportée ;
-   contexte absent ;
-   contradiction ;
-   changement d'avis ;
-   preuve trop faible.

Sorties possibles :

-   confirmé ;
-   contesté ;
-   ambigu ;
-   contexte insuffisant.

Un résultat contesté ou ambigu passe dans une file **à revoir** plutôt
que d'être transformé automatiquement en score certain.

------------------------------------------------------------------------

## 7. Gérer les changements d'opinion dans le temps

Dindon ne devrait pas considérer une position comme une propriété
permanente d'une personne.

Modèle préférable :

**position + période + preuves**

Exemple :

-   janvier : favorable ;
-   avril : incertain ;
-   septembre : opposé.

L'interface pourrait montrer une trajectoire plutôt qu'un unique état.

Cela permet de distinguer :

-   contradiction réelle ;
-   changement d'avis ;
-   nuance contextuelle ;
-   anciennes preuves devenues moins représentatives.

Les scores peuvent conserver une décroissance temporelle, mais les
preuves historiques doivent rester consultables selon les règles de
conservation applicables.

------------------------------------------------------------------------

## 8. Embeddings : retrouver plutôt que juger

L'usage principal des embeddings devrait être la **recherche de
candidats**.

Exemple :

1.  une proposition existe : « augmenter le SMIC » ;
2.  pgvector recherche les messages et affirmations proches
    sémantiquement ;
3.  le classifieur ou le LLM examine les passages ;
4.  le système décide s'ils constituent réellement une preuve.

Ainsi :

**similarité sémantique ≠ position politique**

Les embeddings réduisent l'espace de recherche ; ils ne rendent pas le
verdict.

------------------------------------------------------------------------

## 9. Abstention obligatoire

Chaque composant devrait disposer d'une sortie explicite d'abstention.

Par exemple :

-   `unknown`
-   `insufficient_evidence`
-   `ambiguous`
-   `conflicting_evidence`
-   `needs_context`

Il ne faut pas forcer le modèle à choisir entre « pour » et « contre ».

Une métrique essentielle devient alors :

> **Quand le système affirme quelque chose, à quelle fréquence a-t-il
> raison ?**

Il peut être préférable d'obtenir :

-   moins de couverture ;
-   beaucoup plus de précision.

Pour Dindon, une conclusion manquante est moins problématique qu'une
opinion politique faussement attribuée.

------------------------------------------------------------------------

## 10. Corpus d'évaluation

Avant de sélectionner définitivement Jev, Laya ou un autre modèle,
construire un corpus commun.

### Première cible

**200 exemples annotés**, puis augmenter progressivement vers 500 ou
davantage.

### Le corpus doit contenir

-   positions explicites ;
-   positions implicites ;
-   négations ;
-   sarcasme ;
-   citations ;
-   questions ;
-   opinions rapportées ;
-   changement d'avis ;
-   contradictions ;
-   messages hors sujet ;
-   manque de contexte ;
-   nuances ;
-   cas impossibles à déterminer.

Une partie du corpus devrait être annotée indépendamment par deux
personnes afin de mesurer également le désaccord humain.

------------------------------------------------------------------------

## 11. Benchmark des modèles

Faire passer exactement les mêmes exemples à :

-   Jev ;
-   Laya ;
-   autres System One candidats ;
-   LLM local principal.

Mesurer séparément chaque tâche.

### Mesures

-   précision ;
-   rappel ;
-   F1 lorsque pertinent ;
-   matrice de confusion ;
-   faux positifs ;
-   faux négatifs ;
-   précision conditionnelle lorsque le modèle accepte de répondre ;
-   taux d'abstention ;
-   qualité de l'abstention ;
-   latence ;
-   mémoire ;
-   débit ;
-   coût énergétique approximatif si utile.

Ne pas choisir le modèle uniquement sur l'accuracy globale.

Pour Dindon, les **fausses attributions de position** méritent une
attention particulière.

------------------------------------------------------------------------

## 12. Routage dynamique

Une optimisation intéressante consiste à ne pas envoyer tous les cas au
LLM.

Exemple :

1.  System One traite le message.
2.  Si le cas est simple et la confiance calibrée est suffisante : →
    résultat conservé.
3.  Si ambigu : → LLM.
4.  Si LLM et System One divergent : → vérificateur contradictoire.
5.  Si divergence persistante : → `à revoir`.

Cela permet de réserver la puissance du modèle lourd aux situations qui
en ont réellement besoin.

------------------------------------------------------------------------

## 13. Provenance complète

Chaque conclusion devrait être reconstructible.

Chaîne :

**score → proposition → position → affirmation → conversation → message
Discord**

Conserver avec chaque étape :

-   IDs des messages ;
-   modèle utilisé ;
-   version du modèle ;
-   prompt/version de tâche ;
-   version des embeddings ;
-   version des axes ;
-   date du calcul ;
-   niveau de confiance ;
-   résultat du vérificateur ;
-   éventuelle validation humaine.

Si un modèle ou un axe change, Dindon doit pouvoir savoir quels
résultats nécessitent un recalcul.

------------------------------------------------------------------------

## 14. Interface : montrer les preuves avant le score

Éviter une présentation comme :

> « Axe X : 73/100 »

sans contexte.

Présentation préférable :

### Proposition X

-   3 preuves favorables ;
-   1 preuve contradictoire ;
-   2 éléments ambigus ;
-   confiance : modérée ;
-   période : janvier--septembre ;
-   dernière preuve : date ;
-   accès aux messages justificatifs.

Le score agrégé peut rester utile pour la carte, mais la fiche détaillée
doit rendre l'incertitude et les preuves visibles.

------------------------------------------------------------------------

## 15. Gestion des contradictions

Une contradiction ne doit pas automatiquement être considérée comme une
erreur.

Elle peut signifier :

-   changement d'opinion ;
-   différence de contexte ;
-   nuance ;
-   sarcasme mal interprété ;
-   mauvaise extraction ;
-   réelle incohérence.

Stocker les observations contradictoires séparément avant l'agrégation.

Le système doit préférer :

> « preuves contradictoires »

à :

> « la personne pense X »

lorsque les données ne permettent pas de trancher proprement.

------------------------------------------------------------------------

## 16. Agrégation déterministe

L'IA produit les observations.

Le code produit le score.

Avantages :

-   reproductibilité ;
-   auditabilité ;
-   tests unitaires ;
-   possibilité de modifier les règles sans refaire toute l'extraction ;
-   comparaison de plusieurs méthodes de scoring ;
-   explication précise d'un résultat.

Le modèle ne devrait donc pas répondre directement :

> « cette personne est 72 % sur cet axe ».

Il devrait produire les éléments permettant au SQL de calculer ce
résultat selon des règles connues.

------------------------------------------------------------------------

## 17. Proposition de pipeline final

``` text
Messages Discord
       │
       ▼
Regroupement SQL en conversations
       │
       ▼
Tri déterministe
       │
       ▼
Embeddings / recherche de candidats
       │
       ▼
LLM extracteur ──────────────┐
       │                     │
       ▼                     │
Affirmations + preuves       │
       │                     │
       ▼                     │
System One                   │
(position / relation / thème)│
       │                     │
       ├── confiance faible ─┘ → LLM
       │
       ▼
Vérificateur contradictoire
       │
       ├── ambigu → À REVOIR
       │
       ▼
Observations validées
       │
       ▼
Agrégation SQL
       │
       ▼
Scores / trajectoires
       │
       ▼
Interface
preuves + contradictions + incertitude
```

------------------------------------------------------------------------

## 18. Ordre d'implémentation conseillé

### Étape 1

Créer le corpus d'évaluation.

### Étape 2

Installer un LLM local de référence et implémenter l'extraction
d'affirmations avec preuves.

### Étape 3

Ajouter les sorties d'abstention dès le début.

### Étape 4

Tester Jev, Laya et d'autres petits modèles sur les tâches fermées.

### Étape 5

Calibrer le routage System One → LLM.

### Étape 6

Ajouter le vérificateur contradictoire.

### Étape 7

Versionner modèles, prompts, embeddings et axes.

### Étape 8

Implémenter les contradictions et changements de position dans le temps.

### Étape 9

Brancher l'agrégation SQL.

### Étape 10

Afficher preuves, contradictions et incertitude dans l'interface.

------------------------------------------------------------------------

## 19. Principe directeur

L'objectif de Dindon ne devrait pas être :

> **« produire une opinion politique pour chaque personne ».**

L'objectif technique plus robuste est :

> **« identifier les affirmations que les messages permettent réellement
> d'étayer, conserver leurs preuves, représenter les contradictions et
> s'abstenir lorsque les données ne suffisent pas ».**

Cette différence doit guider toute l'architecture IA.

Le résultat final devient alors moins dépendant d'un modèle unique et
beaucoup plus facile à tester, auditer, corriger et faire évoluer.
