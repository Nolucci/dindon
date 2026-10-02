# Dindon --- architecture globale cible pour Discord

**Date : 2 octobre 2026**\
**But :** disposer d'une vue à la fois macro et détaillée de
l'enchaînement complet de Dindon, depuis Discord jusqu'à la carte, aux
preuves et aux analyses IA.

------------------------------------------------------------------------

# 1. Vue macro

L'architecture cible peut être comprise comme sept couches :

``` text
┌───────────────────────────────────────────────────────────────┐
│ 1. DISCORD                                                   │
│ Serveur · membres · salons · messages · réactions · rôles    │
└──────────────────────────┬────────────────────────────────────┘
                           │ Gateway / API Discord
                           ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. ADAPTATEUR DISCORD                                        │
│ Bot officiel · événements · normalisation vers JSON v2       │
└──────────────────────────┬────────────────────────────────────┘
                           │ contrat JSON v2
                           ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. CŒUR DINDON                                               │
│ Ingestion · identités · messages · graphe · consentement     │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│ 4. POSTGRESQL + PGVECTOR                                     │
│ Source de vérité · graphe · tâches · preuves · vecteurs      │
└──────────────┬───────────────────────────────┬────────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────┐      ┌─────────────────────────────┐
│ 5A. TEMPS RÉEL           │      │ 5B. ANALYSE IA             │
│ NOTIFY → SSE             │      │ SQL → vecteurs → modèles   │
└──────────────┬───────────┘      └─────────────┬───────────────┘
               │                                │
               └──────────────┬─────────────────┘
                              ▼
┌───────────────────────────────────────────────────────────────┐
│ 6. API / CONTRÔLE D'ACCÈS                                    │
│ FastAPI · sessions · droits · consentement · endpoints       │
└──────────────────────────┬────────────────────────────────────┘
                           │ HTTPS / SSE
                           ▼
┌───────────────────────────────────────────────────────────────┐
│ 7. INTERFACE                                                 │
│ Svelte + Sigma.js → Web locale ou Discord Activity           │
└───────────────────────────────────────────────────────────────┘
```

Le principe important est que **Discord n'est qu'une source et une
interface**.

Le cœur métier reste Dindon.

------------------------------------------------------------------------

# 2. Deux flux parallèles

Dindon fonctionne en réalité avec deux vitesses.

## Flux rapide

``` text
Message Discord
      ↓
Bot
      ↓
JSON v2
      ↓
Ingestion
      ↓
PostgreSQL
      ↓
mise à jour du graphe
      ↓
NOTIFY
      ↓
SSE
      ↓
carte
```

Objectif : quelques centaines de millisecondes à quelques secondes.

Aucune IA n'est nécessaire.

## Flux lent

``` text
Messages
   ↓
conversation
   ↓
tri
   ↓
embeddings
   ↓
thèmes
   ↓
affirmations
   ↓
propositions
   ↓
positions / relations
   ↓
vérification
   ↓
agrégation SQL
   ↓
fiche utilisateur
```

Objectif : produire une analyse plus tard, avec preuves et incertitude.

Les deux flux ne doivent pas se bloquer mutuellement.

------------------------------------------------------------------------

# 3. Couche Discord

## 3.1 Une application Discord Dindon

La cible logique est une application Discord unique pouvant regrouper :

-   le bot ;
-   les commandes Discord ;
-   l'Activity ;
-   l'identité OAuth de l'application.

Conceptuellement :

``` text
                 Application Discord Dindon
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
         Bot / Gateway          Activity
         collecte              interface
```

Le bot transporte les événements vers Dindon.

L'Activity transporte l'expérience utilisateur vers Discord.

------------------------------------------------------------------------

# 4. Le bot Discord

Le bot doit rester aussi mince que possible.

Il ne doit pas contenir la logique d'analyse politique.

Sa responsabilité :

``` text
événement Discord
       ↓
validation minimale
       ↓
conversion vers le contrat Dindon
       ↓
envoi à l'ingestion
```

