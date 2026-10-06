# Texte d'information à publier sur le serveur (à adapter)

> À copier dans un salon lu de tous (règlement, #informations) **avant** d'enregistrer. Remplacez les crochets. Ce modèle n'est pas un avis juridique : faites-le relire.

---

**Ce serveur est cartographié par Dindon.**

**Ce qui est fait.** Un robot (« [nom du bot] ») lit les messages écrits dans les salons qu'il peut voir, et les garde sur un ordinateur appartenant à [responsable : nom ou pseudo]. Avec ces messages, Dindon dessine une carte de **qui parle avec qui** (réponses, mentions, réactions) et regroupe les conversations par **sujets**. Un traitement automatique par des programmes qui tournent **sur cet ordinateur** (rien n'est envoyé à un service extérieur) sert à nommer ces sujets.

**Ce qui est gardé.** Le texte des messages, leur date et leur salon, les réactions, les mentions, votre nom et pseudo sur le serveur, vos rôles. [Durée : N jours / jusqu'à ce que vous demandiez l'effacement.]

**Ce qui n'est pas fait.** [Aucune analyse de vos opinions ni de vos positions n'est faite. / adapter si cela change : cela demandera votre accord explicite.] Les données ne sont ni vendues ni partagées. [Qui peut voir la carte : …]

**Vos droits.** À tout moment, sans avoir à vous justifier :
- `/dindon info` : ce texte, dans Discord
- `/dindon mes-donnees` : vous recevez un fichier avec tout ce qui est gardé de vous
- `/dindon stop` : on **arrête de vous enregistrer** (ce qui est déjà gardé reste)
- `/dindon effacer` : on arrête **et on efface** ce qui est gardé de vous (messages, réactions, tout ce qui en est tiré). Définitif, avec une confirmation
- `/dindon reprendre` : vous acceptez de nouveau d'être enregistré·e
- `/dindon debat sujet` : la personne qui le lance choisit les paramètres dans une fenêtre (et, si elle ne sait pas quoi débattre, **un axe** : Dindon pose alors la question de cet axe, et on répond en choisissant l'un des deux camps), puis le débat s'ouvre, **dans un fil (le choix par défaut ; dans le forum des débats du serveur s'il y en a un) ou, si elle le décoche, dans le salon**. Pendant qu'il est ouvert, Dindon **compte vos messages** et **votre position** (pour, ne sait pas, contre), et en publie les chiffres à la fin. **Dans un salon, tout ce qui s'y écrit pendant le débat est compté** (c'est écrit dans le message de lancement) ; dans un fil, seulement ce qui s'y écrit. Le débat se termine quand la personne qui l'a lancé ou un modérateur appuie sur « Terminer le débat », ou tout seul quand personne n'écrit pendant la durée choisie. `/dindon stop` vous en exclut : vos messages n'y sont plus comptés et vous ne pouvez plus y prendre position
- `/dindon card @quelqu'un` : poste dans le salon la carte d'une personne, en 4 pages que des boutons font tourner : **Profil** (activité, habitudes, salons, rôles), **Interactions** (avec qui elle échange, de qui elle est proche ou opposée), **Positions** (ce que l'analyse a lu de ses propos, avec la citation et le lien du message) et **Contradictions** (ce qu'elle dit à l'encontre des rôles qu'elle s'est donnés, ses revirements, avec les preuves). Ce sont des lectures automatiques, pas des verdicts. Les citations montrent un extrait de message : un lien vers un salon privé n'ouvre rien pour qui n'y a pas accès, mais l'extrait, lui, est visible de tout le salon où la carte est postée
- `/dindon map` : poste dans le salon une **image** de la carte du serveur (qui parle avec qui), sur 7, 30 ou 90 jours ou depuis le début, éventuellement centrée sur une personne. Elle est **éteinte tant que les administrateurs ne l'ont pas activée** et ne montre que ce qu'ils ont réglé (nombre de personnes, de noms, types d'échanges) : jamais un message, jamais une personne qui a fait `/dindon stop` ou `/dindon effacer`. Elle est visible de tout le salon
- Si une commande ne fonctionne pas : demandez à [responsable : nom ou pseudo].

Ces réponses ne sont visibles que de vous. Les messages que d'autres personnes ont écrits **à votre sujet** sont les leurs et restent. Les sauvegardes disparaissent d'elles-mêmes sous 14 jours.


Si le bot est retiré du serveur et que le responsable a activé l'effacement automatique, toutes les données du serveur sont supprimées aussitôt.


## Les réponses de Dindon (quand le niveau « répond » est activé sur ce serveur)

Dans un débat dont les affirmations sont vérifiées, quand Dindon est **certain** qu'une affirmation est fausse, il le dit **sous le message**, avec son IA locale, **sans chercher sur Internet et sans source** : **il peut se tromper**, et le message le dit. Dessous, **✅ Valide** et **❌ Invalide** : chacun juge **sa réponse** (pas la personne), un vote chacun, que l'on peut changer. **S'il y a plus d'Invalide que de Valide, Dindon cherche sur Internet** (une phrase neutre, sans nom ni message) et **réécrit sa réponse** avec ce que disent des sources de confiance, même quand c'est « j'avais tort ». S'il y a plus de Valide, ou autant, il en reste là. Vos votes sont gardés (qui a voté quoi sur quelle réponse) ; `/dindon mes-donnees` les montre, `/dindon stop` et `/dindon effacer` les retirent, et les réponses qui portaient sur vos messages sont **supprimées de Discord** par le bot.

## Vérification des affirmations dans les débats (quand elle est activée sur ce serveur)

**Vérification des affirmations (débats).** Pour vérifier ce qu'une personne affirme dans un débat, Dindon envoie à un moteur de recherche une phrase neutre qui décrit l'affirmation — sans votre nom, sans votre message — et lit au plus trois des pages trouvées. Il ne cherche rien d'autre, ne vérifie rien de ce qui concerne une personne privée, n'ouvre pas les liens que vous écrivez, et ne prend pas parti : il dit ce que des sources de confiance établissent, ou qu'il ne peut pas trancher. Rien d'autre ne quitte cet ordinateur, à part ce que Dindon écrit dans les débats de ce serveur. Pour l'instant, il note ses vérifications sans rien publier.

*Si les corrections publiques sont activées sur ce serveur*, la dernière phrase devient : « Quand des sources de confiance contredisent une affirmation, il le dit dans le fil, avec ces sources (sur lesquelles vous pouvez cliquer pour vérifier) ; sinon il ne dit rien. » Sa réponse est la même pour tout le monde : l'affirmation vérifiée, ce que disent les sources avec leurs mots exacts, des liens ; elle ne nomme personne, ne prévient personne et ne donne aucun avis. Elle est **retirée** si le message est modifié ou supprimé, ou si la personne se fait effacer.

À la fin d'un débat, Dindon publie des statistiques (participants, positions, nombre de messages, le message de chacun qui a reçu le plus de réponses et de réactions, et, si la vérification est active, ce qui a été vérifié, sans accuser personne). Elles se recalculent à chaque clic : une personne qui s'est fait effacer ou a demandé l'arrêt n'y figure plus. Ce message de statistiques **reste sur Discord** : seuls les modérateurs du serveur peuvent le supprimer.

Vous pouvez à tout moment voir ce qui a été vérifié de vos messages (`/dindon mes-donnees`), les faire effacer (`/dindon effacer`) ou ne plus participer (`/dindon stop` : vos messages ne sont alors plus lus du tout).
