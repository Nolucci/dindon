# Axes et idéologies à relire

Cette page est **générée à partir de la base** (`generate_axes_review.py`) : elle dit exactement ce que contient `seed-axes.sql`. Pour changer quelque chose, modifiez `seed-axes.sql` (ou la base), puis relancez le générateur.

## Comment lire

- Chaque axe va de **−1 à +1**. −1 est le pôle de gauche du modèle [12 Axes](https://12axes.vercel.app), +1 son pôle de droite. Les pôles ne sont pas des jugements de valeur.
- Pour chaque axe : la question qu'il pose, ce qu'il couvre, **ce qu'il ne couvre pas** (pour qu'un sujet n'appartienne qu'à un seul axe), et ce que veulent dire −1, 0 et +1.
- Les **12 axes du modèle 12 Axes** (leurs noms et leurs pôles) et les **9 axes ajoutés** sont tous **actifs** (décision du 4 octobre 2026 : mesuré sur 55 phrases, le modèle range bien moins de phrases sur un mauvais axe quand il voit l'Europe, l'écologie, le genre, la redistribution, les animaux : voir [VALIDATION-AXES.md](VALIDATION-AXES.md)). Un axe inactif n'est ni proposé à l'IA ni calculé.
- Pour éteindre un axe : `UPDATE axes SET is_active = false WHERE code = 'europe';`

## Les axes en un coup d'œil

| N° | Axe | −1 | +1 | Origine | État |
| ---: | --- | --- | --- | --- | --- |
| 1 | **Structure de l'État** (`structure`) | Fédéral | Unitaire | 12 Axes | actif |
| 2 | **Représentation et régime** (`representation`) | Démocratie | Autocratie | 12 Axes | actif |
| 3 | **Pouvoir de l'État sur l'individu** (`pouvoir`) | Sécurité | Liberté | 12 Axes | actif |
| 4 | **Immigration et identité** (`immigration`) | Assimilation | Multiculturalisme | 12 Axes | actif |
| 5 | **Armée et diplomatie** (`diplomatie`) | Militariste | Pacifiste | 12 Axes | actif |
| 6 | **Intervention et souveraineté** (`intervention`) | Non-interventionniste | Nationaliste | 12 Axes | actif |
| 7 | **Propriété des moyens de production** (`economie`) | Public | Privé | 12 Axes | actif |
| 8 | **Contrôle de l'économie** (`controle`) | Planification | Libre marché | 12 Axes | actif |
| 9 | **Commerce international** (`commerce`) | Protectionnisme | Globalisme | 12 Axes | actif |
| 10 | **Religion et État** (`religion`) | Irréligieux | Religieux | 12 Axes | actif |
| 11 | **Morale et mœurs** (`morale`) | Progressiste | Traditionaliste | 12 Axes | actif |
| 12 | **Technologie et nature** (`technologie`) | Technologie | Biologie | 12 Axes | actif |
| 13 | **Souveraineté et Europe** (`europe`) | Souveraineté nationale | Intégration européenne | ajouté | actif |
| 14 | **Écologie** (`ecologie`) | Productivisme | Écologie | ajouté | actif |
| 15 | **Méthode de changement** (`rupture`) | Réforme | Rupture | ajouté | actif |
| 16 | **Protection sociale et fiscalité** (`redistribution`) | Redistribution | Mérite individuel | ajouté | actif |
| 17 | **Confiance dans les institutions et les experts** (`confiance`) | Confiance | Défiance | ajouté | actif |
| 18 | **Genre et égalité des sexes** (`genre`) | Égalité des genres | Rôles traditionnels | ajouté | actif |
| 19 | **Condition animale** (`animaux`) | Droits des animaux | Usage humain des animaux | ajouté | actif |
| 20 | **Alliances et blocs** (`alliances`) | Non-alignement | Atlantisme | ajouté | actif |
| 21 | **Démocratie directe ou représentative** (`participation`) | Démocratie directe | Démocratie représentative | ajouté | actif |

## Les 12 axes du modèle 12 Axes

### 1. Structure de l'État (`structure`)

**Question :** Le pouvoir doit-il être réparti entre les régions et les collectivités, ou concentré dans un État unitaire ?

