-- Dindon answers first, without the Internet, and the participants judge its answer (docs/DEBAT.md, « Répondre d'abord, chercher ensuite »).
--
-- When Dindon is certain that a claim of a message is false, it says so under the message, from what its local model knows (no search, no source: the message says so). Under that answer
-- every participant can press Valide or Invalide. Where there is more Invalide than Valide, Dindon then looks on the Internet (the existing verification: trusted sources and verified
-- quotations) and corrects its own message with what it found, whatever it is, including « the claim was right ».
--
-- Like the other debate tables: no foreign key towards `users` or `messages`. An edited or deleted message takes its answers with it (ingest/loader.py), an erased person takes hers
-- (privacy.erase_person), and the message that Dindon had posted on Discord is then taken back through `debate_corrections.answer_id` (set to null with the answer).
CREATE TABLE IF NOT EXISTS debate_answers (
    id          bigserial PRIMARY KEY,
    debate_id   bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    message_id  bigint NOT NULL,
    author_id   bigint NOT NULL,
    claim       text   NOT NULL CHECK (char_length(claim) BETWEEN 3 AND 500),
    said        text   NOT NULL CHECK (char_length(said) BETWEEN 3 AND 500),
    query       text   NOT NULL CHECK (char_length(query) BETWEEN 3 AND 300),    -- the neutral phrase that would be searched if the participants ask for it
    -- true: Dindon is certain that the claim is exact (nothing is said, nothing is searched). false: certain that it is not: it says so, in `answer`.
    verdict     text   NOT NULL CHECK (verdict IN ('true', 'false')),
    answer      text   CHECK (char_length(answer) <= 600),
    model       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    searched_at timestamptz,                                                      -- the participants found the answer invalid: Dindon looked on the Internet (or could not)
    claim_id    bigint REFERENCES debate_claims (id) ON DELETE SET NULL,          -- what it found: a claim checked with sources, as any other
    shown_at    timestamptz,                                                      -- the result was written in Dindon's message on Discord
    CHECK ((verdict = 'false') = (answer IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS debate_answers_debate_idx ON debate_answers (debate_id, created_at);
CREATE INDEX IF NOT EXISTS debate_answers_message_idx ON debate_answers (message_id);
CREATE INDEX IF NOT EXISTS debate_answers_author_idx ON debate_answers (author_id);

CREATE TABLE IF NOT EXISTS debate_answer_votes (
    answer_id bigint NOT NULL REFERENCES debate_answers (id) ON DELETE CASCADE,
    user_id   bigint NOT NULL,
    choice    text   NOT NULL CHECK (choice IN ('valid', 'invalid')),
    voted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (answer_id, user_id)
);
CREATE INDEX IF NOT EXISTS debate_answer_votes_person_idx ON debate_answer_votes (user_id);

-- The message that Dindon posted for an answer is one more row of `debate_corrections`: posted once, tried again if it failed, and taken back when the answer goes.
ALTER TABLE debate_corrections ADD COLUMN IF NOT EXISTS answer_id bigint REFERENCES debate_answers (id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS debate_corrections_answer_idx ON debate_corrections (answer_id) WHERE answer_id IS NOT NULL;
