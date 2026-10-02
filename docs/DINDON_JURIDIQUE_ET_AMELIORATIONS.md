# Dindon --- cadre juridique et améliorations techniques

**Date : 2 octobre 2026**\
**Objet :** synthèse de travail sur les risques juridiques liés au
traitement d'opinions politiques et feuille de route technique avant un
usage réel ou commercial.

> **Important :** ce document est une synthèse technique et
> documentaire, pas un avis juridique. Pour une commercialisation ou un
> déploiement impliquant de vraies personnes, une validation par un
> juriste spécialisé en protection des données ou un DPO est
> recommandée.

## 1. Point de départ : ce que fait Dindon

Dindon est conçu comme une carte vivante d'un serveur Discord. Il
collecte les messages, représente les interactions entre membres et
prévoit, dans ses phases IA, d'extraire les thèmes abordés, les
affirmations de chaque personne, leurs positions sur des propositions et
leur rapprochement avec des axes ou rôles idéologiques.

Le projet possède déjà un socle technique conséquent : PostgreSQL,
ingestion idempotente, gestion des modifications et exports en retard,
graphe des interactions, API, SSE et interface Svelte/Sigma. En
revanche, le document actuel précise que les 78 tests utilisent un faux
Discord et qu'aucun test n'a encore été réalisé contre Discord réel.

Cette distinction est importante : le socle de collecte et de
visualisation peut être testé indépendamment de la future analyse
politique.

------------------------------------------------------------------------

## 2. Pourquoi la partie « opinions politiques » change le cadre juridique

### 2.1 Données sensibles

L'article 9 du RGPD classe les données révélant les **opinions
politiques** parmi les catégories particulières de données personnelles.
Leur traitement est en principe interdit, sauf lorsqu'une des exceptions
prévues par l'article 9(2) est applicable.

Pour un projet comme Dindon, une voie envisageable est le **consentement
explicite** de la personne pour une ou plusieurs finalités déterminées.
Il faut toutefois également déterminer la base juridique appropriée au
titre de l'article 6 du RGPD ; l'exception de l'article 9 ne remplace
pas à elle seule cette analyse.

Sources : - CNIL, article 9 du RGPD :
https://www.cnil.fr/fr/reglement-europeen-protection-donnees/chapitre2 -
CNIL, bases légales et données sensibles :
https://www.cnil.fr/fr/les-bases-legales/liceite-essentiel-sur-les-bases-legales -
CEPD/EDPB, principes de licéité et consentement :
https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en

### 2.2 Une opinion déduite peut elle aussi relever des données sensibles

C'est particulièrement important pour Dindon.

Dans l'arrêt **Vyriausioji tarnybinės etikos komisija, C-184/20, 1er
août 2022**, la CJUE a retenu une interprétation large des données
sensibles : des données permettant de révéler une information sensible
par rapprochement ou déduction peuvent relever de l'article 9.

Dans **Commission c. Pologne, C-204/21, 5 juin 2023**, la Cour rappelle
également que l'article 9 couvre non seulement les données
intrinsèquement sensibles mais aussi celles qui révèlent indirectement
de telles informations par déduction ou recoupement.

Conséquence pratique pour Dindon : le fait que l'utilisateur n'écrive
jamais littéralement « mon opinion politique est X » ne suffit pas à
sortir l'analyse du champ des données sensibles si le système déduit
cette information à partir de ses messages.

Sources : - CJUE, C-184/20 :
https://eur-lex.europa.eu/legal-content/FR/ALL/?uri=CELEX:62020CJ0184_RES -
CJUE, C-204/21 :
https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62021CJ0204

### 2.3 Le simple fait que des messages soient visibles sur Discord ne règle pas la question

Il ne faut pas partir du principe qu'un message visible par d'autres
membres d'un serveur peut automatiquement être réutilisé pour établir un
profil politique.