**Pôles :** −1 = Fédéral, +1 = Unitaire

**Ce que l'axe couvre :** Répartition du pouvoir entre l'État central, les régions, les communes et les communautés locales ; uniformité des lois et du commandement.

**Ce qu'il ne couvre pas :** Le régime politique (axe representation) et l'Union européenne (axe europe).

**Repères :**

- **−1,0** (Fédéral) : Le pouvoir appartient surtout aux régions et aux communautés locales, qui font leurs propres lois ; l'État central a un rôle minimal.
- **0** (au milieu) : Un État décentralisé : les compétences sont partagées entre l'État et les collectivités.
- **+1,0** (Unitaire) : Un État unitaire fort : les mêmes lois et un commandement unique pour tout le territoire.

### 2. Représentation et régime (`representation`)

**Question :** Le pouvoir doit-il venir d'élections libres et d'une opposition, ou d'un chef, d'un parti ou d'experts ?

**Pôles :** −1 = Démocratie, +1 = Autocratie

**Ce que l'axe couvre :** Confiance dans les élections, l'opposition et les institutions démocratiques, face à la préférence pour un dirigeant fort, la technocratie, la monarchie ou un régime autoritaire.

**Ce qu'il ne couvre pas :** Les libertés individuelles et la sécurité (axe pouvoir).

**Repères :**

- **−1,0** (Démocratie) : Le pouvoir vient d'élections libres et pluralistes, avec une opposition et des contre-pouvoirs, voire de la démocratie directe.
- **0** (au milieu) : Une démocratie qui laisse une grande place à un exécutif fort ou à des experts.
- **+1,0** (Autocratie) : Le pouvoir est concentré dans un chef, un parti, un monarque ou des experts, sans opposition réelle.

### 3. Pouvoir de l'État sur l'individu (`pouvoir`)

**Question :** Faut-il privilégier l'ordre et la sécurité, ou la liberté individuelle ?

**Pôles :** −1 = Sécurité, +1 = Liberté

**Ce que l'axe couvre :** Équilibre entre ordre, surveillance, punition et contrôle de l'État, d'un côté, et vie privée, liberté individuelle et autonomie civile, de l'autre.

**Ce qu'il ne couvre pas :** Le régime politique (axe representation) et les mœurs (axe morale).

**Repères :**

- **−1,0** (Sécurité) : L'ordre et la sécurité passent avant tout : une surveillance et des sanctions fortes sont acceptables.
- **0** (au milieu) : Un équilibre entre sécurité et libertés, au cas par cas.
- **+1,0** (Liberté) : La liberté individuelle passe avant tout : peu de surveillance, peu de punition, une grande autonomie.

### 4. Immigration et identité (`immigration`)

**Question :** Faut-il exiger l'assimilation à l'identité nationale, ou valoriser le multiculturalisme ?

**Pôles :** −1 = Assimilation, +1 = Multiculturalisme

**Ce que l'axe couvre :** Assimilation culturelle, langue et identité nationale, face au multiculturalisme, à l'ouverture migratoire et à la pluralité des coutumes.

**Ce qu'il ne couvre pas :** La religion dans la vie publique (axe religion) et les mœurs (axe morale).

**Repères :**

- **−1,0** (Assimilation) : Les nouveaux arrivants doivent s'assimiler pleinement à la langue, à la culture et à l'identité nationales.
- **0** (au milieu) : L'intégration est attendue, tout en respectant certaines différences.
- **+1,0** (Multiculturalisme) : La diversité des cultures est une richesse : le multiculturalisme et l'ouverture migratoire sont à encourager.

### 5. Armée et diplomatie (`diplomatie`)

**Question :** Faut-il miser sur la force militaire ou sur la négociation ?

**Pôles :** −1 = Militariste, +1 = Pacifiste

**Ce que l'axe couvre :** Forces armées, armement, dissuasion et intervention militaire, face à la négociation, au pacifisme et aux organismes internationaux.

**Ce qu'il ne couvre pas :** La place du pays dans le monde en général (axe intervention).

**Repères :**

