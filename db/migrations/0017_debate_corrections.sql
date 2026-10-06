-- The public corrections that Dindon posts in a debate thread when trusted sources contradict a claim (docs/DEBAT.md, « Corrections publiques »).
--
-- One row per correction, so that it is posted ONCE (the unique index on the claim), tried again if posting failed (attempts), and **taken back** when what it rests on goes: the claim is
-- deleted when its message is edited or deleted or its author is erased (ingest/loader.py, privacy.erase_person), which sets `claim_id` to null here, and the engine then deletes the message
-- that it had posted on Discord (`posted_message_id`). Nothing in this table says who wrote what: only message numbers.
CREATE TABLE IF NOT EXISTS debate_corrections (
    id                  bigserial PRIMARY KEY,
    debate_id           bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    claim_id            bigint REFERENCES debate_claims (id) ON DELETE SET NULL,
    thread_id           bigint NOT NULL,
    reply_to_message_id bigint NOT NULL,                  -- the message that the correction answers
    posted_message_id   bigint,                           -- the correction on Discord (null until posted)
    attempts            smallint NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    posted_at           timestamptz,
    retracted_at        timestamptz                        -- taken back from Discord, or given up on (after too many failures)
);
CREATE UNIQUE INDEX IF NOT EXISTS debate_corrections_claim_idx ON debate_corrections (claim_id) WHERE claim_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS debate_corrections_retract_idx ON debate_corrections (id) WHERE claim_id IS NULL AND posted_message_id IS NOT NULL AND retracted_at IS NULL;
CREATE INDEX IF NOT EXISTS debate_corrections_debate_idx ON debate_corrections (debate_id, posted_at);