## Événements utiles

-   création de message ;
-   modification ;
-   suppression ;
-   réponse ;
-   mention ;
-   ajout de réaction ;
-   suppression de réaction ;
-   création / activité des fils selon les besoins ;
-   changement de rôle lorsque les rôles idéologiques doivent être
    synchronisés.

## Ce que le bot ne doit pas faire

Éviter :

``` text
Discord → bot → LLM
```

Préférer :

``` text
Discord → bot → Dindon → PostgreSQL → worker IA
```

Ainsi, une panne du modèle IA n'empêche jamais la collecte ou la carte
de fonctionner.

------------------------------------------------------------------------

# 5. Contrat JSON v2

Le contrat existant reste la frontière entre Discord et Dindon.

``` text
                  ┌─ export manuel
Discord ──────────┼─ surveillance
                  └─ bot Gateway
                          │
                          ▼
                       JSON v2
                          │
                          ▼
                       ingestion
```

Avantage :

le cœur de Dindon ne doit pas savoir si le message vient :

-   d'un export ;
-   de la surveillance ;
-   du bot direct.

Toutes les sources deviennent interchangeables.

------------------------------------------------------------------------

# 6. Ingestion

L'ingestion reste le point d'entrée central.

Elle doit conserver les propriétés actuelles :

-   idempotence ;
-   identité Discord par ID ;
-   gestion des exports qui se chevauchent ;
-   modifications ;
-   suppressions ;
-   réactions ;
-   événements arrivant en retard ;
-   transactions atomiques.

Flux :

``` text
JSON v2
   ↓
validation
   ↓
transaction PostgreSQL
   ├── utilisateur
   ├── message
   ├── mentions
   ├── réactions
   ├── pièces jointes
   ├── relations
   └── événement temps réel
```

------------------------------------------------------------------------

# 7. Couche confidentialité / consentement

Cette couche devrait être placée très tôt dans l'architecture cible.

Conceptuellement :

``` text
événement Discord
      ↓
identité Discord
      ↓
politique de traitement
      │
      ├── non participant
      │       ↓
      │   pas de profil IA
      │
      └── participant
              ↓
         pipeline autorisé
```

Table conceptuelle :

``` text
privacy_subject
---------------
discord_user_id
guild_id
analysis_opt_in
consent_version
consented_at
withdrawn_at
deletion_requested_at
forgotten_at
```

Important :

la suppression durable doit empêcher un backfill ou un événement Gateway
de recréer involontairement le profil supprimé.

------------------------------------------------------------------------

# 8. PostgreSQL comme centre

PostgreSQL reste la source de vérité.

Il peut continuer à jouer plusieurs rôles :

``` text
PostgreSQL
│
├── messages
├── utilisateurs
├── salons
├── réactions
├── graphe
├── consentements
├── conversations
├── thèmes
├── affirmations
├── propositions
├── preuves
├── positions
├── relations
├── scores
├── tâches IA
├── pgvector
└── LISTEN / NOTIFY
```

Pas besoin d'introduire immédiatement :

-   Kafka ;
-   Redis ;
-   Neo4j ;
-   Elasticsearch ;
-   une architecture microservices.

La simplicité actuelle est un avantage.

------------------------------------------------------------------------

# 9. Graphe social temps réel

Lorsqu'un événement arrive :

``` text
Alice répond à Bob
       ↓
message ingéré
       ↓
relation Alice ↔ Bob recalculée
       ↓
poids temporel mis à jour
       ↓
PostgreSQL NOTIFY
       ↓
FastAPI
       ↓
SSE
       ↓
Sigma.js
       ↓
le lien Alice–Bob s'illumine
```

Cette chaîne ne dépend pas de l'IA.

------------------------------------------------------------------------

# 10. Construction des conversations

Le pipeline IA commence après l'ingestion.

``` text
messages bruts
      ↓
SQL
      ↓
fenêtres conversationnelles
```

Règles prévues :

