# Plan d’agencement UX/UI de Dindon

Audit du site consulté le 8 octobre 2026. Corrections réalisées dans le projet ; validation et déploiement à distinguer. Les parcours de lecture passent avant les commandes de gestion. Les données et les opérations existantes restent accessibles.

| Page | Problèmes observés | Agencement appliqué |
| --- | --- | --- |
| Navigation | Consultation et gestion mélangées ; aucune adresse propre aux pages | Carte, Débats et Analyse en tête ; gestion séparée ; adresses avec fragment et historique du navigateur, y compris sous-sections |
| Carte | Recherche et menus tronqués ; trop de liens ; limites et total confondus ; pied de page technique | Recherche, période, bouton Filtres ; filtres secondaires dépliables ; 800 liens forts par défaut ; limite explicite ; total affiché ; légende taille/couleur ; alertes vers Système |
| Fiche personne | Activité, positions et rôles mélangés ; métriques répétées ; axes sans propos ; graphique sans dates | Onglets Activité, Positions, Rôles ; preuves par sujet ; axes étayés ; légende courte ; premières et dernières dates du graphique |
| Débats | Diagnostics avant la liste ; colonne vide ; répétition d’affirmations ; « vérifiées » ambigu ; tableau de verdicts presque vide | Liste pleine largeur puis détail ; retour explicite sur mobile ; résumé court ; sources avec réponse initiale repliée ; « examinées » ; répartition repliée, seulement les verdicts présents ; diagnostics dans Système |
| Analyse | Étapes techniques en navigation principale ; faux zéros pendant le chargement ; explications du fonctionnement | Onglets Thèmes, Positions, Contradictions en premier ; progression active visible ; suivi technique replié ; chargement explicite |
| Thèmes | Gros blocs de réglages ; cartes longues ; trop d’actions ; mots-clés nombreux | Résultats et recherche en premier ; sélection et validation conservées ; description complète dépliable ; trois mots-clés ; édition secondaire ; analyse et réglages en fin de page |
| Positions | Seulement 250 propositions accessibles ; compteurs contradictoires ; administration avant citations ; action « Lire » trompeuse | Pagination serveur de 50 résultats avec total filtré ; personnes et preuves avant révision ; axes dans une section repliée ; analyse séparée ; bouton « Analyser les conversations restantes » |
| Contradictions | Bouton citations ouvrant une fiche sans preuve ; rôles incompatibles inclus dans le compteur de contradictions ; conclusions trop affirmatives | Citations directement dans la liste ; profil séparé ; filtre distinct pour conflits de rôles ; « À examiner » / « Sans contradiction repérée » ; calcul séparé des preuves |
| Import | Liste de salons trop longue ; filtres par identifiant brut ; action hors écran ; serveur initial incohérent | Serveur courant présélectionné ; liste bornée et défilante ; dates avant filtres facultatifs ; recherche de personnes et ajout d’identifiant ; résumé et action persistants ; journal replié ; ID distingue les salons homonymes |
| Système | Très longue page ; alertes et réglages mélangés ; état vert malgré un ordinateur hors ligne ; consentement rouge même accordé | Sections État, Analyses auto, Discord, Performance, Maintenance ; accès direct depuis automatisation ; état des ordinateurs dans le résumé ; détails performance repliés ; consentement neutre quand accordé ; suppression isolée et confirmation du serveur |
| Vie privée | Longue introduction ; actions incompatibles avec l’état actuel ; informations d’effacement répétées | Recherche puis état de la personne ; arrêt/reprise selon état ; export ; portée de l’effacement dépliable ; registre, conservation et journal préservés |
| Invitation | « N’écrit pas » contredit les permissions ; restriction du bot privé après l’action ; lien brut encombrant | Restriction privée visible avant l’action ; CTA explicite ; permissions exactes dépliables ; collecte expliquée brièvement ; lien et copie conservés |
| Ensemble | Police artificiellement réduite à 80 %, texte gris peu lisible, styles de titre et marges divergents | Police à taille normale ; gris plus contrasté ; surface sobre ; largeur de lecture et espacement communs ; filtres adaptables ; conservation du clavier et des modales |

## Parcours de validation

- Navigation : ouvrir une page, changer de sous-section, revenir avec le navigateur, recharger une adresse.
- Carte : rechercher et ouvrir une personne, changer les filtres, régler la population, consulter les trois onglets.
- Analyse : filtrer les résultats, examiner les preuves, ouvrir la révision et les exports ; aucune analyse ne doit démarrer au clic de consultation.
- Positions : page suivante/précédente, changement de filtre remettant la pagination au début, preuves puis édition des axes.
- Contradictions : nombre de personnes cohérent avec le filtre ; citations visibles sans quitter la page ; conflits de rôles distincts.
- Gestion : onglets Système, filtre de personnes importées, salons nombreux, confirmation des opérations existantes.
- Responsive : 390 px et ordinateur, absence de débordement horizontal, actions et fermeture accessibles, clavier dans les fenêtres.

## Limites

Le filtre d’import par nom trouve les personnes déjà connues du serveur ; un identifiant Discord permet d’ajouter une personne encore inconnue. Les salons homonymes sont distingués par leur identifiant, les catégories Discord n’étant pas fournies par l’API actuelle. Les conclusions de l’analyse restent des éléments à examiner avec leurs citations.

## Vérification locale

La compilation de production est réussie. Les parcours navigateur ont été testés sur les données de la base de test : recherche au clavier, serveurs, filtres, thèmes et leur révision, analyse des positions, citations et axes, débats, réglages, vie privée, invitation et import. La pagination est également vérifiée côté API, avec un total filtré et sans doublons entre les pages.

Les captures à 1440 et 390 px couvrent les pages et les sections de Système ; les essais contrôlent le retour du navigateur, le rechargement d’une adresse, l’ouverture des preuves et l’absence de débordement horizontal. L’import est vérifié avec un service Discord simulé ; aucun import, effacement ou envoi n’a été effectué sur le site de production.

Ces changements sont locaux et ne sont pas encore déployés sur dindon.serveurnf.fr.