- **−1,0** (Militariste) : Une armée forte et la dissuasion sont la meilleure garantie de la paix ; le recours à la force est légitime.
- **0** (au milieu) : Une défense solide, avec une préférence pour la négociation.
- **+1,0** (Pacifiste) : Le pacifisme prime : désarmement, négociation et organismes internationaux plutôt que la force.

### 6. Intervention et souveraineté (`intervention`)

**Question :** Faut-il rester en retrait du monde ou défendre activement les intérêts nationaux ?

**Pôles :** −1 = Non-interventionniste, +1 = Nationaliste

**Ce que l'axe couvre :** Entre le non-interventionnisme extérieur et une souveraineté nationale plus affirmée : nationalisme géopolitique et défense active des intérêts nationaux.

**Ce qu'il ne couvre pas :** L'emploi de la force militaire en soi (axe diplomatie) et le commerce (axe commerce).

**Repères :**

- **−1,0** (Non-interventionniste) : Le pays doit rester en dehors des affaires du monde et n'intervenir nulle part à l'étranger.
- **0** (au milieu) : Une action extérieure limitée, pour des raisons précises.
- **+1,0** (Nationaliste) : La souveraineté doit être affirmée : défendre activement les intérêts nationaux, y compris par la puissance.

### 7. Propriété des moyens de production (`economie`)

**Question :** Les entreprises et les services essentiels doivent-ils être publics ou privés ?

**Pôles :** −1 = Public, +1 = Privé

**Ce que l'axe couvre :** Préférence pour la propriété publique, les entreprises d'État et les services collectifs, face à la propriété privée, aux privatisations et au rôle des entreprises.

**Ce qu'il ne couvre pas :** La façon dont l'économie est dirigée (axe controle).

**Repères :**

- **−1,0** (Public) : Les moyens de production et les services essentiels appartiennent à la collectivité : entreprises publiques, propriété collective.
- **0** (au milieu) : Une économie mixte, avec un secteur public et un secteur privé.
- **+1,0** (Privé) : La propriété privée et les entreprises sont le moteur de l'économie : il faut privatiser l'essentiel.

### 8. Contrôle de l'économie (`controle`)

**Question :** L'économie doit-elle être planifiée et régulée, ou laissée au libre marché ?

**Pôles :** −1 = Planification, +1 = Libre marché

**Ce que l'axe couvre :** Planification d'État, régulation et politique économique active, face au libre marché, à la faible intervention, à l'autonomie monétaire et à la concurrence.

**Ce qu'il ne couvre pas :** La propriété des entreprises (axe economie) et le commerce international (axe commerce).

**Repères :**

- **−1,0** (Planification) : L'État planifie l'économie et oriente fortement la production, les prix et l'investissement.
- **0** (au milieu) : Un marché régulé par l'État.
- **+1,0** (Libre marché) : Un marché libre, avec une intervention minimale de l'État, de la concurrence et une monnaie autonome.

### 9. Commerce international (`commerce`)

**Question :** Faut-il protéger l'industrie nationale ou ouvrir l'économie au commerce mondial ?

**Pôles :** −1 = Protectionnisme, +1 = Globalisme

**Ce que l'axe couvre :** Protectionnisme, souveraineté productive et défense de l'industrie nationale, face au libre-échange et à l'intégration économique internationale.

**Ce qu'il ne couvre pas :** L'Union européenne en tant que telle (axe europe).

**Repères :**

- **−1,0** (Protectionnisme) : Protéger l'industrie nationale par des droits de douane et viser la souveraineté productive.
- **0** (au milieu) : Des échanges ouverts, avec des protections ciblées.
- **+1,0** (Globalisme) : Le libre-échange et l'intégration économique internationale, sans barrières.

### 10. Religion et État (`religion`)

**Question :** La religion doit-elle rester hors de la vie publique, ou y avoir une influence ?

**Pôles :** −1 = Irréligieux, +1 = Religieux

**Ce que l'axe couvre :** Laïcité, séparation de la religion et de l'État et critique des privilèges religieux, face à l'influence publique de la foi et des valeurs religieuses.

**Ce qu'il ne couvre pas :** L'immigration (axe immigration) et les mœurs (axe morale).

**Repères :**

