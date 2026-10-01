-- The graph of interactions: how fast old exchanges fade, how to rebuild the links from the messages,
-- and an index for questions about a period.

-- Half-life of the weight of a link, in days: an exchange of this age counts for half of a new one.
INSERT INTO scoring_settings (key, value, description) VALUES
    ('edge_half_life_days', 90, 'Half-life of the weight of the links between people, in days. After changing it, run: SELECT rebuild_edges()')
ON CONFLICT (key) DO NOTHING;

-- Questions such as "what happened between these two dates" in a whole server
CREATE INDEX IF NOT EXISTS messages_sent_idx ON messages (sent_at);

-- Weight of a link = the sum over its exchanges of 0.5 ^ (age / half-life). It is stored "as of
-- last_at" (the date of the latest exchange), which is what makes it possible to add an exchange
-- without looking at the others: weight_now = weight * 0.5 ^ ((now - last_at) / half-life).
-- Links are kept for every pair of different people, bots included (the API leaves bots out).
--
-- Rebuilds the links of one server (or of all) from the messages. The ingestion keeps `edges` up to
-- date by itself, one batch at a time; this does the same from zero, and the tests check that both
-- give the same result.
CREATE OR REPLACE FUNCTION rebuild_edges(p_guild bigint DEFAULT NULL) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_half_life double precision :=
        86400 * COALESCE((SELECT value FROM scoring_settings WHERE key = 'edge_half_life_days'), 90)::double precision;
    v_count integer;
BEGIN
    DELETE FROM edges WHERE p_guild IS NULL OR guild_id = p_guild;
    INSERT INTO edges (guild_id, from_user_id, to_user_id, kind, weight, n, last_at)
    SELECT guild_id, from_user_id, to_user_id, kind,
           sum(power(0.5, extract(epoch FROM (last_at - sent_at)) / v_half_life)),
           count(*), last_at
    FROM (
        SELECT i.*, max(i.sent_at) OVER (PARTITION BY i.guild_id, i.from_user_id, i.to_user_id, i.kind) AS last_at
        FROM interactions i
        WHERE i.from_user_id <> i.to_user_id AND (p_guild IS NULL OR i.guild_id = p_guild)
    ) events
    GROUP BY guild_id, from_user_id, to_user_id, kind, last_at;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$$;
