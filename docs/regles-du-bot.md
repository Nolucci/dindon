# Règles du bot Discord

Le service `bot` utilise un **jeton de bot**, le Gateway Discord et le même stockage que l'application. Activer *Message Content Intent* et *Server Members Intent* dans le portail Discord. L'invitation préparée par l'interface ajoute le champ `applications.commands` et les permissions nécessaires ; `dindon preflight` contrôle la configuration en lecture seule. Les commandes sont enregistrées au démarrage du bot. Un compte personnel automatisé contrevient aux conditions de Discord.

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
| `/dindon mycard` | écran privé pour régler sa propre card : le contenu de chaque partie (blocs, positions montrées, petite note), avec les suggestions de Dindon |
| `/dindon politimetre [personne]` | publie une image verticale des positions de l'auteur, ou du membre choisi : tous les axes actifs, avec leur score et leur incertitude lorsqu’ils sont renseignés, sinon « Non renseigné » (la fiche s’allonge selon leur nombre) et trois prises de position sourcées en bas. Suit les blocs et positions épinglées de `mycard`. Nécessite la carte et sa section positions activées, avec confirmation que les membres sont informés. Les prises de position couvrent tout le serveur : votes de débat et positions sourcées, avec les libellés Pour / Nuancé / Contre et, si disponibles, un exemple de chaque camp. Les choix les plus récents remplacent les anciens. Les extraits de messages restent limités au salon de publication ; les boutons donnent accès aux sources dans Discord. |
| `/dindon map [periode] [personne] [forme]` | publie l'image de la carte si l'administrateur l'a activée. Avec une personne : seulement ses propres liens (pas ceux des autres entre eux), ceux avec qui elle échange le plus sont plus gros (jamais plus qu'elle) ; forme au choix : normale, spirale, étoile, carré, cœur, tête de dindon (aussi par un menu sous l'image) |
| `/dindon debat [sujet]` | ouvre les paramètres ; un sujet libre est reformulé avec une description par l’IA, puis confirmé en privé avant toute création ; un axe actif peut aussi être choisi |
| `/dindon terminer [debat]` | clôture le débat de ce fil ou votre débat ouvert ; numéro facultatif ; réservé à son auteur ou à un modérateur |
| `/dindon suivi [debat]` | affiche en privé l’état, les votes et les statistiques ; depuis le fil, le débat est choisi automatiquement ; ailleurs, les débats en cours sont proposés |
| `/dindon param` | montre ou règle le forum des débats et le salon des sondages ; modification réservée aux modérateurs |

Les actions sur les données personnelles portent seulement sur l'auteur de la commande, identifié par Discord. Leurs réponses sont privées ; `card`, `map` et `politimetre` sont volontairement publiques. Une personne ayant choisi `stop` ou `effacer` n'est plus enregistrée ni incluse dans les débats. L'effacement touche aussi les fichiers d'import, mais une ancienne sauvegarde doit être gérée séparément.

## Ma card

Avec `/dindon mycard`, chaque personne règle **sa propre card**, dans un message visible d'elle seule. Les quatre parties (Profil, Interactions, Positions, Contradictions) ne bougent pas ; seul leur contenu change, **dans les limites de ce que l'administrateur a laissé activé** dans le panneau web : quels blocs s'affichent, lesquelles de ses positions lues par Dindon sont montrées (3 au plus, à choisir parmi celles de la base), et une courte note (200 caractères, sans lien) sous une partie ou sous une position. Ces réglages sont ceux que tout le salon voit avec `/dindon card @personne`, notes comprises.

Sous chaque partie, Dindon propose des **suggestions d'amélioration** tirées de ce qu'il a analysé, par règles fixes : une position lue avec peu de certitude ou gardée sans preuve (à préciser par une note), une position plus claire qui n'est pas montrée, un rôle en contradiction avec les propos ou un changement d'avis à expliquer, un bloc masqué alors qu'il y a des données. Chaque suggestion applicable l'est en un clic. Les réglages sont effacés avec `/dindon effacer`, figurent dans `/dindon mes-donnees` et disparaissent avec le serveur.

## Débats

La fenêtre permet de définir sujet ou axe, contexte, lieu (fil public, forum configuré ou salon), vérification et délai de silence : 1 h, 6 h, 24 h par défaut, 3 j ou 7 j. Le texte du sujet fait 3 à 200 caractères ; le contexte, 1 000 au plus. Une personne ne peut lancer qu'un débat ouvert à la fois ; un serveur, trois. Les positions sont « pour », « ne sait pas », « contre » ou les deux pôles d'un axe avec l'option neutre, plus un quatrième bouton **👀 Témoin**. Seules les personnes qui ont pris l'une des trois premières positions **participent** : leurs messages sont lus et comptés dans le débat. Un témoin regarde seulement : il ne peut pas terminer le débat, et ses messages (comme ceux de quelqu'un sans position) sont gardés, marqués « témoin », pour de futures analyses, sans être analysés pour ce débat. Passer de participant à témoin revient à quitter le débat.

**Fin du débat** : aucun bouton de clôture n’est proposé. Son auteur ou un modérateur peut le clôturer avec `/dindon terminer`. Il se termine aussi lorsqu’un camp se vide après que les deux ont existé en même temps, ou après le silence choisi à la création. Il n’a pas de durée fixe. `/dindon suivi` permet de consulter son état et ses votes sans le terminer. Le bot publie les statistiques finales et reprend après redémarrage les annonces dues. Les anciens boutons de fin ouvrent désormais le suivi privé.

`/dindon param` choisit un forum. Dindon attribue aux nouveaux posts les étiquettes disponibles qui correspondent au sujet ou à l'axe (jusqu'à cinq) ; les étiquettes réservées aux modérateurs ne sont pas choisies automatiquement. L'option `etiquette:` sert de secours si aucun thème ne correspond. Si le forum impose une étiquette et qu'aucune n'a été indiquée, il faut une étiquette générale « Politique » ou « Philosophie » non réservée ; elle est utilisée seulement si rien de plus précis ne correspond. Quand l'option « Ouvrir un fil » est cochée, Dindon y crée un post ; sinon il utilise le salon. Si le forum n'est plus disponible, le code essaie un fil sous le salon d'origine. Dans un débat tenu directement dans un salon, tous les messages de ce salon écrits pendant le débat sont comptés.

## Verdict

Quand un débat se termine (et que quelqu'un y a participé), un bouton « ⭐ Noter les participants » apparaît sur le message de fin pendant **24 h**. Toute personne qui a pris une position dans ce débat, **participant ou témoin**, peut noter chaque participant sur 10 (deux décimales, par exemple 7,50), jamais elle-même, et changer sa note jusqu'à la fin de la fenêtre. Ensuite Dindon publie le verdict : la **note finale** de chaque participant vaut **50 % la moyenne des notes reçues** et **50 % l'analyse de Dindon** ; la plus haute gagne (égalité : ex æquo). Si personne n'a noté, l'analyse compte seule, et le verdict le dit.

L'analyse de Dindon est faite de règles fixes sur ce que la base sait déjà, sans jugement d'un modèle sur le fond, et se calcule de la même façon pour tous. Moyenne de trois parties sur 10 : **sources** (affirmations confirmées par une source de confiance vérifiée, rapportées à celui qui en a le plus dans ce débat), **logique** (parmi les affirmations tranchées, la part qui tient : confirmée = 1, en partie vraie = 0,5, contredite = 0), **valeurs** (part des rôles que la personne s'est donnés qui ne sont pas jugés incompatibles avec ses propos). Une partie sans donnée vaut 5. Les chiffres de chaque partie sont affichés dans le verdict.

## Vérification des affirmations

`DINDON_DEBATE_CHECKS` est `off` par défaut. La case de chaque débat peut désactiver une vérification autorisée, jamais dépasser le niveau choisi par l'administrateur.

| Mode | Comportement |
| --- | --- |
| `off` | aucune affirmation de débat lue par le vérificateur |
| `observe` | lit et vérifie les affirmations sur Internet, enregistre le résultat sans correction publique |
| `answer` | le modèle local trie : s'il est sûr que l'affirmation est vraie, rien. Sinon Dindon cherche sur Internet, sources de confiance d'abord, puis ailleurs. **Une source de confiance contredit** (citation retrouvée dans sa page) : message public « Sûr », avec la source. **Aucune source de confiance ne tranche**, mais le modèle est sûr que c'est faux, ou des pages non officielles le suggèrent : message public **⚠️ non fiable** (sa réponse, les pages trouvées, un bouton **🔎 Vérifier**). **Tout le reste** (confirmée, en partie, contestée, avis provisoire « vrai », rien trouvé et modèle pas sûr) : Dindon ne dit rien |
| `live` | identique à `answer` : les corrections par sources de confiance, qui exigeaient une précision mesurée, font maintenant partie de `answer` |

Le bouton **🔎 Vérifier** (un seul clic suffit, il n'y a plus de vote Valide/Invalide sur les nouveaux messages) lance une fois une recherche **plus profonde** : quatre recherches, dont la phrase de l'affirmation, avec plus de résultats par recherche, et douze lectures de pages au plus. Les pages d'autres sources (Wikipédia, presse, blogs) y ont leur propre budget : elles donnent un avis provisoire, avec leurs citations et leurs liens, même si aucune source de confiance ne tranche. Le message est alors réécrit avec ce que Dindon trouve, quel qu'en soit le résultat, y compris que sa réponse était fausse. Les anciens messages gardent leurs boutons Valide/Invalide : plus d'Invalide que de Valide lance toujours la recherche.

`DINDON_DEBATE_PRECISION` et `DINDON_DEBATE_MIN_PRECISION` ne changent plus le comportement ; `tools/measure_claims.py verify` reste le moyen de mesurer la fiabilité du vérificateur sur un jeu pertinent, et `dindon preflight` annonce le niveau effectif. Une réponse « non fiable » est explicitement sans source de confiance et peut se tromper. Un message « Sûr » exige une citation retrouvée mot pour mot dans une page consultée ; les listes de sources de confiance dans `debate/trust.py` sont à relire par l'administrateur.

La recherche envoie une **phrase neutre**, pas le message Discord entier ni le nom de son auteur, à Google Fact Check Tools ou à un SearXNG configuré. Le vérificateur limite chaque affirmation à deux recherches et cinq lectures de pages, dont trois au plus pour des pages qui ont quelque chose à lire (un portail, une page vide ou refusée coûte une lecture mais ne compte pas parmi les trois), et seulement parmi les pages que la recherche a renvoyées ; la vérification demandée par le bouton passe à quatre recherches et douze lectures. `answer` peut fonctionner sans service de recherche : Dindon répond alors depuis le modèle local, marqué non fiable, et dit qu'il ne peut pas chercher. Les modes avec recherche font donc sortir cette phrase de la machine ; l'activité normale du bot communique aussi avec Discord.

**Contexte.** Pour comprendre un message (« oui, exactement », une ironie, une citation, une réponse à une question), le modèle local lit aussi les huit messages qui le précèdent dans le même fil, datant de moins d'une heure, avec le message auquel il répond. Les auteurs y sont anonymes (U1, U2…) : ni nom, ni position, ni camp. Les messages d'une personne qui a demandé à ne plus être enregistrée n'y figurent jamais, et le contexte ne sert qu'à comprendre : une affirmation n'est retenue que si elle se trouve dans le message lui-même et que son auteur l'affirme (pas s'il la cite, s'en moque ou la met en question). Ce contexte reste sur la machine du modèle ; la recherche Internet n'envoie toujours qu'une phrase neutre.

**Avis provisoire.** Quand aucune source de confiance ne tranche, le vérificateur peut lire, dans la limite des mêmes lectures et seulement parmi celles que la recherche a renvoyées, des pages d'autres sources (presse, encyclopédie, blogs). Il en tire au mieux un avis **provisoire** (« probablement vraie / fausse »), avec la citation retrouvée sur la page et le lien. Cet avis est affiché comme provisoire dans l'interface et dans les statistiques ; il ne fonde **jamais** un message « Sûr » ni une note du verdict. Quand il va dans le sens « faux », Dindon peut le publier, marqué **non fiable** (voir `answer`). Deux sources qui se contredisent, ou une citation introuvable, ne donnent aucun avis. Les participants peuvent le contester et le corriger.

Les interactions réelles avec Discord, la fiabilité du modèle et la pertinence des sources demandent une validation sur le serveur concerné. Les tests du dépôt couvrent le protocole et les règles avec un faux Discord et des données inventées.

### Sondages et axes des cartes

`/dindon param forum:#débats sondages:#sondages` choisit les deux destinations. Chaque nouveau débat publie dans le salon choisi un sondage avec une question courte, des précisions sur les termes si nécessaire et un lien vers le débat. Les trois boutons sont **Pour**, **Ne sait pas**, **Contre**. Le modèle local prépare la question et les précisions ; s'il ne répond pas, le sujet et le contexte fournis sont utilisés. Pour une question d'axe, Pour correspond au premier pôle indiqué dans la question, Contre au second.

Les boutons du débat et du sondage enregistrent la même position : une réponse modifiée remplace la précédente dans le calcul. Les réponses Pour et Contre alimentent les axes de la partie Informations des cartes ; Ne sait pas et Témoin ne donnent aucune direction. Les réponses aux questions d'axes ont un lien explicite ; celles aux sujets libres sont reliées aux axes par l'analyse des propositions. Les messages du débat restent analysés par le parcours habituel des conversations. Les scores conservent leur marge d'incertitude.

Le sondage se ferme avec le débat. Sa destination, son message et les mises à jour à publier sont conservés pour reprendre après un redémarrage ou un échec de publication. Les réponses suivent les règles d'opposition à l'enregistrement et d'effacement des données des débats.

Les sondages liés aux nouveaux débats sont des sondages Discord à choix unique (Pour / Ne sait pas / Contre), ouverts pendant 32 jours au maximum et arrêtés dès la clôture du débat. Leurs votes alimentent les positions du débat ; un changement de camp dans le débat ne change pas le vote affiché par Discord. Les votes manqués pendant une déconnexion sont récupérés au retour du bot. Les anciens messages à boutons des débats encore ouverts sont remplacés, en conservant les positions enregistrées.

Une personne qui rejoint un fil de débat reçoit une mention dans ce fil avec les trois choix de camp, une seule fois par débat. Si elle a déjà choisi, aucune invitation n'est envoyée. Sans événement d'arrivée, son premier message déclenche aussi cette invitation. Activer **Server Members Intent** dans le portail Discord et autoriser **Envoyer des sondages** dans le salon des sondages.