L'exception concernant les données « manifestement rendues publiques »
par la personne doit être appréciée strictement. Par ailleurs, la
finalité initiale d'une conversation Discord et la finalité consistant à
agréger les messages pour construire un profil sont différentes et
doivent être analysées comme telles.

La jurisprudence européenne sur les réseaux sociaux souligne également
que les catégories sensibles bénéficient d'une protection renforcée et
que leur traitement reste soumis aux conditions de l'article 9.

Source complémentaire : - CJUE, C-252/21, Meta Platforms :
https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=celex:62021CJ0446

------------------------------------------------------------------------

## 3. Consentement : pourquoi de simples CGU ne suffisent pas

Si Dindon choisit de s'appuyer sur le consentement, celui-ci doit être
notamment :

-   libre ;
-   spécifique ;
-   éclairé ;
-   univoque ;
-   et, pour les données sensibles, **explicite**.

Le CEPD précise également que le consentement doit résulter d'une action
affirmative et être séparé des conditions générales lorsque cela est
nécessaire. La CNIL recommande, pour les données sensibles, un mécanisme
expressément dédié.

Une formulation du type :

> « En rejoignant ce serveur, vous acceptez les CGU et l'analyse de vos
> messages »

serait donc beaucoup plus fragile qu'un véritable opt-in séparé.

### Conception préférable

Prévoir deux étapes distinctes :

1.  **Accès au serveur Discord** --- règles générales du serveur.
2.  **Participation à Dindon** --- écran spécifique expliquant
    précisément :
    -   quels salons sont concernés ;
    -   quelles données sont collectées ;
    -   que les messages peuvent servir à déduire des thèmes et
        positions ;
    -   qui peut consulter les résultats ;
    -   combien de temps les données sont conservées ;
    -   comment retirer son consentement ;
    -   ce qui est supprimé après retrait.

Exemple fonctionnel :

`[ ] J’accepte expressément que mes messages dans les salons indiqués soient traités par Dindon afin d’identifier les thèmes et positions que ces messages permettent d’étayer.`

Cette formulation n'est qu'un exemple de conception et ne constitue pas
une clause juridiquement validée.

Sources : - CNIL, recueillir le consentement :
https://www.cnil.fr/fr/les-bases-legales/consentement - CEPD/EDPB,
consentement :
https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en

------------------------------------------------------------------------

## 4. Retrait du consentement et suppression

Le retrait doit être possible sans conséquence négative injustifiée et
être aussi simple que le consentement.

Pour Dindon, cela implique une conséquence technique directe : la
fonction actuelle d'oubli n'est pas encore suffisante si une personne
supprimée peut être recréée lors d'un export Discord ultérieur.

### Modification prioritaire

Créer un registre persistant, par exemple :

-   `privacy_subjects`
-   `discord_user_id`
-   `analysis_opt_in`
-   `consent_version`
-   `consented_at`
-   `withdrawn_at`
-   `deletion_requested_at`
-   `collection_policy`

Puis imposer le contrôle de cette table **avant toute ingestion destinée
au profil personnel ou avant toute analyse**, selon l'architecture de
collecte retenue.

Une personne ayant retiré son consentement ne doit pas réapparaître
automatiquement dans les résultats d'analyse à cause d'un backfill, d'un
rattrapage nocturne ou d'un nouvel événement Gateway.

Il faudra définir séparément ce qui peut être conservé lorsque cela est
nécessaire à d'autres finalités licites (par exemple sécurité ou preuve
du consentement) et ce qui doit être effectivement supprimé ou
anonymisé.

------------------------------------------------------------------------

## 5. AIPD : à traiter comme une priorité

La CNIL indique qu'une analyse d'impact relative à la protection des
données (AIPD/DPIA) doit être réalisée lorsqu'un traitement est
susceptible d'engendrer un risque élevé.

Parmi les critères utilisés figurent notamment :

-   évaluation ou scoring, y compris profilage ;
-   surveillance systématique ;
-   données sensibles ;
-   données concernant des personnes vulnérables, notamment les enfants
    ;
