# Fonctionnement

## Interface

Après connexion, la carte montre les personnes et leurs échanges. Le survol ou le clic met en évidence les liens ; la fiche d'une personne regroupe son activité et, si elles ont été lues, ses positions avec leurs citations. La page **Analyse** rassemble les thèmes, les positions et les contradictions, avec un résumé et trois sections. Les pages **Débats**, **Vie privée** et **Système** donnent accès aux autres résultats et réglages. La recherche de la section active s'ouvre avec `/`. La carte et les fiches se mettent à jour à partir des messages importés et du flux `/events`.

La page **Système** montre la santé des services, les serveurs suivis, les réglages de performance, la lecture automatique et la carte publiée sur Discord. Une confirmation que les personnes sont informées est requise avant d'activer la lecture automatique de positions ou d'exposer rôles et positions dans la carte Discord. Ces confirmations sont des garde-fous de l'interface ; elles ne remplacent pas l'information et le cadre juridique du serveur.

## Analyse locale

L'analyse se lance dans **Analyse → Thèmes** ou par `dindon analyze`. Les étapes par défaut sont `conversations`, `embeddings` et `themes`. La lecture des positions (`claims`) et le placement sur les axes (`axes`) peuvent être demandés séparément avec `--stage` ou dans **Analyse → Positions**. Ollama fournit `bge-m3` pour les vecteurs et `qwen3:14b` par défaut pour les noms et la lecture. Un thème est une proposition que l'administrateur peut valider, renommer, fusionner ou rejeter. Les liens entre propositions et axes sont aussi des propositions à valider ; les scores portent une incertitude et doivent être lus avec les messages cités.

La lecture automatique est désactivée par défaut. Activée dans **Système**, elle exécute les étapes choisies par lots, à une fréquence et dans une plage horaire configurables. Les positions demandent une confirmation supplémentaire que les personnes sont informées. `--rebuild` reconstruit les conversations et ce qui en dépend après un changement important de l'historique.

## Discord et débats

Le bot en direct reçoit les événements du Gateway, met à jour la base et répond aux commandes `/dindon`. `/dindon card` publie une fiche ; `/dindon map` publie une image si la carte Discord est activée. Avec `DISCORD_CLIENT_ID` et `DISCORD_CLIENT_SECRET`, l'Activity affiche la carte dans un salon vocal et contrôle l'appartenance au serveur via Discord.

`/dindon debat` ouvre une fenêtre de configuration : sujet ou axe actif, contexte, fil public ou salon, vérification et fin après une période de silence. Les participants choisissent une position ; l'auteur ou un modérateur peut terminer le débat. Les statistiques finales sont publiées et visibles sur la page **Débats**. Un modérateur peut désigner un forum avec `/dindon forum`. Le détail des modes de vérification et des limites figure dans [Règles du bot](regles-du-bot.md).

## Données des membres

Le bot propose `/dindon info`, `/dindon mes-donnees`, `/dindon stop`, `/dindon effacer` et `/dindon reprendre`. L'interface et la CLI offrent aussi les actions d'accès, d'arrêt et d'effacement. Une personne arrêtée est exclue des nouvelles lectures et des débats. Les anciens fichiers importés sont réécrits lors d'un effacement ; une sauvegarde déjà créée doit être gérée à part. La rétention automatique est désactivée si `DINDON_RETENTION_DAYS=0`.

Les vérifications sur Internet et les publications du bot peuvent faire sortir des informations de la machine. Elles sont conditionnées par la configuration ; voir [Règles du bot](regles-du-bot.md) et [Architecture](architecture.md).
