-- Debates (docs/DEBAT.md): `/dindon debat <subject>` opens a thread, people take a position with a button (for / not sure / against), a timer runs,
-- and at its end the participants vote to go on or to stop. This file is the state of that; the Discord side and the analysis come later.
--
-- Deliberately WITHOUT links to `users`, `messages`, `channels` or `guilds`: erasing a person deletes their row there (privacy.erase_person), the messages
-- are written by another path (the ingestion) a moment after the debate sees them, and a server that was never ingested has no row. Each table that holds a
-- person's id is cleaned by name in privacy.py (erase_person, erase_server, export_person, purge_older_than), and a test checks that none is forgotten.
CREATE TABLE IF NOT EXISTS debates (
    id                  bigserial PRIMARY KEY,
    guild_id            bigint NOT NULL,
    channel_id          bigint NOT NULL,                  -- the channel where the command was used; the thread lives under it
    thread_id           bigint UNIQUE,                    -- null while 'preparing' (the thread is not created yet)
    topic               text   NOT NULL CHECK (char_length(topic) BETWEEN 3 AND 200),   -- as typed by the person, never reworded
    created_by          bigint,                           -- null once that person is erased
    -- preparing: the row exists, the thread does not yet; open: the timer runs; voting: the timer ended, the participants vote to go on or stop; closed
    status              text   NOT NULL DEFAULT 'preparing' CHECK (status IN ('preparing', 'open', 'voting', 'closed')),
    close_reason        text   CHECK (close_reason IN ('stopped', 'tie', 'no_vote', 'no_participants', 'max_rounds', 'failed')),
    duration_seconds    integer NOT NULL CHECK (duration_seconds BETWEEN 60 AND 86400),
    round               smallint NOT NULL DEFAULT 1,      -- 1 = the first period; each vote to go on starts the next
    max_rounds          smallint NOT NULL DEFAULT 7 CHECK (max_rounds >= 1),   -- the first period and 6 extensions
    question_message_id bigint,                           -- the message with the buttons of the positions
    vote_message_id     bigint,                           -- the message with the buttons go on / stop of the vote in progress (null: not posted yet)
    final_message_id    bigint,                           -- the statistics at the end (null: not posted yet)
    created_at          timestamptz NOT NULL DEFAULT now(),
    started_at          timestamptz,
    ends_at             timestamptz,                      -- the end of the current period (status 'open')
    voting_ends_at      timestamptz,                      -- the end of the vote (status 'voting')
    closed_at           timestamptz,
    CHECK ((status = 'closed') = (close_reason IS NOT NULL) AND (status = 'closed') = (closed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS debates_active_idx ON debates (guild_id, status) WHERE status <> 'closed';
CREATE INDEX IF NOT EXISTS debates_creator_idx ON debates (created_by) WHERE created_by IS NOT NULL;

-- The messages written in the thread: who, and when. The text is not copied here (it is in `messages` once ingested).
CREATE TABLE IF NOT EXISTS debate_messages (
    debate_id  bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    message_id bigint NOT NULL,
    author_id  bigint NOT NULL,
    sent_at    timestamptz NOT NULL,
    PRIMARY KEY (debate_id, message_id)
);
CREATE INDEX IF NOT EXISTS debate_messages_author_idx ON debate_messages (author_id);

-- Every position a person took, in order: the current one is the last, the others show that they changed their mind.
CREATE TABLE IF NOT EXISTS debate_positions (
    id        bigserial PRIMARY KEY,
    debate_id bigint NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    user_id   bigint NOT NULL,
    position  text   NOT NULL CHECK (position IN ('for', 'unsure', 'against')),
    chosen_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS debate_positions_current_idx ON debate_positions (debate_id, user_id, id DESC);
CREATE INDEX IF NOT EXISTS debate_positions_person_idx ON debate_positions (user_id);

-- The votes to go on or to stop, one per person and per period (changeable until the vote ends).
CREATE TABLE IF NOT EXISTS debate_votes (
    debate_id bigint   NOT NULL REFERENCES debates (id) ON DELETE CASCADE,
    round     smallint NOT NULL,
    user_id   bigint   NOT NULL,
    choice    text     NOT NULL CHECK (choice IN ('continue', 'stop')),
    voted_at  timestamptz NOT NULL,
    PRIMARY KEY (debate_id, round, user_id)
);
CREATE INDEX IF NOT EXISTS debate_votes_person_idx ON debate_votes (user_id);