-   traitement à grande échelle ;
-   croisement de données ;
-   usage innovant de technologies.

Dindon peut réunir plusieurs de ces critères simultanément. Avant un
déploiement réel étendu ou commercial, il est donc prudent de traiter
l'AIPD comme un chantier préalable et de faire confirmer formellement
son caractère obligatoire dans le contexte précis du produit.

Une AIPD doit notamment documenter :

1.  le traitement et ses finalités ;
2.  sa nécessité et sa proportionnalité ;
3.  les risques pour les personnes ;
4.  les mesures techniques et organisationnelles destinées à réduire ces
    risques.

Sources : - CNIL, AIPD :
https://www.cnil.fr/fr/ce-quil-faut-savoir-sur-lanalyse-dimpact-relative-la-protection-des-donnees-aipd -
CNIL, définition de l'AIPD :
https://www.cnil.fr/fr/definition/analyse-dimpact-aipd - CNIL, guides
AIPD : https://www.cnil.fr/fr/guides-aipd

------------------------------------------------------------------------

## 6. Mineurs

Le projet indique que des mineurs peuvent être présents sur le serveur.

Cela augmente le niveau de prudence requis : la CNIL inclut les enfants
parmi les personnes vulnérables dans les critères d'évaluation du risque
d'un traitement.

Avant d'inclure des mineurs dans l'analyse politique, il faut donc faire
déterminer précisément le régime applicable et les modalités appropriées
de consentement/information. Une première version réelle de Dindon
gagnerait fortement à **exclure les comptes de mineurs de l'analyse
politique** tant que cette question n'est pas juridiquement cadrée.

------------------------------------------------------------------------

# 7. Feuille de route technique recommandée

## Priorité 0 --- avant l'analyse politique de vraies personnes

### A. Tester le socle contre Discord réel

Le projet n'a pour l'instant été testé qu'avec un faux Discord.

Faire un essai contrôlé sur un serveur administré par le développeur :

1.  petit nombre de salons ;
2.  petit nombre de participants informés ;
3.  collecte et graphe seulement ;
4.  vérifier messages, réponses, mentions et réactions ;
5.  vérifier modifications et suppressions ;
6.  vérifier fils de discussion ;
7.  tester interruptions réseau, reconnexion et limites de débit ;
8.  comparer l'état incrémental à un recalcul complet.

Ne pas commencer par l'analyse politique. Ce premier test doit valider
la couche Discord → ingestion → PostgreSQL → SSE → interface.

### B. Implémenter le bot officiel Discord

Préférer un bot officiel à l'automatisation d'un compte personnel.

Architecture recommandée :

`Discord Gateway → Source Discord → contrat JSON v2 → ingestion existante → PostgreSQL → SSE → interface`

Le bot doit rester un adaptateur mince. Il ne doit pas réimplémenter
l'ingestion.

Événements à prévoir :

-   création de message ;
-   modification ;
-   suppression ;
-   réactions ajoutées/supprimées ;
-   fils de discussion nécessaires au périmètre ;
-   reconnexion et reprise après coupure.

### C. Corriger l'effacement durable

À faire **avant** la phase 5 initialement prévue.

Créer une politique persistante empêchant qu'un utilisateur supprimé
soit recréé involontairement par un export ou un backfill.

Ajouter des tests automatiques :

-   suppression → nouvel export → utilisateur toujours absent de
    l'analyse ;
-   retrait → événement Gateway → aucune nouvelle analyse ;
-   suppression → rattrapage nocturne → aucune résurrection ;
-   modification de version du consentement → comportement attendu.

------------------------------------------------------------------------

## Priorité 1 --- rendre l'IA mesurable avant de lui faire confiance

### A. Construire un corpus d'évaluation

Le jeu actuel de 52 exemples est trop petit pour valider un système de
classification politique.