- **−1,0** (Irréligieux) : Séparation stricte de la religion et de l'État, aucun privilège religieux, et critique de la religion dans l'espace public.
- **0** (au milieu) : Une laïcité qui respecte les pratiques religieuses.
- **+1,0** (Religieux) : La foi et les valeurs religieuses doivent avoir une influence publique : lois, institutions, éducation.

### 11. Morale et mœurs (`morale`)

**Question :** Faut-il faire évoluer les normes sociales ou préserver la tradition ?

**Pôles :** −1 = Progressiste, +1 = Traditionaliste

**Ce que l'axe couvre :** Progressisme culturel, droits civils et changements sociaux, face à la tradition, à la famille, aux coutumes et au conservatisme moral.

**Ce qu'il ne couvre pas :** La religion dans la vie publique (axe religion), l'immigration (axe immigration) et le genre (axe genre).

**Repères :**

- **−1,0** (Progressiste) : Le progrès culturel et l'extension des droits civils sont à encourager, sans frein de la tradition.
- **0** (au milieu) : Les évolutions sont acceptées au cas par cas, avec prudence.
- **+1,0** (Traditionaliste) : La tradition, la famille et les coutumes doivent être préservées ; les évolutions de mœurs sont à freiner.

### 12. Technologie et nature (`technologie`)

**Question :** Faut-il accélérer le développement technique ou faire preuve de prudence envers le vivant et l'environnement ?

**Pôles :** −1 = Technologie, +1 = Biologie

**Ce que l'axe couvre :** Enthousiasme pour la technologie, l'IA, le génie génétique et le développement technique, face à la prudence biologique, environnementale et préservationniste.

**Ce qu'il ne couvre pas :** Le rôle de l'État dans l'économie (axes economie et controle).

**Repères :**

- **−1,0** (Technologie) : Le développement technique, l'IA et le génie génétique sont à accélérer, avec peu de limites.
- **0** (au milieu) : Du progrès technique, encadré.
- **+1,0** (Biologie) : La prudence biologique et environnementale prime : préserver le vivant et limiter les technologies.

## Les axes ajoutés

Les trois premiers (Europe, écologie, rupture) couvrent ce que les 12 axes ne couvrent pas et que vos rôles de serveur expriment. Les six suivants portent sur des sujets importants du débat politique français.

### 13. Souveraineté et Europe (`europe`)

**Question :** Faut-il plus de pouvoir national ou plus d'intégration européenne ?

**Pôles :** −1 = Souveraineté nationale, +1 = Intégration européenne

**Ce que l'axe couvre :** Place de l'Union européenne, de l'euro et des traités par rapport aux décisions nationales.

**Ce qu'il ne couvre pas :** Le commerce mondial en général (axe commerce) et la structure interne de l'État (axe structure).

**Repères :**

- **−1,0** (Souveraineté nationale) : La France doit retrouver la maîtrise de ses lois et de sa monnaie, quitte à quitter l'Union européenne.
- **0** (au milieu) : L'Union est utile, mais ses pouvoirs doivent rester limités.
- **+1,0** (Intégration européenne) : L'Europe doit devenir une fédération, avec un gouvernement commun.

### 14. Écologie (`ecologie`)

**Question :** Faut-il subordonner l'économie à l'environnement ?

**Pôles :** −1 = Productivisme, +1 = Écologie

**Ce que l'axe couvre :** Climat, énergie, biodiversité, sobriété, croissance, contraintes environnementales, condition animale.

**Ce qu'il ne couvre pas :** La prudence envers la technologie (axe technologie), le rôle de l'État (axes economie et controle) et la condition animale (axe animaux).

**Repères :**

- **−1,0** (Productivisme) : La croissance et l'industrie passent avant ; les contraintes environnementales sont excessives.
- **0** (au milieu) : Une transition progressive, compatible avec la croissance.
- **+1,0** (Écologie) : L'environnement prime : sobriété, voire décroissance, et fortes contraintes sont nécessaires.

### 15. Méthode de changement (`rupture`)

**Question :** Faut-il changer la société par la réforme ou par la rupture ?

**Pôles :** −1 = Réforme, +1 = Rupture

