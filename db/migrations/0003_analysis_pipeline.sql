-- The first stages of the analysis (see docs/ANALYSE.md): conversations rebuilt from the messages, a triage of what is worth reading,
-- the vector of each conversation, and the topics that are discovered from them (without any regard to who wrote what).

-- What a conversation is made of, kept so that nothing has to be counted again
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS first_message_id  bigint;                      -- the key of a conversation: a message is in one only
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS participants      integer NOT NULL DEFAULT 0;   -- people (not bots) who wrote in it
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS substantive_count integer NOT NULL DEFAULT 0;   -- messages that say something (see analysis_substantive)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS substantive_chars integer NOT NULL DEFAULT 0;   -- letters in those messages
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS importance        real    NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS kept              boolean NOT NULL DEFAULT false;  -- worth the models' time
CREATE UNIQUE INDEX IF NOT EXISTS conversations_first_message_idx ON conversations (first_message_id) WHERE first_message_id IS NOT NULL;

-- The text of a message as the analysis reads it: without links, custom emoji and mentions (a mention is a person, and the first
-- stages do not look at people)
CREATE OR REPLACE FUNCTION analysis_clean_text(content text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT btrim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(content,
           'https?://\S+', ' ', 'g'), '<a?:\w+:\d+>', ' ', 'g'), '@\S+', ' ', 'g'), '\s+', ' ', 'g'))
$$;

CREATE OR REPLACE FUNCTION analysis_letters(content text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
    SELECT length(regexp_replace(analysis_clean_text(content), '[^[:alpha:]]', '', 'g'))
$$;

-- A message that says something: at least 15 letters once the links, the emoji and the mentions are gone. "mdr", "oui", "+1" and
-- a link alone are not; "il faut taxer les riches" is.
CREATE OR REPLACE FUNCTION analysis_substantive(content text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT analysis_letters(content) >= 15
$$;

-- One vector per conversation and per model (1024 numbers: the size that schema-vector.sql expects)
CREATE TABLE IF NOT EXISTS conversation_embeddings (
    conversation_id bigint NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    model           text   NOT NULL,
    embedding       vector(1024) NOT NULL,
    PRIMARY KEY (conversation_id, model)
);

-- The topic of each conversation, for one run of the discovery: the closest one, with how close
CREATE TABLE IF NOT EXISTS topic_assignments (
    run_id          bigint NOT NULL REFERENCES topic_runs (id)     ON DELETE CASCADE,
    conversation_id bigint NOT NULL REFERENCES conversations (id)  ON DELETE CASCADE,
    topic_id        bigint NOT NULL REFERENCES topics (id)         ON DELETE CASCADE,
    similarity      real   NOT NULL,
    PRIMARY KEY (run_id, conversation_id)
);
CREATE INDEX IF NOT EXISTS topic_assignments_topic_idx ON topic_assignments (topic_id, similarity DESC);