Créer progressivement un corpus de **200 à 500+ exemples annotés**, avec
une partie annotée indépendamment par au moins deux personnes.

Inclure explicitement :

-   négation ;
-   citations d'une autre personne ;
-   ironie et sarcasme ;
-   questions rhétoriques ;
-   changement d'avis ;
-   opinion rapportée sans adhésion ;
-   messages ambigus ;
-   manque de contexte ;
-   positions nuancées ;
-   messages ne permettant aucune conclusion.

### B. Mesurer chaque étage séparément

Ne pas mesurer seulement le résultat final.

Mesurer :

1.  regroupement en conversations ;
2.  détection des thèmes ;
3.  extraction des affirmations ;
4.  rattachement aux preuves ;
5.  normalisation en propositions ;
6.  stance : pour / contre / nuancé / inconnu ;
7.  relation entre réponses ;
8.  agrégation finale.

Une erreur précoce peut sinon être transformée en score apparemment
précis plusieurs étapes plus tard.

### C. Faire de l'abstention une fonction essentielle

Ajouter explicitement :

-   `unknown`
-   `insufficient_evidence`
-   `ambiguous`
-   `conflicting_evidence`

Le système doit être récompensé lorsqu'il refuse correctement de
conclure.

Pour ce type de produit, **ne pas attribuer une position faute de preuve
est préférable à inventer une position plausible**.

Mesures utiles :

-   précision sur les positions émises ;
-   couverture : proportion de cas sur lesquels le système ose conclure
    ;
-   taux de fausses attributions ;
-   qualité de l'abstention ;
-   accord humain/modèle.

------------------------------------------------------------------------

## Priorité 2 --- provenance et auditabilité

Chaque résultat affiché devrait pouvoir être remonté jusqu'à sa source :

`score → proposition → affirmation extraite → conversation → message(s) Discord`

Conserver avec chaque résultat :

-   identifiants des messages sources ;
-   horodatage ;
-   version du modèle ;
-   version du prompt ;
-   version des règles ;
-   version des axes ;
-   version du modèle d'embeddings ;
-   date de calcul ;
-   niveau de confiance ;
-   statut de validation humaine éventuelle.

Cela permet de reproduire un résultat et de comprendre pourquoi il a
changé.

------------------------------------------------------------------------

## Priorité 3 --- remplacer le « score magique » par de l'incertitude lisible

Éviter qu'un nombre unique donne une impression de certitude excessive.

Une fiche devrait plutôt pouvoir montrer :

-   preuves allant dans un sens ;
-   preuves contradictoires ;
-   éléments ambigus ;
-   quantité de données disponible ;
-   période couverte ;
-   niveau de confiance ;
-   possibilité de consulter les messages justificatifs.

Exemple conceptuel :

**Proposition X** - 3 éléments favorables - 1 contradictoire - 2
ambigus - confiance : modérée - dernière preuve : date - voir les
passages

Le score agrégé peut rester utile en interne, mais l'interface devrait
conserver le chemin vers les éléments concrets.

------------------------------------------------------------------------

## Priorité 4 --- consentement « privacy by design »

Ajouter au modèle de données :

-   état du consentement ;
-   version du texte accepté ;
-   finalités acceptées ;
-   salons concernés ;
-   date d'acceptation ;
-   date de retrait ;
-   état de suppression ;
-   éventuelle pseudonymisation.

Le pipeline d'analyse doit vérifier cette autorisation avant de créer ou
mettre à jour un profil.

Prévoir une interface utilisateur permettant :

-   de voir son état ;
-   de retirer son consentement ;
-   de demander l'effacement ;
-   éventuellement de télécharger ou consulter les informations
    conservées.

------------------------------------------------------------------------

## Priorité 5 --- robustesse opérationnelle

Avant commercialisation :