**Ce que l'axe couvre :** La façon de changer les choses, quelle que soit la direction : compromis et réformes graduelles, ou changement radical du système.

**Ce qu'il ne couvre pas :** La direction du changement (tous les autres axes).

**Repères :**

- **−1,0** (Réforme) : Seules des réformes graduelles et consensuelles sont légitimes ; la rupture est dangereuse.
- **0** (au milieu) : Des réformes profondes, mais dans le cadre existant.
- **+1,0** (Rupture) : Le système actuel doit être renversé ou refondé ; les réformes ne suffisent pas.

### 16. Protection sociale et fiscalité (`redistribution`)

**Question :** Faut-il réduire les inégalités par l'impôt et la protection sociale, ou laisser chacun responsable de ses revenus ?

**Pôles :** −1 = Redistribution, +1 = Mérite individuel

**Ce que l'axe couvre :** Impôts, prestations sociales, retraites, assurance chômage, droit du travail et lutte contre les inégalités, face à la responsabilité individuelle, à la baisse des prélèvements et à la flexibilité.

**Ce qu'il ne couvre pas :** La propriété des entreprises (axe economie) et la planification (axe controle).

**Repères :**

- **−1,0** (Redistribution) : Les inégalités doivent être fortement réduites par l'impôt, des prestations généreuses et une forte protection des travailleurs.
- **0** (au milieu) : Une protection sociale solide mais financée avec mesure, entre solidarité et responsabilité.
- **+1,0** (Mérite individuel) : Chacun est responsable de sa situation : impôts et prestations réduits au minimum, marché du travail flexible.

### 17. Confiance dans les institutions et les experts (`confiance`)

**Question :** Faut-il faire confiance aux institutions, aux experts et aux médias établis, ou s'en défier ?

**Pôles :** −1 = Confiance, +1 = Défiance

**Ce que l'axe couvre :** Confiance dans les institutions, la science, les experts, la justice et les grands médias, face à la défiance envers les élites et les versions officielles.

**Ce qu'il ne couvre pas :** Le régime politique (axe representation) et les opinions sur un sujet précis (qui relèvent des autres axes).

**Repères :**

- **−1,0** (Confiance) : Les institutions, les experts et la science sont globalement fiables, et leurs conclusions doivent guider l'action.
- **0** (au milieu) : Une confiance prudente : vérifier et critiquer, sans rejeter en bloc.
- **+1,0** (Défiance) : Les élites, les médias et les versions officielles sont suspects : il faut s'en défier par principe.

### 18. Genre et égalité des sexes (`genre`)

**Question :** Faut-il aller vers plus d'égalité et de fluidité des genres, ou maintenir des rôles et des identités traditionnels ?

**Pôles :** −1 = Égalité des genres, +1 = Rôles traditionnels

**Ce que l'axe couvre :** Égalité entre les sexes, féminisme, identités de genre, droits des personnes LGBT, face aux rôles et aux différences traditionnels entre hommes et femmes.

**Ce qu'il ne couvre pas :** La famille et les mœurs en général (axe morale).

**Repères :**

- **−1,0** (Égalité des genres) : L'égalité réelle entre les sexes et la reconnaissance de toutes les identités de genre sont des priorités, avec des mesures actives.
- **0** (au milieu) : L'égalité des droits est acquise ; les évolutions se font avec prudence.
- **+1,0** (Rôles traditionnels) : Les rôles et les différences traditionnels entre hommes et femmes doivent être préservés.

### 19. Condition animale (`animaux`)

**Question :** Faut-il reconnaître des droits aux animaux ou conserver leur usage par l'humain ?

**Pôles :** −1 = Droits des animaux, +1 = Usage humain des animaux

**Ce que l'axe couvre :** Élevage, chasse, corrida, expérimentation animale, alimentation carnée, statut juridique de l'animal.

**Ce qu'il ne couvre pas :** Les politiques environnementales en général (axe ecologie).

**Repères :**

- **−1,0** (Droits des animaux) : Les animaux ont des droits : il faut abolir l'élevage intensif, la chasse et la corrida.
- **0** (au milieu) : Le bien-être animal doit être amélioré, tout en maintenant les usages.
- **+1,0** (Usage humain des animaux) : L'usage des animaux (élevage, chasse, traditions) est légitime et ne doit pas être restreint.

