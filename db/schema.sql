-- Database schema for the messages exported by DiscordChatExporter (JSON format, schema version 2).
--
-- The tables mirror the layout of the export: users, roles and emoji are stored once, and messages
-- refer to them by ID. Discord IDs are 63-bit numbers, so they fit in a bigint, which is smaller
-- and faster to join than text. Everything can be run again safely (it only creates what is missing).
-- Requires PostgreSQL 14 or later and a UTF-8 database.

CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- French full-text search that ignores accents ("democratie" finds "démocratie")
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'french_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION french_unaccent (COPY = french);
        ALTER TEXT SEARCH CONFIGURATION french_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------------------------
-- Where the data comes from
-- ---------------------------------------------------------------------------------------------

-- One row per imported export file. A file can only be imported once.
CREATE TABLE IF NOT EXISTS ingest_runs (
    id             bigserial PRIMARY KEY,
    source_file    text,
    source_sha256  text UNIQUE,
    schema_version integer     NOT NULL,
    exported_at    timestamptz NOT NULL,
    guild_id       bigint,
    channel_id     bigint,
    message_count  integer     NOT NULL,
    date_after     timestamptz,
    date_before    timestamptz,
    imported_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------------------------
-- Servers, channels
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS guilds (
    id              bigint PRIMARY KEY,
    name            text NOT NULL,
    -- Names often use fancy Unicode letters (e.g. "𝔻𝕚𝕧𝕖𝕣𝕥𝕚𝕤𝕤𝕖𝕞𝕖𝕟𝕥𝕤"), this is the plain version for searching
    name_normalized text GENERATED ALWAYS AS (normalize(name, NFKC)) STORED,
    icon_url        text
);

CREATE TABLE IF NOT EXISTS channels (
    id              bigint PRIMARY KEY,
    guild_id        bigint NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    -- Category, or the channel that a thread or forum post belongs to. Not a foreign key,
    -- because the parent is not necessarily exported.
    parent_id       bigint,
    parent_name     text,
    type            text   NOT NULL,
    name            text   NOT NULL,
    name_normalized text GENERATED ALWAYS AS (normalize(name, NFKC)) STORED,
    topic           text,
    icon_url        text
);
CREATE INDEX IF NOT EXISTS channels_guild_idx  ON channels (guild_id);
CREATE INDEX IF NOT EXISTS channels_parent_idx ON channels (parent_id);

-- ---------------------------------------------------------------------------------------------
-- People
-- ---------------------------------------------------------------------------------------------

-- The Discord account. Its ID never changes, unlike the names, so it is the identity of a person.
CREATE TABLE IF NOT EXISTS users (
    id            bigint PRIMARY KEY,
    name          text    NOT NULL,                -- username
    discriminator text    NOT NULL DEFAULT '0000',
    global_name   text,                            -- display name chosen by the user
    is_bot        boolean NOT NULL DEFAULT false,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

-- What a person looks like in one server. Nickname, color, roles and avatar belong to the server.
CREATE TABLE IF NOT EXISTS members (
    guild_id    bigint NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    user_id     bigint NOT NULL REFERENCES users (id)  ON DELETE CASCADE,
    nickname    text,
    color       text,
    avatar_url  text,
    observed_at timestamptz NOT NULL,                -- when it was last seen in an export
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS members_user_idx ON members (user_id);

CREATE TABLE IF NOT EXISTS roles (
    id         bigint PRIMARY KEY,
    guild_id   bigint  NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    name       text    NOT NULL,
    color      text,
    position   integer NOT NULL                      -- the higher, the more important
);
CREATE INDEX IF NOT EXISTS roles_guild_idx ON roles (guild_id);

CREATE TABLE IF NOT EXISTS member_roles (
    guild_id bigint NOT NULL,
    user_id  bigint NOT NULL,
    role_id  bigint NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    PRIMARY KEY (guild_id, user_id, role_id),
    FOREIGN KEY (guild_id, user_id) REFERENCES members (guild_id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS member_roles_role_idx ON member_roles (role_id);

-- Every name that a person has been seen with, so that nothing is lost when they rename themselves.
-- 'name' and 'globalName' belong to the account (guild_id is 0), 'nickname' to a server.
CREATE TABLE IF NOT EXISTS identity_history (
    user_id       bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    guild_id      bigint NOT NULL DEFAULT 0,
    field         text   NOT NULL CHECK (field IN ('name', 'globalName', 'nickname')),
    value         text   NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at  timestamptz NOT NULL,
    PRIMARY KEY (user_id, guild_id, field, value)
);

-- The name that Discord displays: nickname, otherwise display name, otherwise username
CREATE OR REPLACE VIEW member_names AS
SELECT m.guild_id,
       u.id AS user_id,
       COALESCE(m.nickname, u.global_name, u.name) AS display_name,
       u.name,
       u.global_name,
       m.nickname,
       u.is_bot
FROM users u
LEFT JOIN members m ON m.user_id = u.id;

-- ---------------------------------------------------------------------------------------------
-- Emoji
-- ---------------------------------------------------------------------------------------------

-- Referred to by 'key': the ID of a custom emoji, or the character itself for a standard emoji
CREATE TABLE IF NOT EXISTS emojis (
    key         text PRIMARY KEY,
    id          bigint,                              -- custom emoji only
    name        text    NOT NULL,
    code        text,                                -- e.g. 'rose'
    is_animated boolean NOT NULL DEFAULT false,
    image_url   text    NOT NULL
);

-- ---------------------------------------------------------------------------------------------
-- Messages
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS messages (
    id                   bigint PRIMARY KEY,          -- also encodes the creation time
    channel_id           bigint      NOT NULL REFERENCES channels (id) ON DELETE CASCADE,
    author_id            bigint      NOT NULL REFERENCES users (id)    ON DELETE CASCADE,
    type                 text        NOT NULL,
    sent_at              timestamptz NOT NULL,
    edited_at            timestamptz,
    call_ended_at        timestamptz,
    is_pinned            boolean     NOT NULL DEFAULT false,
    content              text        NOT NULL,

    -- What was replied to (kept even if that message is not in the database)
    reference_type       text,
    reference_message_id bigint,
    reference_channel_id bigint,
    reference_guild_id   bigint,
    reference_author_id  bigint REFERENCES users (id) ON DELETE SET NULL,
    reference_content    text,

    -- Use of a bot command
    interaction_id       bigint,
    interaction_name     text,
    interaction_user_id  bigint REFERENCES users (id) ON DELETE SET NULL,

    -- Everything else that is not worth a column: embeds, stickers, poll, forwardedMessage
    extra                jsonb,

    last_seen_run_id     bigint REFERENCES ingest_runs (id) ON DELETE SET NULL,

    -- Full-text search, in French, ignoring accents and fancy Unicode letters
    content_tsv          tsvector GENERATED ALWAYS AS
                         (to_tsvector('french_unaccent', normalize(content, NFKC))) STORED
);

-- All the messages of a person, in order. This is the main access path for profiles.
CREATE INDEX IF NOT EXISTS messages_author_idx    ON messages (author_id, sent_at);
CREATE INDEX IF NOT EXISTS messages_channel_idx   ON messages (channel_id, sent_at);
CREATE INDEX IF NOT EXISTS messages_reference_idx ON messages (reference_message_id) WHERE reference_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS messages_ref_author_idx ON messages (reference_author_id) WHERE reference_author_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS messages_tsv_idx       ON messages USING gin (content_tsv);

CREATE TABLE IF NOT EXISTS attachments (
    id         bigint PRIMARY KEY,
    message_id bigint NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    url        text   NOT NULL,
    file_name  text   NOT NULL,
    size_bytes bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS attachments_message_idx ON attachments (message_id);

CREATE TABLE IF NOT EXISTS mentions (
    message_id bigint NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    user_id    bigint NOT NULL REFERENCES users (id)    ON DELETE CASCADE,
    PRIMARY KEY (message_id, user_id)
);
CREATE INDEX IF NOT EXISTS mentions_user_idx ON mentions (user_id);

-- Emoji used in the text of a message
CREATE TABLE IF NOT EXISTS message_emojis (
    message_id bigint NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    emoji_key  text   NOT NULL REFERENCES emojis (key),
    PRIMARY KEY (message_id, emoji_key)
);

CREATE TABLE IF NOT EXISTS reactions (
    message_id bigint  NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    emoji_key  text    NOT NULL REFERENCES emojis (key),
    count      integer NOT NULL,
    PRIMARY KEY (message_id, emoji_key)
);

-- Who reacted (only known if the export was made with the reaction authors)
CREATE TABLE IF NOT EXISTS reaction_users (
    message_id bigint NOT NULL,
    emoji_key  text   NOT NULL,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, emoji_key, user_id),
    FOREIGN KEY (message_id, emoji_key) REFERENCES reactions (message_id, emoji_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS reaction_users_user_idx ON reaction_users (user_id);

-- ---------------------------------------------------------------------------------------------
-- Analysis: what is derived from the messages
-- ---------------------------------------------------------------------------------------------

-- Everything that was generated about a person, with what it was generated from, so that it can
-- be redone when there are new messages or a better model.
CREATE TABLE IF NOT EXISTS profiles (
    id               bigserial PRIMARY KEY,
    guild_id         bigint NOT NULL REFERENCES guilds (id) ON DELETE CASCADE,
    user_id          bigint NOT NULL REFERENCES users (id)  ON DELETE CASCADE,
    model            text   NOT NULL,                -- e.g. the local model that wrote it
    prompt_version   text   NOT NULL,
    message_count    integer NOT NULL,               -- how many messages it is based on
    last_message_id  bigint,                         -- the most recent of them
    profile          jsonb  NOT NULL,
    generated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS profiles_user_idx ON profiles (user_id, guild_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS cards (
    id          bigserial PRIMARY KEY,
    profile_id  bigint NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    kind        text   NOT NULL,
    title       text,
    data        jsonb  NOT NULL,
    image_path  text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cards_profile_idx ON cards (profile_id);

-- ---------------------------------------------------------------------------------------------
-- Ready-made views
-- ---------------------------------------------------------------------------------------------

-- Figures about each person, per server
CREATE OR REPLACE VIEW user_stats AS
SELECT c.guild_id,
       m.author_id AS user_id,
       count(*)                                                  AS message_count,
       min(m.sent_at)                                            AS first_message_at,
       max(m.sent_at)                                            AS last_message_at,
       count(DISTINCT (m.sent_at AT TIME ZONE 'UTC')::date)      AS active_days,
       round(avg(length(m.content)))                             AS avg_length,
       count(*) FILTER (WHERE m.reference_message_id IS NOT NULL) AS replies_sent,
       count(*) FILTER (WHERE m.edited_at IS NOT NULL)           AS edited_count
FROM messages m
JOIN channels c ON c.id = m.channel_id
GROUP BY c.guild_id, m.author_id;

-- Who talks to whom: replies, mentions and reactions, as one list of links between people
CREATE OR REPLACE VIEW interactions AS
SELECT c.guild_id, m.author_id AS from_user_id, m.reference_author_id AS to_user_id,
       'reply'::text AS kind, m.id AS message_id, m.sent_at
FROM messages m JOIN channels c ON c.id = m.channel_id
WHERE m.reference_author_id IS NOT NULL
UNION ALL
SELECT c.guild_id, m.author_id, mn.user_id, 'mention', m.id, m.sent_at
FROM mentions mn JOIN messages m ON m.id = mn.message_id JOIN channels c ON c.id = m.channel_id
UNION ALL
SELECT c.guild_id, ru.user_id, m.author_id, 'reaction', m.id, m.sent_at
FROM reaction_users ru JOIN messages m ON m.id = ru.message_id JOIN channels c ON c.id = m.channel_id;

-- ---------------------------------------------------------------------------------------------
-- Forgetting someone
-- ---------------------------------------------------------------------------------------------

-- Removes a person and everything that is linked to them: their messages, reactions, mentions,
-- memberships, profiles and cards. What others quoted from their messages when replying is
-- erased as well.
CREATE OR REPLACE FUNCTION forget_user(p_user_id bigint) RETURNS void
LANGUAGE sql AS $$
    UPDATE messages SET reference_content = NULL, reference_author_id = NULL
    WHERE reference_author_id = p_user_id;
    DELETE FROM users WHERE id = p_user_id;
$$;
