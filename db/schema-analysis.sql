-- Analysis layer: what is derived from the messages. It sits on top of schema.sql.
--
--   topics         ideas that come up, found automatically first, refined by hand afterwards
--   axes           the scales that people are placed on, each with a precise definition
--   ideologies     named positions (communist, eurosceptic...) and what they imply on the axes
--   role_rules     which server roles are ideologies, and which ones are not (staff, age...)
--   propositions   statements that people can agree or disagree with, and how they weigh on the axes
--   claims         what a person said, with the messages that prove it
--   person_axis_scores   where a person stands on each axis, with its uncertainty
--
-- Nothing is classified without evidence: a score is computed from claims, and every claim points
-- to the messages it comes from. The seed data (axes, ideologies, role rules) is in seed-axes.sql.

-- ---------------------------------------------------------------------------------------------
-- Settings of the computation
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scoring_settings (
    key         text PRIMARY KEY,
    value       numeric NOT NULL,
    description text NOT NULL
);

-- ---------------------------------------------------------------------------------------------
-- Topics: found automatically first (independently of people), then refined
-- ---------------------------------------------------------------------------------------------

-- One run of the automatic discovery of topics
CREATE TABLE IF NOT EXISTS topic_runs (
    id            bigserial PRIMARY KEY,
    guild_id      bigint REFERENCES guilds (id) ON DELETE CASCADE,
    method        text   NOT NULL,                  -- e.g. 'embeddings clustering + model naming'
    model         text,
    parameters    jsonb,
    message_count integer,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topics (
    id           bigserial PRIMARY KEY,
    guild_id     bigint REFERENCES guilds (id) ON DELETE CASCADE,   -- NULL: shared by all servers
    parent_id    bigint REFERENCES topics (id) ON DELETE SET NULL,
    label        text   NOT NULL,
    description  text,
    keywords     text[] NOT NULL DEFAULT '{}',
    origin       text   NOT NULL CHECK (origin IN ('discovered', 'manual')),
    -- proposed: just found, validated: confirmed by you, merged: it is the same as another one
    status       text   NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'validated', 'merged', 'rejected')),
    merged_into  bigint REFERENCES topics (id) ON DELETE SET NULL,
    run_id       bigint REFERENCES topic_runs (id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    validated_at timestamptz
);
CREATE INDEX IF NOT EXISTS topics_guild_idx ON topics (guild_id, status);

