-- The verdict of a debate (docs/regles-du-bot.md, « Verdict ») : after it ends, everybody who took a position (participants AND witnesses) may rate each participant out of 10, never themselves,
-- during a window. The final score of a participant is half the average of these ratings and half Dindon's own analysis (sources, logic, faithfulness to their roles), computed
-- from the database with fixed rules. Like the other debate tables: no foreign key towards `users` (privacy.py cleans them by name).
ALTER TABLE debates ADD COLUMN IF NOT EXISTS rating_ends_at timestamptz;      -- null: nothing to rate (nobody took part, or the debate failed); else the end of the voting window
ALTER TABLE debates ADD COLUMN IF NOT EXISTS results_message_id bigint;       -- the message of the verdict (0: given up)

CREATE TABLE IF NOT EXISTS debate_ratings (
    debate_id bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    rater_id  bigint NOT NULL,
    target_id bigint NOT NULL,
    score     numeric(4, 2) NOT NULL CHECK (score BETWEEN 0 AND 10),
    rated_at  timestamptz NOT NULL,
    PRIMARY KEY (debate_id, rater_id, target_id),
    CHECK (rater_id <> target_id)
);
CREATE INDEX IF NOT EXISTS debate_ratings_target_idx ON debate_ratings (target_id);

CREATE TABLE IF NOT EXISTS debate_results (
    debate_id   bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    user_id     bigint NOT NULL,
    vote_score  numeric(4, 2),                  -- the average of the ratings received (null: nobody rated this person)
    vote_count  integer NOT NULL DEFAULT 0,
    ai_score    numeric(4, 2) NOT NULL,         -- Dindon's analysis, out of 10
    ai_detail   jsonb NOT NULL,                 -- the three parts, each out of 10, and the figures they come from
    final_score numeric(4, 2) NOT NULL,         -- half the votes, half the analysis (the analysis alone, if nobody rated anybody)
    winner      boolean NOT NULL DEFAULT false,
    PRIMARY KEY (debate_id, user_id)
);
CREATE INDEX IF NOT EXISTS debate_results_person_idx ON debate_results (user_id);
