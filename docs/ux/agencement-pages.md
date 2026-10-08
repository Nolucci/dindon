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
| Ensemble | Densité trop élevée à 100 %, texte gris peu lisible, styles de titre et marges divergents | Rendu ordinateur réduit de 20 % à zoom navigateur 100 % ; mobile à taille lisible ; gris plus contrasté ; largeur de lecture et espacement communs ; filtres adaptables ; conservation du clavier et des modales |

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

## Reprise de la densité et des débordements

À la demande de l’utilisateur, la taille de référence sur ordinateur passe à 80 % : textes, espacements, navigation et éléments de la carte diminuent ensemble. La largeur de lecture utilise la même échelle (960 px au lieu de 1 200 px). À 720 px et moins, la typographie conserve sa taille normale, les boutons principaux restent hauts de 44 px et les champs utilisent 16 px pour éviter le zoom de saisie sur téléphone. La carte adapte aussi sa densité lors d’un changement de largeur.

| Zone | Correction supplémentaire |
| --- | --- |
| Thèmes | Grilles sans largeur minimale imposée ; titres et état peuvent changer de ligne ; mots-clés et liens longs restent dans la carte |
| Positions | Propositions et rôles longs reviennent à la ligne ; réglages avancés adaptables ; menu des thèmes alimenté même pendant une recherche rapide |
| Analyse et relecture | Onglets lisibles sur les petits téléphones ; titres des étapes sur plusieurs lignes ; grilles de machines adaptables |
| Fiche personne | Rôles adaptables ; noms sous les axes dans le flux du document pour éviter les superpositions ; pôles longs répartis sur deux colonnes |
| Système | Grilles de cartes, profils de performance et curseurs adaptées à la largeur disponible ; en-têtes repliables sur plusieurs lignes ; valeurs longues dans les encadrés |
| Vie privée | Recherche et action peuvent passer sur deux lignes ; noms et identifiants longs restent dans leur bloc |
| Import et invitation | Noms de salons et de serveurs lisibles sur plusieurs lignes ; titre de fenêtre flexible ; fermeture préservée |
| Exports | Menu déplié dans le flux sur téléphone pour rester dans l’écran |

La validation couvre les pages de consultation et toutes les sections de Système à 320, 390, 720, 1 024 et 1 440 px. Elle contrôle aussi les débordements internes aux composants, y compris avec des noms, mots-clés et URLs très longs. Les tableaux et journaux conservent leur défilement volontaire.

## Débats et analyse : affichage minimal

- Débats : liste latérale persistante sur ordinateur ; fiches de participants à la place du tableau large ; message phare et contexte dépliables ; répartition sans positions vides ; citations et liens de sources conservés. Les explications du message phare et de la nature des sources sont accessibles avec « ? ».
- Analyse : aide courte au niveau du titre de chaque section ; descriptions et mots-clés des thèmes dépliables ; instructions répétées retirées des réglages ; précision sur le traitement accessible à la demande.
- Relecture : marges intérieures ajoutées aux cadres ; filtres alignés et empilés sur les petits téléphones ; compteurs distincts ; colonnes Avant/Après qui passent en lignes sur mobile ; libellés Pour/Contre/Nuancé ; citations et motif dépliables ; annulation de chaque correction conservée. Les aides précisent la préservation des décisions manuelles et des positions incertaines.

Les infobulles s’ouvrent au clic ou au clavier, restent dans l’écran et se ferment avec Échap ou un clic extérieur. Les tableaux de répartition conservent un défilement propre, sans faire défiler tout le cadre. Les corrections locales sont vérifiées sur ordinateur et téléphone, y compris avec des résultats longs et l’annulation d’une correction.

## Débats : suivi et lecture en trois colonnes

Les ordinateurs des débats sont affichés en haut, avec un état actualisé toutes les 5 secondes. Un état trop ancien ou une connexion interrompue ne sont pas présentés comme une activité en cours. Ce suivi concerne les ordinateurs du traitement des débats ; la télémétrie ne rattache pas chaque appel à un débat individuel.

Sur grand écran, la liste reste à gauche, les informations, participants et citations au centre, et le bilan à droite. Le bilan demandé présente les positions, changements d’avis, nombre de messages et verdicts des affirmations examinées. Il est chargé à l’ouverture, puis actualisé toutes les 20 minutes ; son heure de mise à jour est affichée. Le contenu central se renouvelle toutes les 20 secondes sans fermer les profils ouverts.

Chaque participant se déplie : message phare, historique horodaté de ses positions dans le débat, affirmations examinées, puis fiche existante (activité, positions étayées et rôles). La fiche est chargée à la demande dans le serveur du débat.

À largeur intermédiaire, le résumé suit le contenu ; sur téléphone, le détail remplace la liste avec retour explicite et accès direct au résumé. Les pages utilisent désormais la largeur disponible. Les grandes bordures et fonds imbriqués sont retirés ; les contrôles et séparations entre résultats restent repérables.
