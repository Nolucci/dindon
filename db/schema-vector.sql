-- Optional: semantic search (finding messages by meaning rather than by words), using embeddings
-- that are computed locally. Requires the pgvector extension, which the Docker image includes.
--
-- The size of the vector depends on the embedding model: 1024 is for models such as bge-m3 or
-- multilingual-e5-large. Change it to match the model that you use.
--
-- Embeddings are big (measured: about 5 KB per vector, plus about 8 KB for its index entry), so
-- they are best computed for messages that are worth it, or for groups of messages, rather than
-- for every single one. 'halfvec(1024)' halves the size, at a small cost in precision.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS message_embeddings (
    message_id bigint NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    model      text   NOT NULL,
    embedding  vector(1024) NOT NULL,
    PRIMARY KEY (message_id, model)
);

-- Embeddings of the claims and propositions: used to link a new claim to the proposition that
-- it is about (the nearest one), and to find topics.
CREATE TABLE IF NOT EXISTS proposition_embeddings (
    proposition_id bigint NOT NULL REFERENCES propositions (id) ON DELETE CASCADE,
    model          text   NOT NULL,
    embedding      vector(1024) NOT NULL,
    PRIMARY KEY (proposition_id, model)
);

CREATE TABLE IF NOT EXISTS claim_embeddings (
    claim_id  bigint NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    model     text   NOT NULL,
    embedding vector(1024) NOT NULL,
    PRIMARY KEY (claim_id, model)
);

-- Create the index AFTER the embeddings have been loaded: building it once is much faster than
-- updating it for every insert (measured: 30 000 inserts with the index in place took 2 minutes).
--
--   CREATE INDEX message_embeddings_idx ON message_embeddings USING hnsw (embedding vector_cosine_ops);
--
-- Nearest messages to a given one (about 3 ms with the index):
--
--   SELECT message_id FROM message_embeddings
--   ORDER BY embedding <=> (SELECT embedding FROM message_embeddings WHERE message_id = 123 AND model = 'm')
--   LIMIT 5;
