-- A debate no longer has a time limit, periods or a vote to go on (docs/DEBAT.md): it is opened from a popup where the person chooses its parameters, it ends with a button or after
-- a silence, and it can take place in a thread or in the channel itself.
--
-- Nothing real ran on the tables of 0015-0017 yet (they only ever held test data), so what is dropped here is dropped without a copy.
UPDATE debates SET status = 'open' WHERE status = 'voting';
ALTER TABLE debates DROP CONSTRAINT IF EXISTS debates_status_check;
ALTER TABLE debates ADD CONSTRAINT debates_status_check CHECK (status IN ('preparing', 'open', 'closed'));
ALTER TABLE debates DROP CONSTRAINT IF EXISTS debates_close_reason_check;
ALTER TABLE debates ADD CONSTRAINT debates_close_reason_check
    CHECK (close_reason IN ('ended', 'silence', 'no_participants', 'failed', 'stopped', 'tie', 'no_vote', 'max_rounds'));   -- the last three: debates of the first design

ALTER TABLE debates DROP COLUMN IF EXISTS duration_seconds;
ALTER TABLE debates DROP COLUMN IF EXISTS round;
ALTER TABLE debates DROP COLUMN IF EXISTS max_rounds;
ALTER TABLE debates DROP COLUMN IF EXISTS ends_at;
ALTER TABLE debates DROP COLUMN IF EXISTS voting_ends_at;
ALTER TABLE debates DROP COLUMN IF EXISTS vote_message_id;
DROP TABLE IF EXISTS debate_votes;

ALTER TABLE debates ADD COLUMN IF NOT EXISTS context text CHECK (char_length(context) <= 1000);      -- what the person wrote to frame the debate (optional)
ALTER TABLE debates ADD COLUMN IF NOT EXISTS in_thread boolean NOT NULL DEFAULT true;                  -- false: the debate takes place in the channel itself (`thread_id` is then the channel)
ALTER TABLE debates ADD COLUMN IF NOT EXISTS verify boolean NOT NULL DEFAULT true;                     -- the claims of THIS debate are checked (never more than the owner's setting allows)
ALTER TABLE debates ADD COLUMN IF NOT EXISTS quiet_seconds integer CHECK (quiet_seconds BETWEEN 600 AND 2592000);   -- the debate ends by itself after this long without a message
ALTER TABLE debates ADD COLUMN IF NOT EXISTS start_message_id bigint;                                  -- the launch message: what is written after it belongs to the debate
ALTER TABLE debates ADD COLUMN IF NOT EXISTS last_activity_at timestamptz;                             -- the last message or position

-- Where a debate takes place (`thread_id`) can now be a channel, and a channel hosts one debate after another: the place is unique only among the debates that are not over.
ALTER TABLE debates DROP CONSTRAINT IF EXISTS debates_thread_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS debates_place_open_idx ON debates (thread_id) WHERE status <> 'closed' AND thread_id IS NOT NULL;