-   séparation après une période de silence ;
-   taille maximale ;
-   regroupement des réponses et échanges pertinents ;
-   exclusion des éléments inutiles.

La conversation devient l'unité principale d'analyse plutôt que le
message isolé.

------------------------------------------------------------------------

# 11. Tri déterministe

Avant d'utiliser un modèle :

``` text
conversation
    ↓
SQL / règles
    ↓
utile ?
```

Écarter notamment :

-   bots ;
-   messages vides ;
-   bruit ;
-   réactions purement conversationnelles sans contenu exploitable ;
-   doublons.

L'objectif est de ne pas dépenser du calcul IA sur ce que SQL peut
éliminer.

------------------------------------------------------------------------

# 12. Embeddings et pgvector

Les embeddings servent principalement à retrouver et regrouper.

``` text
conversation
     ↓
embedding
     ↓
pgvector
     ↓
similarités
     ↓
thèmes / preuves candidates
```

Principe :

> une proximité vectorielle n'est jamais une preuve d'opinion.

Elle sert à trouver les passages à examiner.

------------------------------------------------------------------------

# 13. Découverte des thèmes

Les thèmes doivent être découverts indépendamment de l'identité des
personnes.

``` text
conversations
      ↓
vecteurs
      ↓
clusters
      ↓
thèmes candidats
      ↓
validation utilisateur
```

Exemples abstraits :

``` text
cluster 17
 ├─ conversation A
 ├─ conversation B
 └─ conversation C
        ↓
"politique énergétique"
```

La validation humaine évite de transformer automatiquement un cluster
statistique en catégorie définitive.

------------------------------------------------------------------------

# 14. Extraction des affirmations

Le LLM principal reçoit ensuite des conversations sélectionnées.

Sa tâche :

``` text
conversation
      ↓
LLM extracteur
      ↓
affirmation
+ auteur
+ preuves
+ contexte
+ incertitude
```

Exemple structurel :

``` text
claim
-----
person_id
text
evidence_message_ids[]
confidence
model_version
prompt_version
```

Règle :

> sans message justificatif, aucune affirmation n'est créée.

------------------------------------------------------------------------

# 15. Normalisation

Plusieurs formulations peuvent représenter la même proposition.

``` text
"il faudrait augmenter le SMIC"
"le minimum salarial est trop faible"
"le salaire minimum devrait monter"

             ↓

     proposition canonique

       "augmenter le SMIC"
```

On conserve toujours le lien vers l'affirmation originale.

------------------------------------------------------------------------

# 16. Classification System One

Les modèles rapides peuvent intervenir ici.

Entrée :

``` text
affirmation + proposition
```

Sortie :

``` text
pour
contre
nuancé
inconnu
```

Autres usages :

``` text
réponse
  ↓
accord / désaccord / soutien /
information / moquerie / inconnu
```

Routage :

``` text
System One
   │
   ├── cas clair ─────────► continuer
   │
   └── cas incertain ─────► gros LLM
```

------------------------------------------------------------------------

# 17. Vérificateur contradictoire

Pour les conclusions sensibles :

``` text
conclusion proposée
+ preuves
       ↓
vérificateur
       ↓
cherche pourquoi
la conclusion pourrait être fausse
```

Il recherche :

-   négation ;
-   sarcasme ;
-   citation ;
-   opinion rapportée ;
-   hypothèse ;
-   contexte manquant ;
-   contradiction ;
-   changement d'avis.

Sorties :

``` text
confirmé
contesté
ambigu
preuves insuffisantes
```

Les cas ambigus vont dans :

``` text
À REVOIR
```

------------------------------------------------------------------------

# 18. Dimension temporelle

Une position n'est pas une propriété permanente.

Structure préférable :

``` text
personne
  │
  ├── janvier → favorable
  ├── avril   → incertain
  └── septembre → opposé
```

Dindon peut ainsi distinguer :

-   changement d'avis ;
-   contradiction ;
-   nuance ;
-   erreur d'analyse.

------------------------------------------------------------------------

# 19. Agrégation SQL

