-- An import that was narrowed (by people, by a period) brings only a part of what its channels contain. It is recorded as partial, so
-- that it is never taken for a complete history: the first import, and "go on after the newest message that is known", only count
-- complete imports.
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS is_partial boolean NOT NULL DEFAULT false;
