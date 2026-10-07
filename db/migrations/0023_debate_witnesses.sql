-- Witnesses and the end of a debate by the camps (docs/regles-du-bot.md): a person takes part in a debate only by taking a position (for / not sure / against). A fourth button, « Témoin »,
-- is for those who only watch: they cannot end the debate, and their messages are kept (marked `witness`) for later analyses but are not read for the debate.
-- A debate ends when the camps decide it: the participants press the end button, and it closes once most of the smallest camp asked for it, or when one of the two camps has emptied.
ALTER TABLE debate_positions DROP CONSTRAINT IF EXISTS debate_positions_position_check;
ALTER TABLE debate_positions ADD CONSTRAINT debate_positions_position_check CHECK (position IN ('for', 'unsure', 'against', 'witness'));

ALTER TABLE debate_messages ADD COLUMN IF NOT EXISTS witness boolean NOT NULL DEFAULT false;     -- written by somebody who was not a participant (a witness, or no position yet) at that moment

ALTER TABLE debates DROP CONSTRAINT IF EXISTS debates_close_reason_check;
ALTER TABLE debates ADD CONSTRAINT debates_close_reason_check
    CHECK (close_reason IN ('ended', 'silence', 'no_participants', 'failed', 'stopped', 'tie', 'no_vote', 'max_rounds', 'agreed', 'one_sided'));

-- The participants who asked to end the debate (one row each; taken back when they change camp or become witnesses: only the current camps count). No foreign key towards `users` (privacy.py).
CREATE TABLE IF NOT EXISTS debate_end_votes (
    debate_id bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    user_id   bigint NOT NULL,
    voted_at  timestamptz NOT NULL,
    PRIMARY KEY (debate_id, user_id)
);
CREATE INDEX IF NOT EXISTS debate_end_votes_person_idx ON debate_end_votes (user_id);
