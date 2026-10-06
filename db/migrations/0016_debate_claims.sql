-- The claims that are checked in a debate (docs/DEBAT.md, « Vérification sur Internet »).
--
-- What is stored is the least that makes a result traceable: the claim as restated by the model, the words of the message that carry it, the verdict, and for each source that
-- grounds it the address, the quotation that was **verified on the page**, and the hash of the page. A claim that was judged not to be checkable (an opinion, a question, anything
-- about a private person) is not stored at all. A page that was read but did not settle anything is not stored either.
--
-- Like the tables of 0015, deliberately without links to `users` or `messages`: a deleted or edited message takes its claims with it (ingest/loader.py), an erased person takes theirs
-- (privacy.erase_person), a deleted debate takes everything (ON DELETE CASCADE).

-- The queue of messages to read: `read_at` is null until the message was read for claims (or decided not to be). A message that is edited becomes unread again.
ALTER TABLE debate_messages ADD COLUMN IF NOT EXISTS read_at timestamptz;
CREATE INDEX IF NOT EXISTS debate_messages_unread_idx ON debate_messages (message_id) WHERE read_at IS NULL;

CREATE TABLE IF NOT EXISTS debate_claims (
    id         bigserial PRIMARY KEY,
    debate_id  bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    message_id bigint NOT NULL,
    author_id  bigint NOT NULL,
    claim      text   NOT NULL CHECK (char_length(claim) BETWEEN 3 AND 500),   -- restated alone, neutral, with its figures and its period
    said       text   NOT NULL CHECK (char_length(said) BETWEEN 3 AND 500),    -- the words of the message that carry it (checked to be in the message)
    -- confirmed / contradicted: a trusted source AND a verified quotation, the same bar both ways. partly: true for another period, or incomplete.
    -- disputed: trusted sources disagree. unverifiable: nothing trusted settles it (or it could not be checked: `reason`).
    verdict    text   NOT NULL CHECK (verdict IN ('confirmed', 'contradicted', 'partly', 'disputed', 'unverifiable')),
    reason     text   CHECK (reason IN ('no_source', 'error')),
    period     text   CHECK (char_length(period) <= 100),                      -- the date or period of the figure that the sources give
    queries    smallint NOT NULL DEFAULT 0,                                    -- what was done on the Internet for this claim: counts only
    pages      smallint NOT NULL DEFAULT 0,
    model      text,
    checked_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS debate_claims_debate_idx ON debate_claims (debate_id, checked_at);
CREATE INDEX IF NOT EXISTS debate_claims_message_idx ON debate_claims (message_id);
CREATE INDEX IF NOT EXISTS debate_claims_author_idx ON debate_claims (author_id);

CREATE TABLE IF NOT EXISTS debate_sources (
    id          bigserial PRIMARY KEY,
    claim_id    bigint NOT NULL REFERENCES debate_claims (id) ON DELETE CASCADE,
    url         text   NOT NULL CHECK (char_length(url) <= 2000),              -- the exact address that was read: what people click
    title       text   CHECK (char_length(title) <= 300),
    tier        text   NOT NULL CHECK (tier IN ('official', 'checker')),       -- only sources that may ground a verdict are kept (debate/trust.py)
    stance      text   NOT NULL CHECK (stance IN ('supports', 'contradicts', 'partly')),
    quote       text   NOT NULL CHECK (char_length(quote) BETWEEN 25 AND 400), -- word for word on the page: verified by the program, not claimed by the model
    page_period text   CHECK (char_length(page_period) <= 100),
    via         text,                                                          -- which search service returned it
    sha256      text   NOT NULL,                                               -- of the page as read, to tell it from a page that changed since
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS debate_sources_claim_idx ON debate_sources (claim_id);
