-- The weight of a proposition on an axis is *proposed* by the model and *validated* by a person. By default every proposed weight counts (as before);
-- with `only_validated_loadings` = 1 only the validated ones count in a person's score.
INSERT INTO scoring_settings (key, value, description) VALUES
    ('only_validated_loadings', 0, '1: only the weights of propositions on axes that a person validated count in the scores of people (0: all of them, as proposed by the model)')
ON CONFLICT (key) DO NOTHING;
