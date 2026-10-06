-- The register of the people who do not want to be recorded (see docs/CONFORMITE.md). It is the one thing that survives an erasure: the
-- Discord id alone (a number, no name), because without it a later export, a catch-up or the live bot would record the person again.
-- It is read before anything is written (ingest/loader.py) and by the live bot.
CREATE TABLE IF NOT EXISTS privacy_subjects (
    user_id      bigint PRIMARY KEY,                     -- deliberately without a link to `users`: erasing a person deletes their row there
    status       text NOT NULL CHECK (status IN ('stopped', 'erased')),   -- stopped: no longer recorded; erased: also deleted from here
    reason       text,                                    -- 'objection', 'withdrawal', 'erasure', 'manual'
    source       text,                                    -- 'discord' (the person themselves), 'interface', 'cli'
    requested_at timestamptz NOT NULL DEFAULT now(),
    erased_at    timestamptz
);

-- What was done, for being able to show it: an action, a date, counts. Never a message, a name or a content.
CREATE TABLE IF NOT EXISTS privacy_log (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    user_id bigint,                                       -- null for what concerns nobody in particular (retention)
    action  text NOT NULL,                                -- stop, erase, release, export, retention
    source  text,
    detail  jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS privacy_log_user_idx ON privacy_log (user_id, at);
