-- The reread (« relecture »): a pass, apart from the analysis, that reads again each position of each person with the messages that came before it, says whether it is right, and when it is not
-- corrects it (the sense of the position, the proposition it is about, its theme). What was changed is kept with what it was, so that it can be undone; what a person decided is never touched.

-- Where a claim was last reread, to resume a stopped reread and not to read again what the current method already read.
ALTER TABLE claims ADD COLUMN IF NOT EXISTS reread_at timestamptz;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS reread_version text;
CREATE INDEX IF NOT EXISTS claims_reread_idx ON claims (guild_id, reread_version);

-- One reread: when, over what, with which model, and what came of it (counts only)
CREATE TABLE IF NOT EXISTS reread_runs (
    id          bigserial PRIMARY KEY,
    guild_id    bigint NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    state       text NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'done', 'cancelled', 'failed')),
    scope       jsonb NOT NULL DEFAULT '{}',          -- everybody / one person / one theme, and whether what the current method already read is read again
    model       text,
    version     text,
    counts      jsonb NOT NULL DEFAULT '{}',          -- read, confirmed, corrected, ... , and the audit of the scores
    error       text
);
CREATE INDEX IF NOT EXISTS reread_runs_guild_idx ON reread_runs (guild_id, id DESC);

-- What a reread decided about one claim, with what it was before (to undo it) and why
CREATE TABLE IF NOT EXISTS claim_rereads (
    run_id      bigint NOT NULL REFERENCES reread_runs (id) ON DELETE CASCADE,
    claim_id    bigint NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    verdict     text   NOT NULL CHECK (verdict IN ('confirmed', 'corrected', 'uncertain', 'skipped')),
    changes     jsonb  NOT NULL DEFAULT '{}',          -- {"stance": [before, after], "proposition_id": [..], "kind": [..], "theme": [..]} for what changed
    reason      text,                                  -- in a few words, from the model (never longer than 300 characters)
    certainty   smallint,
    undone_at   timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, claim_id)
);
CREATE INDEX IF NOT EXISTS claim_rereads_claim_idx ON claim_rereads (claim_id);

-- The theme of one claim when it is not the one of the conversation that it was read in (a reread moved it)
CREATE TABLE IF NOT EXISTS claim_topics (
    claim_id   bigint PRIMARY KEY REFERENCES claims (id) ON DELETE CASCADE,
    topic_id   bigint NOT NULL REFERENCES topics (id) ON DELETE CASCADE,
    run_id     bigint REFERENCES reread_runs (id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- The themes of each claim: the one a reread gave it when it did, else those of the conversation that it was read in (what the pages Positions read)
CREATE OR REPLACE VIEW claim_themes AS
SELECT ct.claim_id, ct.topic_id FROM claim_topics ct
UNION ALL
SELECT c.id, a.topic_id FROM claims c JOIN topic_assignments a ON a.conversation_id = c.conversation_id
WHERE NOT EXISTS (SELECT 1 FROM claim_topics x WHERE x.claim_id = c.id);