-   sauvegarde et restauration réellement testées ;
-   migrations testées sur une copie de production ;
-   métriques de santé ;
-   journalisation sans contenu sensible inutile ;
-   stratégie de retry ;
-   file d'erreurs/dead-letter pour analyses échouées ;
-   reprise après crash ;
-   rotation des secrets ;
-   principe du moindre privilège pour le bot ;
-   tests de charge au-delà des 400 personnes déjà mesurées ;
-   ingestion en flux/chunks pour éviter le coût mémoire des gros
    fichiers.

------------------------------------------------------------------------

## Priorité 6 --- Activity Discord

L'interface Svelte/Sigma peut potentiellement évoluer vers une Discord
Activity afin d'afficher la carte directement dans Discord.

Il faut toutefois traiter cette évolution comme un produit distinct de
l'interface purement locale actuelle.

Architecture possible :

`Discord Activity → API authentifiée Dindon → PostgreSQL / services Dindon`

Points à résoudre :

-   authentification de l'utilisateur Discord ;
-   autorisations serveur ;
-   isolation des données par serveur ;
-   exposition réseau du backend ;
-   politique CORS/CSP adaptée ;
-   gestion des sessions ;
-   consentement individuel ;
-   séparation des informations visibles par un administrateur et par un
    membre.

L'Activity ne doit jamais devenir un moyen de rendre visibles à tous des
profils sensibles initialement prévus pour un usage privé.

------------------------------------------------------------------------

# 8. Ordre de développement conseillé

### Étape 1

Bot Discord officiel + test réel **sans IA politique**.

### Étape 2

Effacement durable + registre de consentement + exclusion des personnes
non participantes.

### Étape 3

AIPD et validation juridique du modèle de traitement.

### Étape 4

Corpus d'évaluation et protocole de mesure.

### Étape 5

Thèmes et extraction d'affirmations avec preuves.

### Étape 6

Abstention, contradiction et traçabilité complète.

### Étape 7

Seulement ensuite : agrégation sur les axes et comparaison avec les
rôles.

### Étape 8

Activity Discord et éventuelle commercialisation après validation du
modèle de confidentialité.

------------------------------------------------------------------------

# 9. Ce que je conserverais de l'architecture actuelle

Il n'y a pas de raison évidente de réécrire le socle.

Les choix suivants sont cohérents et méritent d'être conservés :

-   contrat JSON v2 unique ;
-   ingestion idempotente ;
-   identité par ID Discord et non par nom ;
-   gestion des données en retard ;
-   calcul incrémental vérifié contre un recalcul complet ;
-   PostgreSQL comme centre de l'architecture ;
-   séparation entre interactions sociales immédiates et analyse IA
    différée ;
-   preuves obligatoires pour les conclusions ;
-   exécution locale de l'IA lorsque cela est possible ;
-   absence de contenu des messages dans les journaux.

Le principal changement recommandé n'est donc pas une nouvelle
architecture technique. C'est l'ajout d'une **couche de gouvernance des
personnes et des preuves** : consentement, retrait, suppression durable,
provenance, versionnage et incertitude.

------------------------------------------------------------------------

# 10. Conclusion

Dindon possède déjà un socle technique sérieux pour la collecte et la
représentation des interactions Discord.

Le risque principal apparaît au moment où le système passe de :

**« ces personnes interagissent »**

à :

**« cette personne défend telle position politique »**.

Cette seconde affirmation transforme fortement la nature du traitement.
La jurisprudence de la CJUE montre notamment que des informations
sensibles obtenues par déduction ou recoupement peuvent bénéficier de la
protection renforcée de l'article 9 du RGPD.

La trajectoire recommandée est donc :

**valider Discord réel → rendre l'oubli et le consentement robustes →
faire l'AIPD → mesurer l'IA → introduire progressivement l'analyse
politique → envisager ensuite l'Activity et la commercialisation.**

Cette approche permet de conserver presque tout le travail technique
déjà accompli tout en déplaçant les garde-fous de confidentialité et
d'évaluation beaucoup plus tôt dans le projet.