L'IA ne produit pas directement le score final.

``` text
observations validées
        ↓
SQL
        ↓
pondération
        ↓
axe
        ↓
score + incertitude
```

Avantages :

-   reproductible ;
-   testable ;
-   explicable ;
-   modifiable sans refaire toute l'analyse.

------------------------------------------------------------------------

# 20. Traçabilité complète

Toute conclusion doit pouvoir être parcourue en sens inverse.

``` text
score
 ↓
axe
 ↓
proposition
 ↓
position
 ↓
affirmation
 ↓
conversation
 ↓
message Discord
```

Et chaque étape doit connaître :

-   modèle ;
-   version ;
-   prompt ;
-   date ;
-   preuves ;
-   confiance ;
-   statut de vérification.

------------------------------------------------------------------------

# 21. FastAPI

FastAPI devient la façade contrôlée du système.

Responsabilités :

``` text
FastAPI
│
├── authentification
├── autorisation
├── API graphe
├── API personnes
├── API preuves
├── API thèmes
├── API positions
├── API consentement
├── API suppression
└── SSE temps réel
```

L'interface ne doit jamais accéder directement à PostgreSQL.

------------------------------------------------------------------------

# 22. Interface locale actuelle

L'interface actuelle peut continuer à fonctionner :

``` text
navigateur local
      ↓
127.0.0.1
      ↓
FastAPI
      ↓
PostgreSQL
```

Elle reste utile pour :

-   développement ;
-   administration ;
-   tests ;
-   analyse privée.

Elle ne doit pas forcément disparaître avec l'Activity Discord.

------------------------------------------------------------------------

# 23. Discord Activity

L'Activity devient une seconde interface.

``` text
Discord
   ↓
Activity Dindon
   ↓
frontend Svelte
   ↓
API Dindon sécurisée
   ↓
PostgreSQL
```

On peut réutiliser une grande partie des composants Svelte/Sigma.

Mais l'Activity nécessite une architecture réseau différente de
l'interface localhost.

------------------------------------------------------------------------

# 24. Frontière publique / privée

C'est probablement le changement architectural le plus important pour
Discord.

Aujourd'hui :

``` text
Internet
   X
   │
Dindon local
```

Avec Activity :

``` text
Discord Activity
      │
      ▼
┌──────────────────────┐
│ façade publique      │
│ HTTPS + auth Discord │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ services privés      │
│ Dindon / PostgreSQL  │
│ workers / Ollama     │
└──────────────────────┘
```

PostgreSQL et Ollama ne doivent jamais être exposés directement.

------------------------------------------------------------------------

# 25. Authentification Discord

L'Activity doit savoir :

``` text
qui est la personne ?
sur quel serveur ?
quels droits possède-t-elle ?
a-t-elle consenti ?
que peut-elle voir ?
```

Le backend associe donc :

``` text
session Activity
      ↓
Discord user ID
      ↓
guild ID
      ↓
permissions Dindon
```

Ne jamais faire confiance à un `user_id` simplement envoyé par le
navigateur.

------------------------------------------------------------------------

# 26. Autorisations applicatives

Dindon devrait avoir ses propres droits, distincts des permissions
Discord brutes.

Exemple :

``` text
MEMBRE
├─ voir la carte générale
├─ voir sa fiche
└─ gérer son consentement

MODÉRATEUR DINDON
├─ voir les signalements
└─ gérer certains contenus

ADMIN DINDON
├─ configurer les salons
├─ gérer les axes
├─ lancer des recalculs
└─ administrer l'instance
```

Les données sensibles accessibles à chaque rôle doivent être décidées
explicitement.

------------------------------------------------------------------------

# 27. Première ouverture de l'Activity

Parcours possible :

``` text
L'utilisateur ouvre Dindon
          ↓
authentification Discord
          ↓
serveur reconnu ?
          ↓
information confidentialité
          ↓
choix de participation
          ↓
consentement enregistré
          ↓
interface
```

