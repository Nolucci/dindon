-- A topic that the person has acted on (renamed, validated, rejected, merged into, put back) is never replaced by a new run of the
-- discovery: only the proposals that nobody has touched are.
ALTER TABLE topics ADD COLUMN IF NOT EXISTS touched_at timestamptz;
