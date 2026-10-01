-- Starting point for the axes, the ideologies and the roles. Everything here is meant to be edited:
-- it is a first proposal, and the ideologies are marked as not validated until you have reviewed them.
--
-- THE AXES. The 12 core axes, their names and their two poles come from the "12 Axes" model
-- (https://12axes.vercel.app, "What does each axis mean?"). On that site, each axis has a left pole
-- and a right pole: here, the left pole is -1 and the right pole is +1. The definitions, the
-- reference points and the ideology ranges below are written for this project, not copied.
-- The site says itself that its test is educational and not scientifically validated: the precision
-- of the classification comes from the evidence behind each score, not from the model of axes.
--
-- Nine more axes cover what the 12 do not: Europe, ecology, method of change, and six more that
-- matter in French political debate (social protection and taxes, trust in institutions, gender,
-- animals, alliances, direct democracy). They are all present but inactive: they are not scored
-- until you have reviewed them and activated them (UPDATE axes SET is_active = true ...).
-- AXES.md lists everything in a readable way; it is generated from the database.
--
-- Scores go from -1 to +1. The poles are not "good" or "bad": what matters is that the question is
-- precise and that -1, 0 and +1 each have a clear meaning.
-- Running this file again does not change what is already there.

-- ---------------------------------------------------------------------------------------------
-- Settings of the computation
-- ---------------------------------------------------------------------------------------------

INSERT INTO scoring_settings (key, value, description) VALUES
    ('prior_weight',       1,    'Amount of doubt (a score of 0) added to the evidence, so that one remark never gives a firm score'),
    ('uncertainty_floor',  0.35, 'Smallest possible uncertainty, for the errors that an analysis cannot avoid (sarcasm, quotes...)'),
    ('min_propositions',   3,    'Fewest positions needed on an axis before a claimed ideology can be checked against it'),
    ('min_evidence_weight',1.5,  'Least confidence-weighted evidence needed on an axis before it can be checked')
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- Axes
-- ---------------------------------------------------------------------------------------------

INSERT INTO axes (code, name, question, negative_pole, positive_pole, definition, excludes, position, is_active, origin) VALUES
('structure', 'Structure de l''État',
 'Le pouvoir doit-il être réparti entre les régions et les collectivités, ou concentré dans un État unitaire ?',
 'Fédéral', 'Unitaire',
 'Répartition du pouvoir entre l''État central, les régions, les communes et les communautés locales ; uniformité des lois et du commandement.',
 'Le régime politique (axe representation) et l''Union européenne (axe europe).', 1, true, '12axes'),
('representation', 'Représentation et régime',
 'Le pouvoir doit-il venir d''élections libres et d''une opposition, ou d''un chef, d''un parti ou d''experts ?',
 'Démocratie', 'Autocratie',
 'Confiance dans les élections, l''opposition et les institutions démocratiques, face à la préférence pour un dirigeant fort, la technocratie, la monarchie ou un régime autoritaire.',
 'Les libertés individuelles et la sécurité (axe pouvoir).', 2, true, '12axes'),
('pouvoir', 'Pouvoir de l''État sur l''individu',
 'Faut-il privilégier l''ordre et la sécurité, ou la liberté individuelle ?',
 'Sécurité', 'Liberté',
 'Équilibre entre ordre, surveillance, punition et contrôle de l''État, d''un côté, et vie privée, liberté individuelle et autonomie civile, de l''autre.',
 'Le régime politique (axe representation) et les mœurs (axe morale).', 3, true, '12axes'),
('immigration', 'Immigration et identité',
 'Faut-il exiger l''assimilation à l''identité nationale, ou valoriser le multiculturalisme ?',
 'Assimilation', 'Multiculturalisme',
 'Assimilation culturelle, langue et identité nationale, face au multiculturalisme, à l''ouverture migratoire et à la pluralité des coutumes.',
 'La religion dans la vie publique (axe religion) et les mœurs (axe morale).', 4, true, '12axes'),
('diplomatie', 'Armée et diplomatie',
 'Faut-il miser sur la force militaire ou sur la négociation ?',
 'Militariste', 'Pacifiste',
 'Forces armées, armement, dissuasion et intervention militaire, face à la négociation, au pacifisme et aux organismes internationaux.',
 'La place du pays dans le monde en général (axe intervention).', 5, true, '12axes'),
('intervention', 'Intervention et souveraineté',
 'Faut-il rester en retrait du monde ou défendre activement les intérêts nationaux ?',
 'Non-interventionniste', 'Nationaliste',
 'Entre le non-interventionnisme extérieur et une souveraineté nationale plus affirmée : nationalisme géopolitique et défense active des intérêts nationaux.',
 'L''emploi de la force militaire en soi (axe diplomatie) et le commerce (axe commerce).', 6, true, '12axes'),
('economie', 'Propriété des moyens de production',
 'Les entreprises et les services essentiels doivent-ils être publics ou privés ?',
 'Public', 'Privé',
 'Préférence pour la propriété publique, les entreprises d''État et les services collectifs, face à la propriété privée, aux privatisations et au rôle des entreprises.',
 'La façon dont l''économie est dirigée (axe controle).', 7, true, '12axes'),
('controle', 'Contrôle de l''économie',
 'L''économie doit-elle être planifiée et régulée, ou laissée au libre marché ?',
 'Planification', 'Libre marché',
 'Planification d''État, régulation et politique économique active, face au libre marché, à la faible intervention, à l''autonomie monétaire et à la concurrence.',
 'La propriété des entreprises (axe economie) et le commerce international (axe commerce).', 8, true, '12axes'),
('commerce', 'Commerce international',
 'Faut-il protéger l''industrie nationale ou ouvrir l''économie au commerce mondial ?',
 'Protectionnisme', 'Globalisme',
 'Protectionnisme, souveraineté productive et défense de l''industrie nationale, face au libre-échange et à l''intégration économique internationale.',
 'L''Union européenne en tant que telle (axe europe).', 9, true, '12axes'),
('religion', 'Religion et État',
 'La religion doit-elle rester hors de la vie publique, ou y avoir une influence ?',
 'Irréligieux', 'Religieux',
 'Laïcité, séparation de la religion et de l''État et critique des privilèges religieux, face à l''influence publique de la foi et des valeurs religieuses.',
 'L''immigration (axe immigration) et les mœurs (axe morale).', 10, true, '12axes'),
('morale', 'Morale et mœurs',
 'Faut-il faire évoluer les normes sociales ou préserver la tradition ?',
 'Progressiste', 'Traditionaliste',
 'Progressisme culturel, droits civils et changements sociaux, face à la tradition, à la famille, aux coutumes et au conservatisme moral.',
 'La religion dans la vie publique (axe religion), l''immigration (axe immigration) et le genre (axe genre).', 11, true, '12axes'),
('technologie', 'Technologie et nature',
 'Faut-il accélérer le développement technique ou faire preuve de prudence envers le vivant et l''environnement ?',
 'Technologie', 'Biologie',
 'Enthousiasme pour la technologie, l''IA, le génie génétique et le développement technique, face à la prudence biologique, environnementale et préservationniste.',
 'Le rôle de l''État dans l''économie (axes economie et controle).', 12, true, '12axes'),
-- Extensions: inactive until you decide to use them
('europe', 'Souveraineté et Europe',
 'Faut-il plus de pouvoir national ou plus d''intégration européenne ?',
 'Souveraineté nationale', 'Intégration européenne',
 'Place de l''Union européenne, de l''euro et des traités par rapport aux décisions nationales.',
 'Le commerce mondial en général (axe commerce) et la structure interne de l''État (axe structure).', 13, false, 'custom'),
('ecologie', 'Écologie',
 'Faut-il subordonner l''économie à l''environnement ?',
 'Productivisme', 'Écologie',
 'Climat, énergie, biodiversité, sobriété, croissance, contraintes environnementales, condition animale.',
 'La prudence envers la technologie (axe technologie), le rôle de l''État (axes economie et controle) et la condition animale (axe animaux).', 14, false, 'custom'),
('rupture', 'Méthode de changement',
 'Faut-il changer la société par la réforme ou par la rupture ?',
 'Réforme', 'Rupture',
 'La façon de changer les choses, quelle que soit la direction : compromis et réformes graduelles, ou changement radical du système.',
 'La direction du changement (tous les autres axes).', 15, false, 'custom'),
('redistribution', 'Protection sociale et fiscalité',
 'Faut-il réduire les inégalités par l''impôt et la protection sociale, ou laisser chacun responsable de ses revenus ?',
 'Redistribution', 'Mérite individuel',
 'Impôts, prestations sociales, retraites, assurance chômage, droit du travail et lutte contre les inégalités, face à la responsabilité individuelle, à la baisse des prélèvements et à la flexibilité.',
 'La propriété des entreprises (axe economie) et la planification (axe controle).', 16, false, 'custom'),
('confiance', 'Confiance dans les institutions et les experts',
 'Faut-il faire confiance aux institutions, aux experts et aux médias établis, ou s''en défier ?',
 'Confiance', 'Défiance',
 'Confiance dans les institutions, la science, les experts, la justice et les grands médias, face à la défiance envers les élites et les versions officielles.',
 'Le régime politique (axe representation) et les opinions sur un sujet précis (qui relèvent des autres axes).', 17, false, 'custom'),
('genre', 'Genre et égalité des sexes',
 'Faut-il aller vers plus d''égalité et de fluidité des genres, ou maintenir des rôles et des identités traditionnels ?',
 'Égalité des genres', 'Rôles traditionnels',
 'Égalité entre les sexes, féminisme, identités de genre, droits des personnes LGBT, face aux rôles et aux différences traditionnels entre hommes et femmes.',
 'La famille et les mœurs en général (axe morale).', 18, false, 'custom'),
('animaux', 'Condition animale',
 'Faut-il reconnaître des droits aux animaux ou conserver leur usage par l''humain ?',
 'Droits des animaux', 'Usage humain des animaux',
 'Élevage, chasse, corrida, expérimentation animale, alimentation carnée, statut juridique de l''animal.',
 'Les politiques environnementales en général (axe ecologie).', 19, false, 'custom'),
('alliances', 'Alliances et blocs',
 'Faut-il rester arrimé au bloc occidental ou rester non-aligné ?',
 'Non-alignement', 'Atlantisme',
 'OTAN, alliance avec les États-Unis, appartenance au bloc occidental, rapport à la Russie et à la Chine, face à l''indépendance et au non-alignement.',
 'L''usage de la force en soi (axe diplomatie) et l''ouverture aux échanges (axe commerce).', 20, false, 'custom'),
('participation', 'Démocratie directe ou représentative',
 'Les citoyens doivent-ils décider directement, ou par l''intermédiaire d''élus ?',
 'Démocratie directe', 'Démocratie représentative',
 'Référendum d''initiative citoyenne, tirage au sort, assemblées citoyennes et consultation permanente, face à la délégation du pouvoir à des élus et à un exécutif stable.',
 'Le fait d''être démocratique ou non (axe representation).', 21, false, 'custom')
ON CONFLICT (code) DO NOTHING;

INSERT INTO axis_anchors (axis_id, value, description)
SELECT a.id, v.value, v.description
FROM (VALUES
 ('structure', -1.0, 'Le pouvoir appartient surtout aux régions et aux communautés locales, qui font leurs propres lois ; l''État central a un rôle minimal.'),
 ('structure',  0.0, 'Un État décentralisé : les compétences sont partagées entre l''État et les collectivités.'),
 ('structure',  1.0, 'Un État unitaire fort : les mêmes lois et un commandement unique pour tout le territoire.'),
 ('representation', -1.0, 'Le pouvoir vient d''élections libres et pluralistes, avec une opposition et des contre-pouvoirs, voire de la démocratie directe.'),
 ('representation',  0.0, 'Une démocratie qui laisse une grande place à un exécutif fort ou à des experts.'),
 ('representation',  1.0, 'Le pouvoir est concentré dans un chef, un parti, un monarque ou des experts, sans opposition réelle.'),
 ('pouvoir', -1.0, 'L''ordre et la sécurité passent avant tout : une surveillance et des sanctions fortes sont acceptables.'),
 ('pouvoir',  0.0, 'Un équilibre entre sécurité et libertés, au cas par cas.'),
 ('pouvoir',  1.0, 'La liberté individuelle passe avant tout : peu de surveillance, peu de punition, une grande autonomie.'),
 ('immigration', -1.0, 'Les nouveaux arrivants doivent s''assimiler pleinement à la langue, à la culture et à l''identité nationales.'),
 ('immigration',  0.0, 'L''intégration est attendue, tout en respectant certaines différences.'),
 ('immigration',  1.0, 'La diversité des cultures est une richesse : le multiculturalisme et l''ouverture migratoire sont à encourager.'),
 ('diplomatie', -1.0, 'Une armée forte et la dissuasion sont la meilleure garantie de la paix ; le recours à la force est légitime.'),
 ('diplomatie',  0.0, 'Une défense solide, avec une préférence pour la négociation.'),
 ('diplomatie',  1.0, 'Le pacifisme prime : désarmement, négociation et organismes internationaux plutôt que la force.'),
 ('intervention', -1.0, 'Le pays doit rester en dehors des affaires du monde et n''intervenir nulle part à l''étranger.'),
 ('intervention',  0.0, 'Une action extérieure limitée, pour des raisons précises.'),
 ('intervention',  1.0, 'La souveraineté doit être affirmée : défendre activement les intérêts nationaux, y compris par la puissance.'),
 ('economie', -1.0, 'Les moyens de production et les services essentiels appartiennent à la collectivité : entreprises publiques, propriété collective.'),
 ('economie',  0.0, 'Une économie mixte, avec un secteur public et un secteur privé.'),
 ('economie',  1.0, 'La propriété privée et les entreprises sont le moteur de l''économie : il faut privatiser l''essentiel.'),
 ('controle', -1.0, 'L''État planifie l''économie et oriente fortement la production, les prix et l''investissement.'),
 ('controle',  0.0, 'Un marché régulé par l''État.'),
 ('controle',  1.0, 'Un marché libre, avec une intervention minimale de l''État, de la concurrence et une monnaie autonome.'),
 ('commerce', -1.0, 'Protéger l''industrie nationale par des droits de douane et viser la souveraineté productive.'),
 ('commerce',  0.0, 'Des échanges ouverts, avec des protections ciblées.'),
 ('commerce',  1.0, 'Le libre-échange et l''intégration économique internationale, sans barrières.'),
 ('religion', -1.0, 'Séparation stricte de la religion et de l''État, aucun privilège religieux, et critique de la religion dans l''espace public.'),
 ('religion',  0.0, 'Une laïcité qui respecte les pratiques religieuses.'),
 ('religion',  1.0, 'La foi et les valeurs religieuses doivent avoir une influence publique : lois, institutions, éducation.'),
 ('morale', -1.0, 'Le progrès culturel et l''extension des droits civils sont à encourager, sans frein de la tradition.'),
 ('morale',  0.0, 'Les évolutions sont acceptées au cas par cas, avec prudence.'),
 ('morale',  1.0, 'La tradition, la famille et les coutumes doivent être préservées ; les évolutions de mœurs sont à freiner.'),
 ('technologie', -1.0, 'Le développement technique, l''IA et le génie génétique sont à accélérer, avec peu de limites.'),
 ('technologie',  0.0, 'Du progrès technique, encadré.'),
 ('technologie',  1.0, 'La prudence biologique et environnementale prime : préserver le vivant et limiter les technologies.'),
 ('europe', -1.0, 'La France doit retrouver la maîtrise de ses lois et de sa monnaie, quitte à quitter l''Union européenne.'),
 ('europe',  0.0, 'L''Union est utile, mais ses pouvoirs doivent rester limités.'),
 ('europe',  1.0, 'L''Europe doit devenir une fédération, avec un gouvernement commun.'),
 ('ecologie', -1.0, 'La croissance et l''industrie passent avant ; les contraintes environnementales sont excessives.'),
 ('ecologie',  0.0, 'Une transition progressive, compatible avec la croissance.'),
 ('ecologie',  1.0, 'L''environnement prime : sobriété, voire décroissance, et fortes contraintes sont nécessaires.'),
 ('rupture', -1.0, 'Seules des réformes graduelles et consensuelles sont légitimes ; la rupture est dangereuse.'),
 ('rupture',  0.0, 'Des réformes profondes, mais dans le cadre existant.'),
 ('rupture',  1.0, 'Le système actuel doit être renversé ou refondé ; les réformes ne suffisent pas.'),
 ('redistribution', -1.0, 'Les inégalités doivent être fortement réduites par l''impôt, des prestations généreuses et une forte protection des travailleurs.'),
 ('redistribution',  0.0, 'Une protection sociale solide mais financée avec mesure, entre solidarité et responsabilité.'),
 ('redistribution',  1.0, 'Chacun est responsable de sa situation : impôts et prestations réduits au minimum, marché du travail flexible.'),
 ('confiance', -1.0, 'Les institutions, les experts et la science sont globalement fiables, et leurs conclusions doivent guider l''action.'),
 ('confiance',  0.0, 'Une confiance prudente : vérifier et critiquer, sans rejeter en bloc.'),
 ('confiance',  1.0, 'Les élites, les médias et les versions officielles sont suspects : il faut s''en défier par principe.'),
 ('genre', -1.0, 'L''égalité réelle entre les sexes et la reconnaissance de toutes les identités de genre sont des priorités, avec des mesures actives.'),
 ('genre',  0.0, 'L''égalité des droits est acquise ; les évolutions se font avec prudence.'),
 ('genre',  1.0, 'Les rôles et les différences traditionnels entre hommes et femmes doivent être préservés.'),
 ('animaux', -1.0, 'Les animaux ont des droits : il faut abolir l''élevage intensif, la chasse et la corrida.'),
 ('animaux',  0.0, 'Le bien-être animal doit être amélioré, tout en maintenant les usages.'),
 ('animaux',  1.0, 'L''usage des animaux (élevage, chasse, traditions) est légitime et ne doit pas être restreint.'),
 ('alliances', -1.0, 'La France doit sortir de l''OTAN et ne s''aligner sur aucun bloc.'),
 ('alliances',  0.0, 'Des alliances utiles, en gardant une autonomie de décision.'),
 ('alliances',  1.0, 'La France doit rester pleinement dans l''alliance occidentale et suivre sa ligne.'),
 ('participation', -1.0, 'Les citoyens doivent pouvoir proposer, voter et révoquer directement (RIC, tirage au sort) ; les élus ne sont que des exécutants.'),
 ('participation',  0.0, 'Des élus qui décident, avec des référendums et des consultations pour les grandes questions.'),
 ('participation',  1.0, 'Les élus décident : le pouvoir est délégué à des représentants et à un exécutif stable, sans référendum permanent.')
) AS v(axis_code, value, description)
JOIN axes a ON a.code = v.axis_code
ON CONFLICT (axis_id, value) DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- Ideologies: a first proposal of what each one implies, to be reviewed
-- ---------------------------------------------------------------------------------------------

INSERT INTO ideologies (code, name, kind, spectrum, description) VALUES
-- Political families
('extreme_gauche',   'Extrême-Gauche',     'famille',  'radical_left', 'Transformation radicale de l''économie et de la société, en rupture avec le système actuel.'),
('gauche_radicale',  'Gauche radicale',    'famille',  'radical_left', 'Forte redistribution et contrôle de l''économie, par des changements profonds.'),
('communiste',       'Communiste',         'famille',  'radical_left', 'Propriété collective des moyens de production et planification.'),
('socialiste',       'Socialiste',         'famille',  'left',         'Redistribution et services publics forts, par la réforme.'),
('ecosocialiste',    'Écosocialiste',      'famille',  'left',         'Socialisme qui place l''écologie au centre.'),
('keynesien',        'Keynésien',          'famille',  'center',       'Intervention de l''État pour soutenir l''activité, dans le cadre d''une économie de marché.'),
('centre_gauche',    'Centre-Gauche',      'famille',  'center',       'Progressisme social et économie mixte, par la réforme.'),
('gaulliste',        'Gaulliste',          'famille',  'right',        'Indépendance nationale, État fort, exécutif fort sous la Ve République.'),
-- Positions on one or two axes
('europeiste',       'Européiste',         'position', NULL, 'Favorable à plus d''intégration européenne.'),
('eurosceptique',    'Eurosceptique',      'position', NULL, 'Défavorable à l''intégration européenne actuelle.'),
('protectionnisme',  'Protectionniste',    'position', NULL, 'Favorable à la protection de l''économie nationale.'),
('mondialiste',      'Mondialiste',        'position', NULL, 'Favorable à l''ouverture des échanges et à la coopération mondiale.'),
('alter_mondialiste','Altermondialiste',   'position', NULL, 'Favorable à la coopération internationale, mais contre la mondialisation libérale.'),
('ecologiste',       'Écologiste',         'position', NULL, 'Place la protection de l''environnement au premier rang.'),
('animaliste',       'Animaliste',         'position', NULL, 'Défense de la condition animale.'),
('multiculturaliste','Multiculturaliste',  'position', NULL, 'Favorable à la diversité culturelle et à l''accueil.'),
('progressiste',     'Progressiste',       'position', NULL, 'Favorable à l''évolution des mœurs et à l''extension des droits.'),
('feministe',        'Féministe',          'position', NULL, 'Favorable à l''égalité entre les sexes.'),
('egalitariste',     'Égalitariste',       'position', NULL, 'Fait de l''égalité sociale et économique une priorité.'),
('survivaliste',     'Survivaliste / autarcique', 'position', NULL, 'Recherche l''autonomie, jusqu''à l''autosuffisance.'),
-- Values and attitudes: they only imply something weak
('republicain',      'Républicain',        'valeur',   NULL, 'Attaché aux principes de la République : égalité, laïcité, universalisme.'),
('patriote',         'Patriote',           'valeur',   NULL, 'Attaché à son pays et à son identité.'),
('democrate',        'Démocrate',          'valeur',   NULL, 'Attaché à la démocratie et à la participation.'),
('humaniste',        'Humaniste',          'valeur',   NULL, 'Place la dignité de la personne au premier rang.'),
('antifasciste',     'Antifasciste',       'valeur',   NULL, 'Opposé aux idéologies d''extrême droite.'),
('pragmatique',      'Pragmatique',        'valeur',   NULL, 'Préfère les solutions concrètes aux principes.'),
('autre_voie',       'Autre voie',         'valeur',   NULL, 'Ne se reconnaît pas dans les grandes familles. Rien à vérifier.'),
('spiritualite',     'Spiritualité',       'valeur',   NULL, 'Dimension spirituelle ou religieuse. Rien à vérifier sur les axes.')
ON CONFLICT (code) DO NOTHING;

-- What each ideology implies: the range where someone who claims it can be expected to stand.
-- Remember that -1 is the left pole of an axis and +1 its right pole (economie: -1 public, +1 privé).
-- The ranges are wide on purpose: a mismatch is only reported when the evidence is clearly outside.
-- Ranges on inactive axes only count once these axes are activated.
INSERT INTO ideology_axis_ranges (ideology_id, axis_id, min_score, max_score)
SELECT i.id, a.id, r.min_score, r.max_score
FROM (VALUES
 ('extreme_gauche',   'economie',       -1.00, -0.60),
 ('extreme_gauche',   'controle',       -1.00, -0.40),
 ('extreme_gauche',   'morale',         -1.00,  0.10),
 ('extreme_gauche',   'rupture',         0.40,  1.00),
 ('gauche_radicale',  'economie',       -1.00, -0.50),
 ('gauche_radicale',  'controle',       -1.00, -0.30),
 ('gauche_radicale',  'rupture',         0.10,  0.90),
 ('communiste',       'economie',       -1.00, -0.70),
 ('communiste',       'controle',       -1.00, -0.50),
 ('communiste',       'rupture',         0.20,  1.00),
 ('socialiste',       'economie',       -1.00, -0.20),
 ('socialiste',       'controle',       -1.00,  0.10),
 ('socialiste',       'morale',         -1.00,  0.30),
 ('socialiste',       'rupture',        -0.60,  0.40),
 ('ecosocialiste',    'economie',       -1.00, -0.30),
 ('ecosocialiste',    'technologie',    -0.30,  1.00),
 ('ecosocialiste',    'ecologie',        0.50,  1.00),
 ('keynesien',        'economie',       -0.60,  0.20),
 ('keynesien',        'controle',       -1.00,  0.10),
 ('keynesien',        'rupture',        -1.00,  0.20),
 ('centre_gauche',    'economie',       -0.60,  0.30),
 ('centre_gauche',    'controle',       -0.70,  0.40),
 ('centre_gauche',    'morale',         -1.00,  0.40),
 ('centre_gauche',    'rupture',        -1.00,  0.10),
 ('gaulliste',        'structure',       0.00,  1.00),
 ('gaulliste',        'intervention',    0.20,  1.00),
 ('gaulliste',        'commerce',       -1.00,  0.20),
 ('gaulliste',        'europe',         -1.00,  0.20),
 ('europeiste',       'structure',      -1.00,  0.20),
 ('europeiste',       'intervention',   -1.00,  0.30),
 ('europeiste',       'commerce',       -0.20,  1.00),
 ('europeiste',       'europe',          0.30,  1.00),
 ('eurosceptique',    'intervention',    0.00,  1.00),
 ('eurosceptique',    'europe',         -1.00, -0.20),
 ('protectionnisme',  'commerce',       -1.00, -0.30),
 ('mondialiste',      'commerce',        0.30,  1.00),
 ('mondialiste',      'intervention',   -1.00,  0.20),
 ('alter_mondialiste','economie',       -1.00,  0.00),
 ('alter_mondialiste','immigration',     0.00,  1.00),
 ('ecologiste',       'technologie',    -0.20,  1.00),
 ('ecologiste',       'ecologie',        0.40,  1.00),
 ('animaliste',       'technologie',    -0.20,  1.00),
 ('animaliste',       'ecologie',        0.00,  1.00),
 ('multiculturaliste','immigration',     0.40,  1.00),
 ('progressiste',     'morale',         -1.00, -0.30),
 ('feministe',        'morale',         -1.00, -0.20),
 ('egalitariste',     'economie',       -1.00,  0.20),
 ('egalitariste',     'morale',         -1.00,  0.30),
 ('survivaliste',     'commerce',       -1.00, -0.20),
 ('republicain',      'structure',       0.00,  1.00),
 ('republicain',      'immigration',    -1.00,  0.30),
 ('republicain',      'religion',       -1.00,  0.20),
 ('patriote',         'intervention',    0.20,  1.00),
 ('patriote',         'immigration',    -1.00,  0.40),
 ('democrate',        'representation', -1.00, -0.20),
 ('humaniste',        'immigration',     0.00,  1.00),
 ('humaniste',        'pouvoir',         0.00,  1.00),
 ('antifasciste',     'representation', -1.00,  0.00),
 ('antifasciste',     'immigration',     0.00,  1.00),
 ('pragmatique',      'rupture',        -1.00,  0.20),
 ('extreme_gauche',   'redistribution', -1.00, -0.60),
 ('gauche_radicale',  'redistribution', -1.00, -0.50),
 ('communiste',       'redistribution', -1.00, -0.60),
 ('socialiste',       'redistribution', -1.00, -0.30),
 ('keynesien',        'redistribution', -1.00,  0.20),
 ('centre_gauche',    'redistribution', -0.80,  0.20),
 ('egalitariste',     'redistribution', -1.00, -0.20),
 ('feministe',        'genre',          -1.00, -0.30),
 ('progressiste',     'genre',          -1.00,  0.10),
 ('animaliste',       'animaux',        -1.00, -0.30),
 ('gaulliste',        'alliances',      -1.00,  0.20),
 ('democrate',        'participation',  -1.00,  0.40)
) AS r(ideology_code, axis_code, min_score, max_score)
JOIN ideologies i ON i.code = r.ideology_code
JOIN axes a       ON a.code = r.axis_code
ON CONFLICT (ideology_id, axis_id) DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- Roles: which ones are ideologies, which ones are not
-- ---------------------------------------------------------------------------------------------

-- Patterns are lowercase and without accents, because roles are compared that way.
INSERT INTO role_rules (match_type, pattern, kind, ideology_id)
SELECT 'exact', r.pattern, 'ideologie', i.id
FROM (VALUES
 ('extreme-gauche', 'extreme_gauche'), ('gauche radicale', 'gauche_radicale'), ('communiste', 'communiste'),
 ('socialiste', 'socialiste'), ('ecosocialiste', 'ecosocialiste'), ('keynesien', 'keynesien'),
 ('centre-gauche', 'centre_gauche'), ('gaulliste', 'gaulliste'), ('europeiste', 'europeiste'),
 ('eurosceptique', 'eurosceptique'), ('protectionnisme', 'protectionnisme'), ('mondialiste', 'mondialiste'),
 ('alter-mondialiste', 'alter_mondialiste'), ('ecologiste', 'ecologiste'), ('animaliste', 'animaliste'),
 ('multiculturaliste', 'multiculturaliste'), ('progressiste', 'progressiste'), ('feministe', 'feministe'),
 ('egalitariste', 'egalitariste'), ('survivaliste/autarcique', 'survivaliste'), ('republicain', 'republicain'),
 ('patriote', 'patriote'), ('democrate', 'democrate'), ('humaniste', 'humaniste'),
 ('antifasciste', 'antifasciste'), ('pragmatique', 'pragmatique'), ('autre voie', 'autre_voie'),
 ('spiritualite', 'spiritualite')
) AS r(pattern, ideology_code)
JOIN ideologies i ON i.code = r.ideology_code
ON CONFLICT (match_type, pattern) DO NOTHING;

-- Roles that say nothing about ideas. Age and gender are recognized only to be left out.
INSERT INTO role_rules (match_type, pattern, kind) VALUES
 ('exact', 'gardien de la democratie', 'staff'),
 ('exact', 'mediateur',                'staff'),
 ('exact', 'animateur',                'staff'),
 ('regex', '^ping ',                   'notification'),
 ('regex', '^entre [0-9]+ et [0-9]+ ans$', 'age'),
 ('exact', 'homme',                    'genre'),
 ('exact', 'femme',                    'genre'),
 ('exact', 'membre',                   'base'),
 ('regex', '^[-_=.–— ]{5,}$',            'separateur')
ON CONFLICT (match_type, pattern) DO NOTHING;
