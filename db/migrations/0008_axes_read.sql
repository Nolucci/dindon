-- A proposition whose weight on the axes was asked of the model is not asked again, even if it weighs on none
ALTER TABLE propositions ADD COLUMN IF NOT EXISTS axes_read_at timestamptz;
