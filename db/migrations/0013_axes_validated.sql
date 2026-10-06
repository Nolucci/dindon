-- A person decided the axes of a proposition (validated them as proposed, corrected them, or said that it weighs on none). The propositions that were decided are
-- what the model is shown as examples when it reads a new one (analysis/axes.py): « validated by a person » includes « on no axis », which a link cannot say.
ALTER TABLE propositions ADD COLUMN IF NOT EXISTS axes_validated_at timestamptz;
UPDATE propositions SET axes_validated_at = now() WHERE axes_validated_at IS NULL AND id IN (SELECT proposition_id FROM proposition_axis WHERE is_validated);
