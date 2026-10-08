ALTER TABLE debate_polls ADD COLUMN answer_ids jsonb;
CREATE TABLE debate_welcomes (
    debate_id bigint REFERENCES debates(id) ON DELETE CASCADE,
    user_id bigint NOT NULL,
    PRIMARY KEY (debate_id, user_id)
);
CREATE TABLE debate_poll_votes (
    debate_id bigint REFERENCES debates(id) ON DELETE CASCADE,
    user_id bigint NOT NULL,
    answer_id integer NOT NULL,
    position_id bigint REFERENCES debate_positions(id) ON DELETE CASCADE,
    PRIMARY KEY (debate_id, user_id)
);
-- Existing button messages are replaced when next published.
UPDATE debate_polls SET dirty = true, revision = revision + 1;