### 20. Alliances et blocs (`alliances`)

**Question :** Faut-il rester arrimé au bloc occidental ou rester non-aligné ?

**Pôles :** −1 = Non-alignement, +1 = Atlantisme

**Ce que l'axe couvre :** OTAN, alliance avec les États-Unis, appartenance au bloc occidental, rapport à la Russie et à la Chine, face à l'indépendance et au non-alignement.

**Ce qu'il ne couvre pas :** L'usage de la force en soi (axe diplomatie) et l'ouverture aux échanges (axe commerce).

**Repères :**

- **−1,0** (Non-alignement) : La France doit sortir de l'OTAN et ne s'aligner sur aucun bloc.
- **0** (au milieu) : Des alliances utiles, en gardant une autonomie de décision.
- **+1,0** (Atlantisme) : La France doit rester pleinement dans l'alliance occidentale et suivre sa ligne.

### 21. Démocratie directe ou représentative (`participation`)

**Question :** Les citoyens doivent-ils décider directement, ou par l'intermédiaire d'élus ?

**Pôles :** −1 = Démocratie directe, +1 = Démocratie représentative

**Ce que l'axe couvre :** Référendum d'initiative citoyenne, tirage au sort, assemblées citoyennes et consultation permanente, face à la délégation du pouvoir à des élus et à un exécutif stable.

**Ce qu'il ne couvre pas :** Le fait d'être démocratique ou non (axe representation).

**Repères :**

- **−1,0** (Démocratie directe) : Les citoyens doivent pouvoir proposer, voter et révoquer directement (RIC, tirage au sort) ; les élus ne sont que des exécutants.
- **0** (au milieu) : Des élus qui décident, avec des référendums et des consultations pour les grandes questions.
- **+1,0** (Démocratie représentative) : Les élus décident : le pouvoir est délégué à des représentants et à un exécutif stable, sans référendum permanent.

## Les idéologies

Une idéologie est un nom, plus **ce qu'elle implique sur les axes** : la plage où quelqu'un qui s'en réclame doit se trouver. Les plages sont **larges exprès** : un écart n'est signalé que s'il est net. **Toutes sont des propositions non validées** (`is_validated = false`) tant que vous ne les avez pas relues. Une plage sur un axe inactif ne compte qu'une fois l'axe activé (elle est marquée « axe inactif »).

Trois sortes : une **famille politique** contraint plusieurs axes, une **position** porte sur un ou deux axes, une **valeur ou attitude** n'implique presque rien.

### Familles politiques

