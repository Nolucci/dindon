-- The card that a person sets up for themselves with `/dindon mycard` (docs/regles-du-bot.md): within what the administrator allows, which blocks of each page show, which of their
-- positions are shown, and short notes under a page or a position. One row per person and server. Like the debate tables, no foreign key towards `users`: erasing a person deletes the
-- row by name (privacy.erase_person), as does removing a server (privacy.erase_server); a test checks that none is forgotten.
CREATE TABLE IF NOT EXISTS card_prefs (
    guild_id   bigint NOT NULL,
    user_id    bigint NOT NULL,
    prefs      jsonb  NOT NULL,                  -- {"blocks": {page: [block]}, "pinned": [claim id], "notes": {"section:<page>" | "pos:<claim id>": text}}
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS card_prefs_user_idx ON card_prefs (user_id);