Un refus de participer à l'analyse ne doit pas être confondu avec
l'impossibilité technique d'utiliser Discord.

------------------------------------------------------------------------

# 28. Parcours utilisateur normal

Une fois installé :

``` text
1. membre écrit dans Discord
2. bot reçoit l'événement
3. ingestion
4. PostgreSQL
5. graphe mis à jour
6. Activity reçoit le changement
7. lien s'illumine

                 puis

8. conversation devient analysable
9. worker IA la traite
10. affirmations créées
11. positions vérifiées
12. SQL recalcule les axes
13. Activity reçoit la mise à jour
14. fiche enrichie
```

Le graphe apparaît immédiatement.

L'analyse arrive plus tard.

------------------------------------------------------------------------

# 29. Suppression

Flux recommandé :

``` text
utilisateur
    ↓
"retirer mon consentement / supprimer"
    ↓
API
    ↓
marquage persistant
    ↓
arrêt des nouvelles analyses
    ↓
suppression des données concernées
    ↓
tombstone / oubli durable
    ↓
backfills futurs
    X
ne recréent pas le profil
```

Ce mécanisme doit intervenir avant l'ouverture réelle du système à des
utilisateurs.

------------------------------------------------------------------------

# 30. Résilience

Le système doit continuer à fonctionner partiellement lorsqu'un
composant tombe.

## Ollama indisponible

``` text
bot ✓
ingestion ✓
graphe ✓
Activity ✓
IA ✗ temporairement
```

Les tâches restent en attente.

## Activity indisponible

``` text
bot ✓
ingestion ✓
IA ✓
interface Discord ✗
```

## Discord Gateway coupé

``` text
reconnexion
+
rattrapage
```

## Worker planté

La tâche doit pouvoir être reprise sans produire de doublons.

------------------------------------------------------------------------

# 31. Déploiement cible conceptuel

Une architecture raisonnable :

``` text
                    INTERNET
                       │
                  Discord API
                       │
                 ┌─────▼─────┐
                 │ Bot Dindon │
                 └─────┬─────┘
                       │
                réseau applicatif
                       │
        ┌──────────────▼──────────────┐
        │          FastAPI            │
        │ ingestion + API + SSE       │
        └───────────┬───────┬─────────┘
                    │       │
              ┌─────▼───┐   │
              │Postgres │   │
              │pgvector │   │
              └─────┬───┘   │
                    │       │
              ┌─────▼───┐   │
              │ Workers │   │
              └─────┬───┘   │
                    │       │
              ┌─────▼───┐   │
              │ Ollama  │   │
              └─────────┘   │
                            │
Internet HTTPS              │
      │                     │
┌─────▼─────────────────────▼──┐
│ façade / API publique Activity│
└──────────────┬────────────────┘
               │
        ┌──────▼──────┐
        │Discord       │
        │Activity      │
        │Svelte/Sigma  │
        └──────────────┘
```

Dans une première implémentation, plusieurs blocs peuvent rester dans le
même processus ou le même Docker Compose.

Le schéma représente des **responsabilités**, pas l'obligation de créer
des microservices.

------------------------------------------------------------------------

# 32. Ce qui existe déjà

Selon l'état actuel de Dindon :

## Déjà construit

-   PostgreSQL ;
-   migrations ;
-   ingestion ;
-   import JSON ;
-   surveillance ;
-   graphe ;
-   pondération temporelle ;
-   FastAPI ;
-   SSE ;
-   Svelte ;
-   Sigma.js ;
-   tests synthétiques ;
-   sécurité locale ;
-   contrat JSON v2.

## Prévu mais non réalisé

-   Ollama en production du projet ;
-   embeddings ;
-   thèmes ;
-   extraction des affirmations ;
-   propositions ;
-   vérification ;
-   bot Gateway ;
-   Activity Discord ;
-   effacement durable ;
-   consentement applicatif ;
-   façade réseau sécurisée.

------------------------------------------------------------------------

# 33. Ordre d'implémentation recommandé

## Phase A --- valider Discord réel