| Idéologie | Spectre | Ce qu'elle implique | Description |
| --- | --- | --- | --- |
| **Centre-Gauche** (`centre_gauche`) | centre | Propriété des moyens de production : de −0,6 à +0,3 (plage large)<br>Contrôle de l'économie : de −0,7 à +0,4 (plage large)<br>Morale et mœurs : de −1,0 à +0,4 (plage large)<br>Méthode de changement : de −1,0 à +0,1 (plage large)<br>Protection sociale et fiscalité : de −0,8 à +0,2 (plage large) | Progressisme social et économie mixte, par la réforme. |
| **Communiste** (`communiste`) | extrême gauche | Propriété des moyens de production : de −1,0 à −0,7 (vers Public)<br>Contrôle de l'économie : de −1,0 à −0,5 (vers Planification)<br>Méthode de changement : de +0,2 à +1,0 (vers Rupture)<br>Protection sociale et fiscalité : de −1,0 à −0,6 (vers Redistribution) | Propriété collective des moyens de production et planification. |
| **Écosocialiste** (`ecosocialiste`) | gauche | Propriété des moyens de production : de −1,0 à −0,3 (vers Public)<br>Technologie et nature : de −0,3 à +1,0 (plage large)<br>Écologie : de +0,5 à +1,0 (vers Écologie) | Socialisme qui place l'écologie au centre. |
| **Extrême-Gauche** (`extreme_gauche`) | extrême gauche | Propriété des moyens de production : de −1,0 à −0,6 (vers Public)<br>Contrôle de l'économie : de −1,0 à −0,4 (vers Planification)<br>Morale et mœurs : de −1,0 à +0,1 (plage large)<br>Méthode de changement : de +0,4 à +1,0 (vers Rupture)<br>Protection sociale et fiscalité : de −1,0 à −0,6 (vers Redistribution) | Transformation radicale de l'économie et de la société, en rupture avec le système actuel. |
| **Gauche radicale** (`gauche_radicale`) | extrême gauche | Propriété des moyens de production : de −1,0 à −0,5 (vers Public)<br>Contrôle de l'économie : de −1,0 à −0,3 (vers Planification)<br>Méthode de changement : de +0,1 à +0,9 (neutre ou vers Rupture)<br>Protection sociale et fiscalité : de −1,0 à −0,5 (vers Redistribution) | Forte redistribution et contrôle de l'économie, par des changements profonds. |
| **Gaulliste** (`gaulliste`) | droite | Structure de l'État : de 0 à +1,0 (neutre ou vers Unitaire)<br>Intervention et souveraineté : de +0,2 à +1,0 (vers Nationaliste)<br>Commerce international : de −1,0 à +0,2 (plage large)<br>Souveraineté et Europe : de −1,0 à +0,2 (plage large)<br>Alliances et blocs : de −1,0 à +0,2 (plage large) | Indépendance nationale, État fort, exécutif fort sous la Ve République. |
| **Keynésien** (`keynesien`) | centre | Propriété des moyens de production : de −0,6 à +0,2 (plage large)<br>Contrôle de l'économie : de −1,0 à +0,1 (plage large)<br>Méthode de changement : de −1,0 à +0,2 (plage large)<br>Protection sociale et fiscalité : de −1,0 à +0,2 (plage large) | Intervention de l'État pour soutenir l'activité, dans le cadre d'une économie de marché. |
| **Socialiste** (`socialiste`) | gauche | Propriété des moyens de production : de −1,0 à −0,2 (vers Public)<br>Contrôle de l'économie : de −1,0 à +0,1 (plage large)<br>Morale et mœurs : de −1,0 à +0,3 (plage large)<br>Méthode de changement : de −0,6 à +0,4 (plage large)<br>Protection sociale et fiscalité : de −1,0 à −0,3 (vers Redistribution) | Redistribution et services publics forts, par la réforme. |

### Positions

| Idéologie | Spectre | Ce qu'elle implique | Description |
| --- | --- | --- | --- |
| **Altermondialiste** (`alter_mondialiste`) |  | Immigration et identité : de 0 à +1,0 (neutre ou vers Multiculturalisme)<br>Propriété des moyens de production : de −1,0 à 0 (neutre ou vers Public) | Favorable à la coopération internationale, mais contre la mondialisation libérale. |
| **Animaliste** (`animaliste`) |  | Technologie et nature : de −0,2 à +1,0 (plage large)<br>Écologie : de 0 à +1,0 (neutre ou vers Écologie)<br>Condition animale : de −1,0 à −0,3 (vers Droits des animaux) | Défense de la condition animale. |
| **Écologiste** (`ecologiste`) |  | Technologie et nature : de −0,2 à +1,0 (plage large)<br>Écologie : de +0,4 à +1,0 (vers Écologie) | Place la protection de l'environnement au premier rang. |
| **Égalitariste** (`egalitariste`) |  | Propriété des moyens de production : de −1,0 à +0,2 (plage large)<br>Morale et mœurs : de −1,0 à +0,3 (plage large)<br>Protection sociale et fiscalité : de −1,0 à −0,2 (vers Redistribution) | Fait de l'égalité sociale et économique une priorité. |
| **Européiste** (`europeiste`) |  | Structure de l'État : de −1,0 à +0,2 (plage large)<br>Intervention et souveraineté : de −1,0 à +0,3 (plage large)<br>Commerce international : de −0,2 à +1,0 (plage large)<br>Souveraineté et Europe : de +0,3 à +1,0 (vers Intégration européenne) | Favorable à plus d'intégration européenne. |
| **Eurosceptique** (`eurosceptique`) |  | Intervention et souveraineté : de 0 à +1,0 (neutre ou vers Nationaliste)<br>Souveraineté et Europe : de −1,0 à −0,2 (vers Souveraineté nationale) | Défavorable à l'intégration européenne actuelle. |
| **Féministe** (`feministe`) |  | Morale et mœurs : de −1,0 à −0,2 (vers Progressiste)<br>Genre et égalité des sexes : de −1,0 à −0,3 (vers Égalité des genres) | Favorable à l'égalité entre les sexes. |
| **Mondialiste** (`mondialiste`) |  | Intervention et souveraineté : de −1,0 à +0,2 (plage large)<br>Commerce international : de +0,3 à +1,0 (vers Globalisme) | Favorable à l'ouverture des échanges et à la coopération mondiale. |
| **Multiculturaliste** (`multiculturaliste`) |  | Immigration et identité : de +0,4 à +1,0 (vers Multiculturalisme) | Favorable à la diversité culturelle et à l'accueil. |
| **Progressiste** (`progressiste`) |  | Morale et mœurs : de −1,0 à −0,3 (vers Progressiste)<br>Genre et égalité des sexes : de −1,0 à +0,1 (plage large) | Favorable à l'évolution des mœurs et à l'extension des droits. |
| **Protectionniste** (`protectionnisme`) |  | Commerce international : de −1,0 à −0,3 (vers Protectionnisme) | Favorable à la protection de l'économie nationale. |
| **Survivaliste / autarcique** (`survivaliste`) |  | Commerce international : de −1,0 à −0,2 (vers Protectionnisme) | Recherche l'autonomie, jusqu'à l'autosuffisance. |

