-- Settings that are changed from the interface while everything runs (the performance limits of the bot and of the AI): the bot and the analysis read them again
-- by themselves, without a restart.
CREATE TABLE IF NOT EXISTS runtime_settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