``` text
bot minimal
→ message
→ JSON v2
→ ingestion
→ PostgreSQL
→ SSE
→ carte
```

Objectif : voir un échange réel allumer un lien.

## Phase B --- confidentialité

Ajouter :

-   consentement ;
-   retrait ;
-   oubli durable ;
-   politiques d'accès.

## Phase C --- IA minimale

``` text
conversation
→ LLM
→ affirmation
→ preuve
```

Pas encore de score complexe.

## Phase D --- normalisation

``` text
affirmation
→ proposition
→ position
```

## Phase E --- optimisation

Ajouter :

-   embeddings ;
-   System One ;
-   routage ;
-   vérificateur contradictoire.

## Phase F --- scoring

Brancher les observations validées sur le calcul SQL existant.

## Phase G --- Activity

Adapter l'interface Svelte/Sigma et créer la façade sécurisée.

## Phase H --- durcissement

-   sauvegardes ;
-   reprise ;
-   monitoring ;
-   migrations ;
-   tests de charge ;
-   rotation des secrets ;
-   revue de sécurité ;
-   revue juridique avant ouverture réelle.

------------------------------------------------------------------------

# 34. Le premier vertical slice

Le meilleur premier objectif n'est pas de construire toute
l'architecture.

Construire ceci :

``` text
Alice écrit à Bob dans Discord
          ↓
bot Dindon
          ↓
JSON v2
          ↓
ingestion actuelle
          ↓
PostgreSQL
          ↓
graphe actuel
          ↓
NOTIFY
          ↓
SSE
          ↓
interface actuelle
          ↓
le lien Alice ↔ Bob s'illumine
```

Si cette chaîne fonctionne avec le vrai Discord, la frontière la plus
importante entre le prototype et le monde réel est validée.

Ensuite seulement, ajouter l'Activity.

------------------------------------------------------------------------

# 35. Vue finale condensée

``` text
                           ┌───────────────────┐
                           │      DISCORD      │
                           │ messages / rôles  │
                           └─────────┬─────────┘
                                     │
                                  Gateway
                                     │
                           ┌─────────▼─────────┐
                           │       BOT         │
                           │ adaptateur mince  │
                           └─────────┬─────────┘
                                     │ JSON v2
                           ┌─────────▼─────────┐
                           │    INGESTION      │
                           └─────────┬─────────┘
                                     │
                           ┌─────────▼─────────┐
                           │    POSTGRESQL     │
                           │     PGVECTOR      │
                           └────┬─────────┬────┘
                                │         │
                         temps réel       │ analyse
                                │         │
                         NOTIFY / SSE     ▼
                                │     SQL conversations
                                │         ↓
                                │      embeddings
                                │         ↓
                                │     LLM extraction
                                │         ↓
                                │     System One
                                │         ↓
                                │     vérificateur
                                │         ↓
                                │     agrégation SQL
                                │         │
                                └────┬────┘
                                     │
                           ┌─────────▼─────────┐
                           │      FASTAPI      │
                           │ auth / droits     │
                           │ consentement      │
                           └─────────┬─────────┘
                                     │
                      ┌──────────────┴──────────────┐
                      │                             │
             ┌────────▼────────┐          ┌────────▼────────┐
             │ interface locale│          │ Discord Activity │
             │  Svelte/Sigma   │          │  Svelte/Sigma   │
             └─────────────────┘          └─────────────────┘
```

------------------------------------------------------------------------

# 36. Idée directrice

L'architecture Discord ne doit pas remplacer l'architecture actuelle de
Dindon.

Elle doit **l'envelopper**.

Le bot devient une nouvelle source conforme au contrat existant.

L'Activity devient une nouvelle interface au-dessus de l'API.

Entre les deux, le cœur de Dindon --- ingestion, PostgreSQL, graphe,
preuves, IA et agrégation --- reste indépendant de Discord autant que
possible.

C'est cette séparation qui permettra de développer progressivement le
système sans devoir réécrire ce qui fonctionne déjà.
