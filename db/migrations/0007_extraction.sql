-- Stage 4-5 of the analysis (see docs/ANALYSE.md): what each person claims, with proof, and the propositions that the claims are about.

-- Where a claim was read: when the conversation goes (erasure of a person, retention), what was read in it goes with it
ALTER TABLE claims ADD COLUMN IF NOT EXISTS conversation_id bigint REFERENCES conversations (id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS claims_conversation_idx ON claims (conversation_id);

-- A conversation that was read is not read again (even when it yielded nothing)
CREATE TABLE IF NOT EXISTS conversation_extractions (
    conversation_id bigint PRIMARY KEY REFERENCES conversations (id) ON DELETE CASCADE,
    model           text    NOT NULL,
    prompt_version  text    NOT NULL,
    claims          integer NOT NULL,       -- kept, with a proof that the code verified
    refused         integer NOT NULL,       -- proposed by the model, and refused (no valid proof, wrong author, ...)
    done_at         timestamptz NOT NULL DEFAULT now()
);

-- (The vectors of the propositions are in `proposition_embeddings`, which schema-vector.sql already makes.)