### Valeurs et attitudes

| Idéologie | Spectre | Ce qu'elle implique | Description |
| --- | --- | --- | --- |
| **Antifasciste** (`antifasciste`) |  | Représentation et régime : de −1,0 à 0 (neutre ou vers Démocratie)<br>Immigration et identité : de 0 à +1,0 (neutre ou vers Multiculturalisme) | Opposé aux idéologies d'extrême droite. |
| **Autre voie** (`autre_voie`) |  | *rien à vérifier* | Ne se reconnaît pas dans les grandes familles. Rien à vérifier. |
| **Démocrate** (`democrate`) |  | Représentation et régime : de −1,0 à −0,2 (vers Démocratie)<br>Démocratie directe ou représentative : de −1,0 à +0,4 (plage large) | Attaché à la démocratie et à la participation. |
| **Humaniste** (`humaniste`) |  | Pouvoir de l'État sur l'individu : de 0 à +1,0 (neutre ou vers Liberté)<br>Immigration et identité : de 0 à +1,0 (neutre ou vers Multiculturalisme) | Place la dignité de la personne au premier rang. |
| **Patriote** (`patriote`) |  | Immigration et identité : de −1,0 à +0,4 (plage large)<br>Intervention et souveraineté : de +0,2 à +1,0 (vers Nationaliste) | Attaché à son pays et à son identité. |
| **Pragmatique** (`pragmatique`) |  | Méthode de changement : de −1,0 à +0,2 (plage large) | Préfère les solutions concrètes aux principes. |
| **Républicain** (`republicain`) |  | Structure de l'État : de 0 à +1,0 (neutre ou vers Unitaire)<br>Immigration et identité : de −1,0 à +0,3 (plage large)<br>Religion et État : de −1,0 à +0,2 (plage large) | Attaché aux principes de la République : égalité, laïcité, universalisme. |
| **Spiritualité** (`spiritualite`) |  | *rien à vérifier* | Dimension spirituelle ou religieuse. Rien à vérifier sur les axes. |

## Ce que vous pouvez faire en relisant

- Une définition est floue ou partiale : corrigez le texte dans `seed-axes.sql`.
- Un pôle est dans le mauvais sens, ou un axe en recouvre un autre : dites-le, c'est ce qui compte le plus pour la qualité du classement.
- Une plage d'idéologie est trop étroite ou trop large : changez ses bornes.
- Il manque un axe ou une idéologie : ajoutez une ligne dans `seed-axes.sql`.
- Vous voulez éteindre un axe : `UPDATE axes SET is_active = false WHERE code = '...';`
