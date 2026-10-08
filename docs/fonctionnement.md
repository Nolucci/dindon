# Fonctionnement

## Interface

Après connexion, la carte montre les personnes et leurs échanges. Le survol ou le clic met en évidence les liens ; la fiche d'une personne regroupe son activité et, si elles ont été lues, ses positions avec leurs citations. La page **Analyse** affiche les quatre étapes, la phase active et sa progression chiffrée lorsqu’elle est connue, puis les thèmes, positions et contradictions dans trois sections. Les pages **Débats**, **Vie privée** et **Système** donnent accès aux autres résultats et réglages. La recherche de la section active s'ouvre avec `/`. La carte et les fiches se mettent à jour à partir des messages importés et du flux `/events`.

La page **Système** montre la santé des services, les serveurs suivis, les réglages de performance, la lecture automatique et la carte publiée sur Discord. Une confirmation que les personnes sont informées est requise avant d'activer la lecture automatique de positions ou d'exposer rôles et positions dans la carte Discord. Ces confirmations sont des garde-fous de l'interface ; elles ne remplacent pas l'information et le cadre juridique du serveur.

## Analyse locale

L'analyse se lance dans **Analyse → Thèmes** ou par `dindon analyze`. Les étapes par défaut sont `conversations`, `embeddings` et `themes`. La lecture des positions (`claims`) et le placement sur les axes (`axes`) peuvent être demandés séparément avec `--stage` ou dans **Analyse → Positions**. Ollama fournit `bge-m3` pour les vecteurs et `qwen3:14b` par défaut pour les noms et la lecture. Un thème est une proposition que l'administrateur peut valider, renommer, fusionner ou rejeter. Les liens entre propositions et axes sont aussi des propositions à valider ; les scores portent une incertitude et doivent être lus avec les messages cités.

Le parcours se lit comme **compacteur → partitionneur → classeur → juge**. Le compacteur conserve les messages bruts, mais retire du texte analysé les marqueurs automatiques de comptes suspendus et les répétitions exactes. Le partitionneur regroupe les conversations proches et peut laisser sans thème celles qui ne ressemblent assez à aucun groupe. Un thème est un sujet, pas une proposition à laquelle on peut être pour ou contre : le classeur relève des propositions précises à l'intérieur des thèmes, puis vérifie que les citations montrent bien la position attribuée. Le juge compare les positions aux rôles d'idées du serveur avec l'incertitude des scores ; « pas assez de propos » reste une absence de conclusion. Les propositions et les liens aux axes proposés par l'IA demandent une relecture humaine.

Après une mise à jour du compacteur ou du partitionneur, `dindon analyze --rebuild` permet de refaire les conversations et leurs résultats dérivés. Cette opération efface les résultats automatiques dépendant des anciennes conversations : examiner les thèmes déjà validés et les relectures humaines avant de la lancer.

La lecture automatique est désactivée par défaut. Activée dans **Système**, elle exécute les étapes choisies par lots, à une fréquence et dans une plage horaire configurables. Les positions demandent une confirmation supplémentaire que les personnes sont informées. `--rebuild` reconstruit les conversations et ce qui en dépend après un changement important de l'historique.

Les vecteurs et les positions sont traités par lots. Un seul appel au modèle tourne à la fois pour préserver la marge du serveur. Le réglage initial **Équilibré** limite les appels IA à 60 % du temps ; il reste modifiable dans **Système → Performance**. Les affectations des conversations aux thèmes sont écrites en base par lots.

## Discord et débats

Le bot en direct reçoit les événements du Gateway, met à jour la base et répond aux commandes `/dindon`. `/dindon card` publie une fiche ; `/dindon map` publie une image si la carte Discord est activée. Avec `DISCORD_CLIENT_ID` et `DISCORD_CLIENT_SECRET`, l'Activity affiche la carte dans un salon vocal et contrôle l'appartenance au serveur via Discord.

`/dindon debat` ouvre une fenêtre de configuration : sujet ou axe actif, contexte, fil public ou salon, vérification et fin après une période de silence. Si un sujet est saisi, l’IA propose une question et une description à confirmer avant la création. Les participants choisissent une position ; `/dindon suivi` affiche l’état et les votes. Son auteur ou un modérateur peut le clôturer avec `/dindon terminer`. Il se termine aussi automatiquement après le silence choisi ou lorsqu’un camp se vide. Les statistiques finales sont publiées et visibles sur la page **Débats**. Un modérateur choisit le forum des débats et le salon des sondages avec `/dindon param forum:#débats sondages:#sondages`. Les sondages renvoient vers les débats ; les positions prises dans les deux lieux alimentent les axes des cartes. Le détail des modes de vérification et des limites figure dans [Règles du bot](regles-du-bot.md).

## Données des membres

Le bot propose `/dindon info`, `/dindon mes-donnees`, `/dindon stop`, `/dindon effacer` et `/dindon reprendre`. L'interface et la CLI offrent aussi les actions d'accès, d'arrêt et d'effacement. Une personne arrêtée est exclue des nouvelles lectures et des débats. Les anciens fichiers importés sont réécrits lors d'un effacement ; une sauvegarde déjà créée doit être gérée à part. La rétention automatique est désactivée si `DINDON_RETENTION_DAYS=0`.

Les vérifications sur Internet et les publications du bot peuvent faire sortir des informations de la machine. Elles sont conditionnées par la configuration ; voir [Règles du bot](regles-du-bot.md) et [Architecture](architecture.md). Si un administrateur ajoute un [ordinateur d'analyse](ordinateurs-analyse.md), le texte à calculer lui est transmis sur le réseau privé.