-- ---------------------------------------------------------------------------------------------
-- Axes: clear scales, from -1 to +1
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS axes (
    id            smallserial PRIMARY KEY,
    code          text    NOT NULL UNIQUE,
    name          text    NOT NULL,
    question      text    NOT NULL,                  -- the question that the axis answers
    negative_pole text    NOT NULL,                  -- what -1 means (the left pole of the 12 Axes)
    positive_pole text    NOT NULL,                  -- what +1 means (the right pole of the 12 Axes)
    definition    text    NOT NULL,                  -- what the axis covers
    excludes      text,                              -- what it does not cover (it belongs to another axis)
    position      integer NOT NULL,                  -- display order
    -- Only active axes are scored and checked. The 12 axes come from the "12 Axes" model
    -- (https://12axes.vercel.app); the others are extensions that cover what it does not.
    is_active     boolean NOT NULL DEFAULT true,
    origin        text    NOT NULL DEFAULT 'custom' CHECK (origin IN ('12axes', 'custom')),
    version       integer NOT NULL DEFAULT 1
);
ALTER TABLE axes ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'custom' CHECK (origin IN ('12axes', 'custom'));

-- Reference points, so that a score has a meaning: what -1, 0 and +1 look like on each axis
CREATE TABLE IF NOT EXISTS axis_anchors (
    axis_id             smallint NOT NULL REFERENCES axes (id) ON DELETE CASCADE,
    value               numeric(3, 2) NOT NULL CHECK (value BETWEEN -1 AND 1),
    description         text NOT NULL,
    PRIMARY KEY (axis_id, value)
);

-- ---------------------------------------------------------------------------------------------
-- Ideologies and what they imply on the axes
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ideologies (
    id           smallserial PRIMARY KEY,
    code         text NOT NULL UNIQUE,
    name         text NOT NULL,
    -- famille: a whole political family; position: a stance on one or two axes; valeur: an attitude
    -- or a value, which only implies something weak
    kind         text NOT NULL CHECK (kind IN ('famille', 'position', 'valeur')),
    description  text,
    -- Where it sits on the political spectrum, with the vocabulary of the 12 Axes. Only for families.
    spectrum     text CHECK (spectrum IN ('radical_left', 'left', 'center', 'right', 'far_right', 'third_position', 'libertarian', 'anarchist')),
    -- The ranges below are a proposal until you have reviewed them
    is_validated boolean NOT NULL DEFAULT false
);
ALTER TABLE ideologies ADD COLUMN IF NOT EXISTS spectrum text CHECK (spectrum IN ('radical_left', 'left', 'center', 'right', 'far_right', 'third_position', 'libertarian', 'anarchist'));

-- Where someone who claims an ideology can be expected to stand on an axis. An axis without a
-- range is not constrained by the ideology.
CREATE TABLE IF NOT EXISTS ideology_axis_ranges (
    ideology_id smallint NOT NULL REFERENCES ideologies (id) ON DELETE CASCADE,
    axis_id     smallint NOT NULL REFERENCES axes (id)       ON DELETE CASCADE,
    min_score   numeric(3, 2) NOT NULL CHECK (min_score BETWEEN -1 AND 1),
    max_score   numeric(3, 2) NOT NULL CHECK (max_score BETWEEN -1 AND 1),
    PRIMARY KEY (ideology_id, axis_id),
    CHECK (min_score <= max_score)
);

-- ---------------------------------------------------------------------------------------------
-- Roles that people give themselves
-- ---------------------------------------------------------------------------------------------

-- Server roles are named freely, so they are recognized by name, whatever the server.
-- Only 'ideologie' roles are used to check what people say. Roles of age or gender are recognized
-- so that they can be left out, not to be analyzed.
CREATE TABLE IF NOT EXISTS role_rules (
    id          serial PRIMARY KEY,
    match_type  text NOT NULL CHECK (match_type IN ('exact', 'regex')),
    pattern     text NOT NULL,                     -- lowercase, without accents (see normalize_role_name)
    kind        text NOT NULL CHECK (kind IN ('ideologie', 'staff', 'notification', 'age', 'genre', 'base', 'separateur', 'autre')),
    ideology_id smallint REFERENCES ideologies (id) ON DELETE SET NULL,
    UNIQUE (match_type, pattern)
);

CREATE OR REPLACE FUNCTION normalize_role_name(name text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT lower(unaccent(btrim(regexp_replace(name, '\s+', ' ', 'g'))))
$$;

-- Every role with what it is. Exact names win over patterns.
CREATE OR REPLACE VIEW classified_roles AS
SELECT r.id AS role_id,
       r.guild_id,
       r.name,
       COALESCE(rule.kind, 'autre') AS kind,
       rule.ideology_id
FROM roles r
LEFT JOIN LATERAL (
    SELECT rr.kind, rr.ideology_id
    FROM role_rules rr
    WHERE (rr.match_type = 'exact' AND normalize_role_name(r.name) = rr.pattern)
       OR (rr.match_type = 'regex' AND normalize_role_name(r.name) ~ rr.pattern)
    ORDER BY (rr.match_type = 'exact') DESC, rr.id
    LIMIT 1
) rule ON true;

-- The ideologies that people say they have, from the roles that they have given themselves
CREATE OR REPLACE VIEW claimed_ideologies AS
SELECT mr.guild_id, mr.user_id, cr.ideology_id, cr.role_id, cr.name AS role_name
FROM member_roles mr
JOIN classified_roles cr ON cr.role_id = mr.role_id
WHERE cr.kind = 'ideologie' AND cr.ideology_id IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- Propositions: what people can agree or disagree with
-- ---------------------------------------------------------------------------------------------

-- Shared by all servers. "Il faut augmenter le SMIC" is a proposition: two people who talk about
-- it in different words are linked to the same one, so that they can be compared.
CREATE TABLE IF NOT EXISTS propositions (
    id          bigserial PRIMARY KEY,
    text        text   NOT NULL,
    topic_id    bigint REFERENCES topics (id) ON DELETE SET NULL,
    status      text   NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'validated', 'merged', 'rejected')),
    merged_into bigint REFERENCES propositions (id) ON DELETE SET NULL,
    created_by  text,                               -- the model or the person that created it
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS propositions_topic_idx ON propositions (topic_id);

-- How agreeing with a proposition moves someone on an axis: +1 means that it moves them toward the
-- positive pole, -1 toward the negative pole, 0 that it doesn't matter. Proposed by the model once
-- per proposition, and confirmed by you.
CREATE TABLE IF NOT EXISTS proposition_axis (
    proposition_id bigint   NOT NULL REFERENCES propositions (id) ON DELETE CASCADE,
    axis_id        smallint NOT NULL REFERENCES axes (id) ON DELETE CASCADE,
    loading        numeric(3, 2) NOT NULL CHECK (loading BETWEEN -1 AND 1),
    confidence     real,
    is_validated   boolean NOT NULL DEFAULT false,
    PRIMARY KEY (proposition_id, axis_id)
);

-- ---------------------------------------------------------------------------------------------
-- Claims: what a person said, and the proof
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS claims (
    id             bigserial PRIMARY KEY,
    guild_id       bigint NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    user_id        bigint NOT NULL REFERENCES users (id)  ON DELETE CASCADE,
    proposition_id bigint REFERENCES propositions (id) ON DELETE SET NULL,
    kind           text   NOT NULL CHECK (kind IN ('opinion', 'proposition', 'fait', 'question', 'attaque', 'soutien', 'humour')),
    text           text   NOT NULL,                  -- the claim, in clear French
    -- Toward the proposition: -1 against, 0 nuanced, +1 for. Empty if it is not about a proposition.
    stance         smallint CHECK (stance IN (-1, 0, 1)),
    confidence     real   NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    stated_at      timestamptz NOT NULL,
    model          text   NOT NULL,
    prompt_version text   NOT NULL,
    -- auto: found by the model, confirmed or rejected: reviewed by you
    review_status  text   NOT NULL DEFAULT 'auto' CHECK (review_status IN ('auto', 'confirmed', 'rejected')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS claims_user_idx        ON claims (user_id, guild_id, stated_at DESC);
CREATE INDEX IF NOT EXISTS claims_proposition_idx ON claims (proposition_id, user_id);

-- The messages that prove a claim, with the quote
CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id   bigint NOT NULL REFERENCES claims (id)   ON DELETE CASCADE,
    message_id bigint NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    quote      text,
    PRIMARY KEY (claim_id, message_id)
);
CREATE INDEX IF NOT EXISTS claim_evidence_message_idx ON claim_evidence (message_id);

-- A discussion, rebuilt from the messages: the unit that the model reads, so that it has context
CREATE TABLE IF NOT EXISTS conversations (
    id            bigserial PRIMARY KEY,
    channel_id    bigint NOT NULL REFERENCES channels (id) ON DELETE CASCADE,
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz NOT NULL,
    message_count integer NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_channel_idx ON conversations (channel_id, started_at);

CREATE TABLE IF NOT EXISTS conversation_messages (
    conversation_id bigint NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    message_id      bigint NOT NULL REFERENCES messages (id)      ON DELETE CASCADE,
    PRIMARY KEY (conversation_id, message_id)
);
CREATE INDEX IF NOT EXISTS conversation_messages_message_idx ON conversation_messages (message_id);

-- ---------------------------------------------------------------------------------------------
-- Positions: where a person stands on each axis
-- ---------------------------------------------------------------------------------------------

-- What a person thinks now: the latest claim of each person about each proposition. People change
-- their minds, so older claims stay in 'claims' as a history.
CREATE OR REPLACE VIEW current_stances AS
SELECT DISTINCT ON (c.guild_id, c.user_id, c.proposition_id)
       c.guild_id, c.user_id, c.proposition_id, c.stance, c.confidence, c.stated_at, c.id AS claim_id
FROM claims c
WHERE c.proposition_id IS NOT NULL
  AND c.stance IS NOT NULL
  AND c.review_status <> 'rejected'
ORDER BY c.guild_id, c.user_id, c.proposition_id, c.stated_at DESC, c.id DESC;

CREATE TABLE IF NOT EXISTS person_axis_scores (
    guild_id        bigint   NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    user_id         bigint   NOT NULL REFERENCES users (id)  ON DELETE CASCADE,
    axis_id         smallint NOT NULL REFERENCES axes (id)   ON DELETE CASCADE,
    score           numeric(4, 3) NOT NULL CHECK (score BETWEEN -1 AND 1),
    uncertainty     numeric(4, 3) NOT NULL,          -- half-width of the interval (about 95%)
    evidence_weight numeric NOT NULL,                -- how much evidence there is (confidence-weighted)
    n_propositions  integer NOT NULL,
    computed_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id, axis_id)
);

-- Computes the scores. Each position counts toward an axis by its confidence and by how much the
-- proposition weighs on that axis. The score is the weighted mean, pulled toward 0 by a small
-- amount of "doubt" (p_prior), so that one single remark never gives a firm score. The uncertainty
-- shrinks as the evidence grows, and can never be below p_floor, which stands for the errors that
-- an analysis cannot avoid (sarcasm, quotes...).
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
    WITH points AS (
        SELECT s.guild_id, s.user_id, pa.axis_id,
               (s.stance * sign(pa.loading))::numeric        AS x,   -- -1 .. +1 on the axis
               (s.confidence * abs(pa.loading))::numeric     AS w
        FROM current_stances s
        JOIN propositions p      ON p.id = s.proposition_id AND p.status NOT IN ('rejected', 'merged')
        JOIN proposition_axis pa ON pa.proposition_id = s.proposition_id AND pa.loading <> 0
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

-- ---------------------------------------------------------------------------------------------
-- Checking what people say against what they claim to be
-- ---------------------------------------------------------------------------------------------

-- For each ideology that a person claims (through a role) and each active axis that it constrains:
--   insufficient  not enough evidence yet to say anything
--   confirmed     the whole uncertainty interval (limited to -1..+1) is inside the expected range
--   compatible    the interval overlaps the range
--   incompatible  the whole interval is outside the range: what the person says does not match
CREATE OR REPLACE VIEW ideology_concordance AS
SELECT ci.guild_id, ci.user_id, ci.ideology_id, ci.role_id, ci.role_name,
       r.axis_id, r.min_score, r.max_score,
       s.score, s.uncertainty, s.evidence_weight, s.n_propositions,
       CASE
           WHEN s.score IS NULL
             OR s.n_propositions < (SELECT value FROM scoring_settings WHERE key = 'min_propositions')
             OR s.evidence_weight < (SELECT value FROM scoring_settings WHERE key = 'min_evidence_weight')
               THEN 'insufficient'
           WHEN LEAST(s.score + s.uncertainty, 1) < r.min_score OR GREATEST(s.score - s.uncertainty, -1) > r.max_score
               THEN 'incompatible'
           WHEN GREATEST(s.score - s.uncertainty, -1) >= r.min_score AND LEAST(s.score + s.uncertainty, 1) <= r.max_score
               THEN 'confirmed'
           ELSE 'compatible'
       END AS verdict
FROM claimed_ideologies ci
JOIN ideology_axis_ranges r ON r.ideology_id = ci.ideology_id
JOIN axes ax ON ax.id = r.axis_id AND ax.is_active
LEFT JOIN person_axis_scores s
       ON s.guild_id = ci.guild_id AND s.user_id = ci.user_id AND s.axis_id = r.axis_id;

-- One line per claimed ideology: does what the person says match it?
--   discordant        at least one axis is incompatible
--   concordant        nothing incompatible, and at least one axis can be assessed
--   not_verifiable    nothing can be assessed yet (not enough evidence, or no axis for this ideology)
CREATE OR REPLACE VIEW claimed_ideology_summary AS
SELECT ci.guild_id, ci.user_id, ci.ideology_id, ci.role_id, ci.role_name,
       count(c.axis_id) FILTER (WHERE c.verdict = 'confirmed')    AS confirmed_axes,
       count(c.axis_id) FILTER (WHERE c.verdict = 'compatible')   AS compatible_axes,
       count(c.axis_id) FILTER (WHERE c.verdict = 'incompatible') AS incompatible_axes,
       count(c.axis_id) FILTER (WHERE c.verdict = 'insufficient') AS insufficient_axes,
       CASE
           WHEN count(c.axis_id) FILTER (WHERE c.verdict = 'incompatible') > 0 THEN 'discordant'
           WHEN count(c.axis_id) FILTER (WHERE c.verdict IN ('confirmed', 'compatible')) > 0 THEN 'concordant'
           ELSE 'not_verifiable'
       END AS verdict
FROM claimed_ideologies ci
LEFT JOIN ideology_concordance c
       ON c.guild_id = ci.guild_id AND c.user_id = ci.user_id AND c.ideology_id = ci.ideology_id
GROUP BY ci.guild_id, ci.user_id, ci.ideology_id, ci.role_id, ci.role_name;

-- Ideologies that a person claims but that contradict each other: they expect opposite positions
-- on the same axis (for example "Européiste" and "Eurosceptique"). Roles are often ticked lightly,
-- so this says something about the roles themselves, whatever the person says.
CREATE OR REPLACE VIEW claimed_ideology_conflicts AS
SELECT a.guild_id, a.user_id, a.ideology_id AS ideology_a, b.ideology_id AS ideology_b, ra.axis_id
FROM claimed_ideologies a
JOIN claimed_ideologies b
  ON b.guild_id = a.guild_id AND b.user_id = a.user_id AND a.ideology_id < b.ideology_id
JOIN ideology_axis_ranges ra ON ra.ideology_id = a.ideology_id
JOIN ideology_axis_ranges rb ON rb.ideology_id = b.ideology_id AND rb.axis_id = ra.axis_id
WHERE ra.max_score < rb.min_score OR rb.max_score < ra.min_score;

-- ---------------------------------------------------------------------------------------------
-- The graph of interactions, and the queue of work
-- ---------------------------------------------------------------------------------------------

-- Links between people: one row per pair and per kind of link (reply, mention, reaction, and
-- later agreement or disagreement), kept up to date as messages arrive. 'weight' gives more
-- importance to recent exchanges.
CREATE TABLE IF NOT EXISTS edges (
    guild_id     bigint NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    from_user_id bigint NOT NULL REFERENCES users (id)  ON DELETE CASCADE,
    to_user_id   bigint NOT NULL REFERENCES users (id)  ON DELETE CASCADE,
    kind         text   NOT NULL,
    weight       double precision NOT NULL DEFAULT 0,
    n            integer NOT NULL DEFAULT 0,
    last_at      timestamptz,
    PRIMARY KEY (guild_id, from_user_id, to_user_id, kind)
);
CREATE INDEX IF NOT EXISTS edges_to_idx ON edges (guild_id, to_user_id);

-- Work for the analysis workers. A worker takes the next job with FOR UPDATE SKIP LOCKED, so that
-- several of them can work at the same time without waiting for each other.
CREATE TABLE IF NOT EXISTS jobs (
    id          bigserial PRIMARY KEY,
    kind        text   NOT NULL,                     -- e.g. 'conversation', 'embedding'
    subject_id  bigint NOT NULL,                     -- what to work on (e.g. a conversation)
    priority    integer NOT NULL DEFAULT 0,          -- the higher, the sooner
    attempts    integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_ready_idx ON jobs (priority DESC, id);
