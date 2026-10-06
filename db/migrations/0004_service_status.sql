-- What the other processes say about themselves, so that the interface can show whether they are well. Only counts and states, never
-- a message, a name or a token. One row per service ('bot'), written by the service itself every half minute.
CREATE TABLE IF NOT EXISTS service_status (
    name       text PRIMARY KEY,
    updated_at timestamptz NOT NULL DEFAULT now(),
    data       jsonb NOT NULL DEFAULT '{}'
);
