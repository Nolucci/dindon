-- One poll per debate; answers use debate_positions, shared with the debate buttons.
CREATE TABLE debate_polls (
    debate_id bigint PRIMARY KEY REFERENCES debates(id) ON DELETE CASCADE,
    channel_id bigint,
    message_id bigint,
    question text NOT NULL,
    description text,
    proposition_id bigint REFERENCES propositions(id) ON DELETE SET NULL,
    dirty boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 0
);
CREATE INDEX debate_polls_pending_idx ON debate_polls(debate_id) WHERE dirty;

CREATE FUNCTION mark_debate_poll_dirty() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE debate_polls SET dirty = true, revision = revision + 1 WHERE debate_id = COALESCE(NEW.debate_id, OLD.debate_id);
    RETURN NULL;
END
$$;
CREATE TRIGGER debate_poll_answers AFTER INSERT OR UPDATE OR DELETE ON debate_positions
FOR EACH ROW EXECUTE FUNCTION mark_debate_poll_dirty();

CREATE OR REPLACE FUNCTION refresh_person_axis_scores(
    p_guild bigint DEFAULT NULL,
    p_prior numeric DEFAULT NULL,
    p_floor numeric DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_prior numeric := COALESCE(p_prior, (SELECT value FROM scoring_settings WHERE key = 'prior_weight'), 1);
    v_floor numeric := COALESCE(p_floor, (SELECT value FROM scoring_settings WHERE key = 'uncertainty_floor'), 0.35);
    v_count integer;
BEGIN
    WITH positions AS (
        SELECT guild_id, user_id, proposition_id, stance, confidence, stated_at FROM current_stances
        UNION ALL
        SELECT d.guild_id, v.user_id, q.proposition_id,
               CASE v.position WHEN 'for' THEN 1 WHEN 'against' THEN -1 END, 1::real, v.chosen_at
        FROM debates d JOIN debate_polls q ON q.debate_id = d.id
        JOIN LATERAL (SELECT DISTINCT ON (user_id) user_id, position, chosen_at
                      FROM debate_positions WHERE debate_id = d.id ORDER BY user_id, id DESC) v ON true
        WHERE d.status IN ('open', 'closed') AND d.close_reason IS DISTINCT FROM 'failed'
          AND v.position IN ('for', 'against')
          AND EXISTS (SELECT 1 FROM users u WHERE u.id = v.user_id)
          AND EXISTS (SELECT 1 FROM guilds g WHERE g.id = d.guild_id)
    ), latest AS (
        SELECT DISTINCT ON (guild_id, user_id, proposition_id) * FROM positions
        ORDER BY guild_id, user_id, proposition_id, stated_at DESC
    ), points AS (
        SELECT s.guild_id, s.user_id, pa.axis_id,
               (s.stance * sign(pa.loading))::numeric        AS x,   -- -1 .. +1 on the axis
               (s.confidence * abs(pa.loading))::numeric     AS w
        FROM latest s
        JOIN propositions p      ON p.id = s.proposition_id AND p.status NOT IN ('rejected', 'merged')
        JOIN proposition_axis pa ON pa.proposition_id = s.proposition_id AND pa.loading <> 0
             AND (pa.is_validated OR COALESCE((SELECT value FROM scoring_settings WHERE key = 'only_validated_loadings'), 0) = 0)
        JOIN axes a              ON a.id = pa.axis_id AND a.is_active
        WHERE p_guild IS NULL OR s.guild_id = p_guild
    ), agg AS (
        SELECT guild_id, user_id, axis_id,
               sum(w) AS wsum, sum(w * x) AS wx, sum(w * x * x) AS wxx, count(*) AS n
        FROM points
        WHERE w > 0
        GROUP BY guild_id, user_id, axis_id
    ), scored AS (
        SELECT guild_id, user_id, axis_id, wsum, n,
               wx / (wsum + v_prior) AS score,
               GREATEST(wxx / wsum - power(wx / wsum, 2), 0) AS variance
        FROM agg
    ), upserted AS (
        INSERT INTO person_axis_scores (guild_id, user_id, axis_id, score, uncertainty, evidence_weight, n_propositions, computed_at)
        SELECT guild_id, user_id, axis_id,
               round(score, 3),
               round(LEAST(1.96 * GREATEST(sqrt(variance), v_floor) / sqrt(wsum + v_prior), 2), 3),
               round(wsum, 3), n, now()
        FROM scored
        ON CONFLICT (guild_id, user_id, axis_id) DO UPDATE SET
            score = excluded.score, uncertainty = excluded.uncertainty,
            evidence_weight = excluded.evidence_weight, n_propositions = excluded.n_propositions,
            computed_at = excluded.computed_at
        RETURNING 1
    ), removed AS (
        -- A score that no longer has any evidence behind it (claims rejected since) goes away
        DELETE FROM person_axis_scores ps
        WHERE (p_guild IS NULL OR ps.guild_id = p_guild)
          AND NOT EXISTS (
              SELECT 1 FROM scored sc
              WHERE sc.guild_id = ps.guild_id AND sc.user_id = ps.user_id AND sc.axis_id = ps.axis_id
          )
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM upserted;

    RETURN v_count;
END
$$;
