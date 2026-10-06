# Règles du bot Discord

Le service `bot` utilise un **jeton de bot**, le Gateway Discord et le même stockage que l'application. Activer *Message Content Intent* dans le portail Discord. L'invitation préparée par l'interface ajoute le champ `applications.commands` et les permissions nécessaires ; `dindon preflight` contrôle la configuration en lecture seule. Les commandes sont enregistrées au démarrage du bot. Un compte personnel automatisé contrevient aux conditions de Discord.

Avant de le déployer auprès de vraies personnes, définir la durée de conservation, informer les membres de la collecte et des usages prévus, puis essayer les commandes et l'effacement avec un compte de test. Le code ne recueille pas de consentement préalable et ne vérifie pas l'âge des membres ; l'analyse d'opinions politiques et la présence possible de mineurs demandent un examen juridique propre au serveur. Une confirmation dans l'interface ne suffit pas à elle seule. `dindon preflight` aide à repérer des problèmes techniques ; il ne valide pas ce cadre.

## Commandes des membres

| Commande | Règle |
| --- | --- |
| `/dindon info` | explique collecte, durée et droits |
| `/dindon mes-donnees` | remet en privé les données conservées sur la personne, sous forme JSON si la taille le permet |
| `/dindon stop` | cesse d'enregistrer ses nouveaux messages ; l'existant reste |
| `/dindon effacer` | demande une confirmation, puis cesse l'enregistrement et efface l'existant |
| `/dindon reprendre` | autorise les enregistrements futurs, sans restaurer les données effacées |
| `/dindon card pseudo:@personne` | publie une fiche dans le salon si la personne est enregistrée |
| `/dindon map [periode] [personne]` | publie l'image de la carte si l'administrateur l'a activée |
| `/dindon debat [sujet]` | ouvre une fenêtre de paramètres ; le sujet peut être choisi à partir d'un axe actif |
| `/dindon forum` | montre ou règle le forum des débats ; modification réservée aux modérateurs |

Les actions sur les données personnelles portent seulement sur l'auteur de la commande, identifié par Discord. Leurs réponses sont privées ; `card` et `map` sont volontairement publiques. Une personne ayant choisi `stop` ou `effacer` n'est plus enregistrée ni incluse dans les débats. L'effacement touche aussi les fichiers d'import, mais une ancienne sauvegarde doit être gérée séparément.

## Débats

La fenêtre permet de définir sujet ou axe, contexte, lieu (fil public, forum configuré ou salon), vérification et délai de silence : 1 h, 6 h, 24 h par défaut, 3 j ou 7 j. Le texte du sujet fait 3 à 200 caractères ; le contexte, 1 000 au plus. Une personne ne peut lancer qu'un débat ouvert à la fois ; un serveur, trois. Les positions sont « pour », « ne sait pas », « contre » ou les deux pôles d'un axe avec l'option neutre. La personne qui a lancé le débat ou un modérateur le termine par bouton ; il se termine aussi après le silence choisi. Il n'a pas de durée fixe. Le bot publie les statistiques et reprend après redémarrage les annonces dues.

`/dindon forum` peut choisir un forum et une étiquette. Quand l'option « Ouvrir un fil » est cochée, Dindon y crée un post ; sinon il utilise le salon. Si le forum n'est plus disponible, le code essaie un fil sous le salon d'origine. Dans un débat tenu directement dans un salon, tous les messages de ce salon écrits pendant le débat sont comptés.

## Vérification des affirmations

`DINDON_DEBATE_CHECKS` est `off` par défaut. La case de chaque débat peut désactiver une vérification autorisée, jamais dépasser le niveau choisi par l'administrateur.

| Mode | Comportement |
| --- | --- |
| `off` | aucune affirmation de débat lue par le vérificateur |
| `observe` | lit et vérifie les affirmations sur Internet, enregistre le résultat sans correction publique |
| `answer` | peut répondre d'abord avec le modèle local, sans source ; les participants votent Valide/Invalide. Si Invalide dépasse Valide, une recherche Internet peut compléter sa réponse |
| `live` | ajoute aux réponses les corrections publiques fondées sur des sources de confiance ; le mode retombe à `answer` sans précision mesurée suffisante |

Le mode `live` dépend de `DINDON_DEBATE_PRECISION` et du seuil `DINDON_DEBATE_MIN_PRECISION` (0,90 par défaut). Mesurer avec `python tools/measure_claims.py verify` sur un jeu pertinent avant de renseigner cette valeur ; `dindon preflight` annonce le niveau effectif. Une réponse locale reste explicitement sans source et peut se tromper. Une correction publique exige une citation retrouvée dans une page consultée ; les listes de sources de confiance dans `debate/trust.py` sont à relire par l'administrateur.

La recherche envoie une **phrase neutre**, pas le message Discord entier ni le nom de son auteur, à Google Fact Check Tools ou à un SearXNG configuré. Le vérificateur limite chaque affirmation à deux recherches et trois pages. `answer` peut fonctionner sans service de recherche, mais ne peut alors approfondir un vote défavorable. Les modes avec recherche font donc sortir cette phrase de la machine ; l'activité normale du bot communique aussi avec Discord.

Les interactions réelles avec Discord, la fiabilité du modèle et la pertinence des sources demandent une validation sur le serveur concerné. Les tests du dépôt couvrent le protocole et les règles avec un faux Discord et des données inventées.
