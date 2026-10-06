"""The Discord adapter: Gateway payloads in, JSON v2 documents out.

Level of proof: SIMULATED. The payloads are invented, and the expected values come from reading the exporter's code
(JsonMessageWriter, PlainTextMarkdownVisitor, MarkdownParser.MinimalNodeMatcher, MessageKind, User, Member, Role, ImageCdn),
not from running the exporter. Whether a real message comes out exactly as the real exporter writes it is only settled by
comparing the two on a real server (tools/compare_with_export.py, step M1 of the plan).
"""
import json
from pathlib import Path

import jsonschema
import pytest

from dindon.bot.adapter import Directory, build_document, digest, format_time, parse_time
from dindon.ingest.loader import ingest_document
from gateway_fixtures import (ADMIN, ALICE, BOB, BOT, CAROL, CATEGORY, CITIZEN, EUROPEAN, GENERAL, GUILD, OLD_DAVE, THREAD, VOICE,
                              channel, guild_create, member, message_create, role)
from datetime import UTC

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "JSON-format.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def directory():
    d = Directory([GUILD])
    d.apply("GUILD_CREATE", guild_create())
    return d


def document(directory, *messages, channel_id=GENERAL):
    doc = build_document(directory, GUILD, channel_id, list(messages))
    assert doc is not None
    jsonschema.validate(doc, SCHEMA)  # whatever the test is about, the contract is respected
    return doc


def text_of(directory, content, author=ALICE, mentions=(), **extra):
    return document(directory, message_create(1, content, author, mentions=mentions, **extra))["messages"][0]["content"]


# ---------------------------------------------------------------------------------------------
# A message, as the contract wants it
# ---------------------------------------------------------------------------------------------


def test_a_plain_message_gives_the_document_the_ingestion_expects(directory):
    doc = document(directory, message_create(5001, "Bonjour 🌹", member_data=member("Ali", (CITIZEN, EUROPEAN))))
    assert doc["schemaVersion"] == 2 and doc["messageCount"] == 1
    assert doc["guild"] == {"id": GUILD, "name": "Serveur test", "iconUrl": "https://cdn.discordapp.com/embed/avatars/0.png"}
    assert doc["channel"] == {"id": GENERAL, "type": "GuildTextChat", "categoryId": CATEGORY, "category": "Politique",
                              "name": "general", "topic": "Le salon principal"}
    assert doc["messages"] == [{"id": "5001", "type": "Default", "timestamp": "2026-10-02T19:00:00.123Z", "content": "Bonjour 🌹",
                                "authorId": ALICE["id"]}]
    assert doc["exportedAt"] == "2026-10-02T19:00:00.123Z"
    (user,) = doc["users"]
    assert user == {"id": ALICE["id"], "name": "alice", "discriminator": "0000", "globalName": "Alice", "nickname": "Ali",
                    "color": "#00FF00", "isBot": False, "roleIds": [EUROPEAN, CITIZEN],
                    "avatarUrl": f"https://cdn.discordapp.com/avatars/{ALICE['id']}/ahash.png?size=512"}
    assert doc["roles"] == [{"id": EUROPEAN, "name": "Européiste", "color": "#00FF00", "position": 3},
                            {"id": CITIZEN, "name": "Citoyen", "position": 1}]


def test_timestamps_are_utc_with_milliseconds_cut_not_rounded():
    assert format_time(parse_time("2026-10-02T19:00:00.999999+00:00")) == "2026-10-02T19:00:00.999Z"
    assert format_time(parse_time("2026-10-02T21:30:00+02:00")) == "2026-10-02T19:30:00.000Z"
    assert format_time(parse_time("2026-10-02T19:00:00Z")) == "2026-10-02T19:00:00.000Z"


def test_the_message_kinds_are_the_names_of_the_exporter(directory):
    kinds = {0: "Default", 19: "Reply", 20: "ChatInputCommand", 6: "ChannelPinnedMessage", 7: "GuildMemberJoin", 46: "PollResult",
             44: "PurchaseNotification", 40: "40"}  # a kind that the enum does not know is written as its number
    for number, name in kinds.items():
        assert document(directory, message_create(1, "x", type=number))["messages"][0]["type"] == name


def test_edited_pinned_attachments_and_stickers(directory):
    doc = document(directory, message_create(
        1, "voir", edited_timestamp="2026-10-02T19:05:00.500000+00:00", pinned=True,
        attachments=[{"id": "77", "url": "https://cdn.example/a.png", "filename": "a.png", "size": 1234, "width": 10, "height": 10}],
        sticker_items=[{"id": "88", "name": "wave", "format_type": 4}, {"id": "89", "name": "odd", "format_type": 9}]))
    message = doc["messages"][0]
    assert message["timestampEdited"] == "2026-10-02T19:05:00.500Z" and message["isPinned"] is True
    assert message["attachments"] == [{"id": "77", "url": "https://cdn.example/a.png", "fileName": "a.png", "fileSizeBytes": 1234}]
    assert message["stickers"] == [{"id": "88", "name": "wave", "format": "Gif", "sourceUrl": "https://cdn.discordapp.com/stickers/88.gif"}]


def test_nothing_is_invented_for_what_a_message_does_not_have(directory):
    doc = document(directory, message_create(1, "x", embeds=[], poll=None, message_snapshots=[{"message": {"content": "y", "timestamp": "2026-10-02T19:00:00.000000+00:00"}}]))
    message = doc["messages"][0]
    assert not {"embeds", "poll", "forwardedMessage", "reactions", "inlineEmojis"} & message.keys()        # (a snapshot without a forward reference is nothing)


def test_embeds_are_written_as_the_exporter_writes_them(directory):
    embed = {"type": "rich", "title": "Un <@{}>".format(BOB["id"]), "url": "https://example.org/a", "description": f"Du texte <:kekw:555> et <#{GENERAL}>", "color": 0xFF0000,
             "timestamp": "2026-10-02T18:00:00.000000+00:00",
             "author": {"name": "Auteur", "url": "https://example.org/u", "icon_url": "https://x/i.png", "proxy_icon_url": "https://p/i.png"},
             "thumbnail": {"url": "https://x/t.png", "proxy_url": "https://p/t.png", "width": 10, "height": 20}, "image": {"url": "https://x/m.png"},
             "video": {"url": "https://x/v.mp4", "width": 640}, "footer": {"text": "pied", "icon_url": "https://x/f.png"},
             "fields": [{"name": "n", "value": "v", "inline": True}, {"name": "n2", "value": "v2"}]}
    doc = document(directory, message_create(1, "x", embeds=[embed], member_data=member()))
    assert doc["messages"][0]["embeds"] == [{
        "title": "Un @Unknown", "url": "https://example.org/a", "timestamp": "2026-10-02T18:00:00.000Z", "description": "Du texte :kekw: et #general",
        "color": "#FF0000", "author": {"name": "Auteur", "url": "https://example.org/u", "iconUrl": "https://p/i.png", "iconCanonicalUrl": "https://x/i.png"},
        "thumbnail": {"url": "https://p/t.png", "canonicalUrl": "https://x/t.png", "width": 10, "height": 20},
        "image": {"url": "https://x/m.png", "canonicalUrl": "https://x/m.png"}, "images": [{"url": "https://x/m.png", "canonicalUrl": "https://x/m.png"}], "video": {"url": "https://x/v.mp4", "canonicalUrl": "https://x/v.mp4", "width": 640},
        "footer": {"text": "pied", "iconUrl": "https://x/f.png", "iconCanonicalUrl": "https://x/f.png"},
        "fields": [{"name": "n", "value": "v", "isInline": True}, {"name": "n2", "value": "v2", "isInline": False}], "inlineEmojis": ["555"]}]
    assert any(e["id"] == "555" for e in doc["emojis"])


def test_a_poll_is_written_with_its_votes_when_it_has_results(directory):
    poll = {"question": {"text": "On y va ?"}, "answers": [{"answer_id": 1, "poll_media": {"text": "Oui", "emoji": {"id": None, "name": "👍"}}},
                                                          {"answer_id": 2, "poll_media": {"text": "Non"}}],
            "expiry": "2026-10-03T19:00:00.000000+00:00", "allow_multiselect": True, "results": {"is_finalized": True, "answer_counts": [{"id": 1, "count": 5}]}}
    doc = document(directory, message_create(1, "", poll=poll))
    assert doc["messages"][0]["poll"] == {"question": "On y va ?", "answers": [{"id": 1, "text": "Oui", "emoji": "👍", "votes": 5}, {"id": 2, "text": "Non", "votes": 0}],
                                          "expiresAt": "2026-10-03T19:00:00.000Z", "allowsMultipleAnswers": True, "isFinalized": True}
    assert {"name": "👍", "isAnimated": False, "imageUrl": "https://twemoji.maxcdn.com/v/latest/svg/1f44d.svg"} in doc["emojis"]
    open_poll = document(directory, message_create(2, "", poll={"question": {"text": "?"}, "answers": [{"answer_id": 1, "poll_media": {"text": "a"}}]}))
    assert open_poll["messages"][0]["poll"] == {"question": "?", "answers": [{"id": 1, "text": "a"}]}          # no results yet: no votes


def test_a_forwarded_message_keeps_what_it_was(directory):
    snapshot = {"message": {"content": "Salut <@{}>".format(BOB["id"]), "timestamp": "2026-10-01T10:00:00.000000+00:00", "edited_timestamp": "2026-10-01T10:05:00.000000+00:00",
                            "attachments": [{"id": "9", "url": "https://x/a.png", "filename": "a.png", "size": 3}], "embeds": [{"title": "t"}],
                            "sticker_items": [{"id": "8", "name": "w", "format_type": 1}]}}
    doc = document(directory, message_create(1, "", message_snapshots=[snapshot], message_reference={"type": 1, "message_id": "5", "channel_id": GENERAL, "guild_id": GUILD}))
    message = doc["messages"][0]
    assert message["reference"]["type"] == "Forward"
    assert message["forwardedMessage"] == {"timestamp": "2026-10-01T10:00:00.000Z", "timestampEdited": "2026-10-01T10:05:00.000Z", "content": "Salut @Unknown",
                                           "attachments": [{"id": "9", "url": "https://x/a.png", "fileName": "a.png", "fileSizeBytes": 3}], "embeds": [{"title": "t"}],
                                           "stickers": [{"id": "8", "name": "w", "format": "Png", "sourceUrl": "https://cdn.discordapp.com/stickers/8.png"}]}


def test_reactions_are_counted_and_name_the_people_who_reacted_when_they_were_fetched(directory):
    reactions = [{"emoji": {"id": None, "name": "👍"}, "count": 2}, {"emoji": {"id": "555", "name": "kekw", "animated": True}, "count": 1}, {"emoji": {"id": None, "name": "❤️"}, "count": 1}]
    message = message_create(1, "x", reactions=reactions)
    plain = document(directory, message)["messages"][0]["reactions"]
    assert plain == [{"emoji": "👍", "count": 2}, {"emoji": "555", "count": 1}, {"emoji": "❤️", "count": 1}]          # counted, nobody named
    doc = build_document(directory, GUILD, GENERAL, [message], reaction_users={"1": {"👍": [BOB, CAROL], "555": [BOB]}})
    jsonschema.validate(doc, SCHEMA)
    assert doc["messages"][0]["reactions"] == [{"emoji": "👍", "count": 2, "userIds": [BOB["id"], CAROL["id"]]}, {"emoji": "555", "count": 1, "userIds": [BOB["id"]]},
                                              {"emoji": "❤️", "count": 1}]
    assert {u["id"] for u in doc["users"]} == {ALICE["id"], BOB["id"], CAROL["id"]}                                  # the people who reacted are in `users`
    assert {"id": "555", "name": "kekw", "isAnimated": True, "imageUrl": "https://cdn.discordapp.com/emojis/555.gif"} in doc["emojis"]
    assert {"name": "❤️", "isAnimated": False, "imageUrl": "https://twemoji.maxcdn.com/v/latest/svg/2764.svg"} in doc["emojis"]    # the variation selector is left out


def test_an_export_says_when_it_was_made_and_which_period_it_covers(directory):
    from datetime import datetime, timezone
    when = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
    doc = build_document(directory, GUILD, GENERAL, [message_create(1, "x")], exported_at=when,
                         date_range={"after": datetime(2026, 10, 1, tzinfo=UTC), "before": None})
    jsonschema.validate(doc, SCHEMA)
    assert doc["exportedAt"] == "2026-10-03T08:00:00.000Z" and doc["dateRange"] == {"after": "2026-10-01T00:00:00.000Z"}
    assert list(doc).index("dateRange") == list(doc).index("channel") + 1                                           # in the place of the layout
    assert "dateRange" not in build_document(directory, GUILD, GENERAL, [message_create(1, "x")], date_range={"after": None, "before": None})


def test_the_messages_are_in_chronological_order_and_exportedAt_is_the_newest_one(directory):
    doc = document(directory, message_create(30, "c", timestamp="2026-10-02T19:03:00.000000+00:00"),
                   message_create(10, "a", timestamp="2026-10-02T19:01:00.000000+00:00"),
                   message_create(20, "b", timestamp="2026-10-02T19:02:00.000000+00:00"))
    assert [m["id"] for m in doc["messages"]] == ["10", "20", "30"] and doc["messageCount"] == 3
    assert doc["exportedAt"] == "2026-10-02T19:03:00.000Z"


def test_the_same_messages_always_give_the_same_document_and_digest(directory):
    first = document(directory, message_create(1, "a"), message_create(2, "b", BOB))
    again = document(directory, message_create(2, "b", BOB), message_create(1, "a"))  # even delivered in another order
    assert first == again and digest(first) == digest(again)
    assert digest(first) != digest(document(directory, message_create(1, "a")))


# ---------------------------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------------------------


def test_the_color_comes_from_the_most_important_role_that_has_one_and_unknown_roles_are_ignored(directory):
    everything = document(directory, message_create(1, "x", member_data=member(None, (CITIZEN, EUROPEAN, ADMIN, "999"))))["users"][0]
    assert everything["roleIds"] == [ADMIN, EUROPEAN, CITIZEN] and everything["color"] == "#FF0000"
    no_color = document(directory, message_create(1, "x", member_data=member(None, (CITIZEN,))))["users"][0]
    assert no_color["roleIds"] == [CITIZEN] and "color" not in no_color
    none = document(directory, message_create(1, "x", member_data=member()))["users"][0]
    assert "roleIds" not in none and "nickname" not in none


def test_names_discriminators_and_bots(directory):
    users = {u["id"]: u for u in document(directory, message_create(1, "x", OLD_DAVE, mentions=(CAROL, {**BOB, "global_name": "bob", "bot": True})))["users"]}
    assert users[OLD_DAVE["id"]]["discriminator"] == "1234" and "globalName" not in users[OLD_DAVE["id"]]
    assert users[CAROL["id"]]["discriminator"] == "0000" and "globalName" not in users[CAROL["id"]]  # no display name
    assert "globalName" not in users[BOB["id"]] and users[BOB["id"]]["isBot"] is True                # same as the username


def test_avatars_follow_the_exporter(directory):
    users = {u["id"]: u["avatarUrl"] for u in document(directory, message_create(
        1, "x", OLD_DAVE, mentions=(BOB, CAROL), member_data=member(avatar="m1")))["users"]}
    assert users[OLD_DAVE["id"]] == f"https://cdn.discordapp.com/guilds/{GUILD}/users/{OLD_DAVE['id']}/avatars/m1.png?size=512"
    assert users[CAROL["id"]] == f"https://cdn.discordapp.com/avatars/{CAROL['id']}/a_animated.gif?size=512"
    assert users[BOB["id"]] == f"https://cdn.discordapp.com/embed/avatars/{(int(BOB['id']) >> 22) % 6}.png"  # no discriminator
    legacy = document(directory, message_create(1, "x", {**OLD_DAVE, "id": "5"}, member_data=None))["users"][0]
    assert legacy["avatarUrl"] == "https://cdn.discordapp.com/embed/avatars/4.png"                              # 1234 % 5


def test_a_person_seen_with_and_without_member_data_keeps_the_member_data(directory):
    """Someone who wrote (with roles) and who was only the author of a replied-to message: the roles must not disappear."""
    parent = message_create(1, "avant", BOB, member_data=None)
    doc = document(directory, message_create(2, "d'accord", ALICE, reply_to=parent),
                   message_create(3, "bof", BOB, member_data=member("Bobo", (ADMIN,))))
    bob = next(u for u in doc["users"] if u["id"] == BOB["id"])
    assert bob["nickname"] == "Bobo" and bob["roleIds"] == [ADMIN]


# ---------------------------------------------------------------------------------------------
# The text: what the exporter does to mentions, emoji and dates, and nothing else
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("content, expected", [
    ("<@1000000000000000002> et <@!1000000000000000003>", "@Bobby et @carol"),           # display name, then username; both spellings
    ("<@1000000000000000001> parle", "@Ali parle"),                                      # the nickname wins (here: the author)
    ("<@999>", "@Unknown"),                                                              # nobody knows this one
    ("@everyone et @here", "@everyone et @here"),
    (f"<@&{ADMIN}> <@&999>", "@Admin @deleted-role"),
    (f"<#{GENERAL}> <#{VOICE}> <#998>", "#general #Vocal [voice] #deleted-channel"),
    ("<:lul:123> <a:dance:456>", ":lul: :dance:"),
    ("🌹 :rose: **gras** __sous__ ~~barré~~ > citation", "🌹 :rose: **gras** __sous__ ~~barré~~ > citation"),  # nothing else is touched
    ("`code <@1000000000000000002>`", "`code @Bobby`"),                                    # the exporter does not look at code blocks either
    ("<@1000000000000000002><@1000000000000000003>", "@Bobby@carol"),
    ("<:a <@1000000000000000002> b:5>", ":a <@1000000000000000002> b:"),                  # the earliest match wins, even if it spans another
    ("", ""),
])
def test_mentions_emoji_and_markup_in_the_text(directory, content, expected):
    got = text_of(directory, content, mentions=(BOB, CAROL), member_data=member("Ali"))
    assert got == expected


@pytest.mark.parametrize("content, expected", [
    ("<t:0:t>", "00:00"), ("<t:0:T>", "00:00:00"), ("<t:0:d>", "01/01/1970"), ("<t:0:D>", "Thursday, 01 January 1970"),
    ("<t:0:f>", "Thursday, 01 January 1970 00:00"), ("<t:0:F>", "Thursday, 01 January 1970 00:00:00"),
    ("<t:1759431600>", "10/02/2025 19:00"), ("<t:1759431600:R>", "10/02/2025 19:00"), ("<t:1759431600:r>", "10/02/2025 19:00"),
    ("<t:0:x>", "Invalid date"),                  # an unknown style
    ("<t:99999999999999999999>", "Invalid date"), ("<t:253402300800>", "Invalid date"),  # out of what a date can be (year 10000)
])
def test_timestamps(directory, content, expected):
    assert text_of(directory, content) == expected


def test_a_reply_keeps_who_and_what_was_replied_to(directory):
    parent = message_create(1, "Bonjour <@1000000000000000001>", BOB, member_data=None, mentions=(ALICE,))
    doc = document(directory, message_create(2, "salut Bobby", ALICE, reply_to=parent))
    message = doc["messages"][0]
    assert message["type"] == "Reply"
    assert message["reference"] == {"type": "Default", "messageId": "1", "channelId": GENERAL, "guildId": GUILD,
                                    "authorId": BOB["id"], "content": "Bonjour @Alice"}
    assert {u["id"] for u in doc["users"]} == {ALICE["id"], BOB["id"]}
    assert "mentionedUserIds" not in message


def test_a_reply_whose_parent_is_gone_has_no_author_to_link(directory):
    payload = message_create(2, "salut", ALICE, reply_to=message_create(1, "x", BOB), referenced=None)
    payload["referenced_message"] = None  # Discord says null when the replied-to message was deleted
    reference = document(directory, payload)["messages"][0]["reference"]
    assert reference == {"type": "Default", "messageId": "1", "channelId": GENERAL, "guildId": GUILD}


def test_mentions_are_listed_and_the_people_mentioned_are_in_the_table(directory):
    doc = document(directory, message_create(1, "salut <@1000000000000000002>", ALICE, mentions=(BOB,)))
    assert doc["messages"][0]["mentionedUserIds"] == [BOB["id"]]
    assert {u["id"] for u in doc["users"]} == {ALICE["id"], BOB["id"]}


def test_custom_emoji_of_the_text_are_listed_and_described(directory):
    doc = document(directory, message_create(1, "<:lul:123> et <a:dance:456> et <:lul:123>"))
    assert doc["messages"][0]["inlineEmojis"] == ["123", "456"]
    assert doc["emojis"] == [{"id": "123", "name": "lul", "isAnimated": False, "imageUrl": "https://cdn.discordapp.com/emojis/123.png"},
                             {"id": "456", "name": "dance", "isAnimated": True, "imageUrl": "https://cdn.discordapp.com/emojis/456.gif"}]


def test_a_command_response_names_who_used_the_command(directory):
    doc = document(directory, message_create(1, "résultat", {**BOT, "bot": True}, type=20, member_data=None,
                                             interaction={"id": "9", "name": "sondage", "type": 2, "user": BOB}))
    assert doc["messages"][0]["interaction"] == {"id": "9", "name": "sondage", "userId": BOB["id"]}
    assert {u["id"] for u in doc["users"]} == {BOT["id"], BOB["id"]}


# ---------------------------------------------------------------------------------------------
# System messages: the exporter replaces their content with a sentence
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind, content, extra, expected", [
    (7, "", {}, "Joined the server."),
    (6, "", {}, "Pinned a message."),
    (18, "un fil", {}, "Started a thread."),
    (5, "", {}, "Changed the channel icon."),
    (4, "nouveau nom", {}, "Changed the channel name: nouveau nom"),
    (4, "  ", {}, "Changed the channel name."),
    (8, "a boosté", {}, "a boosté"),                                    # other system kinds keep their content, as written
    (1, "", {"mentions": (BOB,)}, "Added Bobby to the group."),
    (1, "", {}, "Added a recipient."),
    (2, "", {"mentions": (BOB,)}, "Removed Bobby from the group."),
    (2, "", {"mentions": (ALICE,)}, "Left the group."),
    (3, "", {"call": {"ended_timestamp": "2026-10-02T20:30:00.000000+00:00", "participants": []}}, "Started a call that lasted 90 minutes."),
    (3, "", {"call": {"ended_timestamp": "2026-10-03T15:00:30.000000+00:00"}}, "Started a call that lasted 1,200 minutes."),
    (3, "", {}, "Started a call that lasted 0 minutes."),
])
def test_system_messages(directory, kind, content, extra, expected):
    extra = dict(extra)
    mentions = extra.pop("mentions", ())
    message = document(directory, message_create(1, content, type=kind, mentions=mentions, **extra))["messages"][0]
    assert message["content"] == expected
    if "call" in extra and extra["call"].get("ended_timestamp"):
        assert message["callEndedTimestamp"].endswith("Z")


# ---------------------------------------------------------------------------------------------
# What the adapter knows of the servers
# ---------------------------------------------------------------------------------------------


def test_a_thread_is_described_with_its_parent_channel(directory):
    channel_doc = document(directory, message_create(1, "dans le fil", channel_id=THREAD), channel_id=THREAD)["channel"]
    assert channel_doc == {"id": THREAD, "type": "GuildPublicThread", "categoryId": GENERAL, "category": "general", "name": "un fil"}


def test_nothing_is_invented_for_an_unknown_channel_or_server(directory):
    assert build_document(directory, GUILD, "424242", [message_create(1, "x", channel_id="424242")]) is None
    assert build_document(directory, "555", GENERAL, [message_create(1, "x")]) is None
    assert build_document(directory, GUILD, GENERAL, []) is None


def test_the_directory_follows_the_events_of_roles_channels_and_threads(directory):
    directory.apply("GUILD_ROLE_UPDATE", {"guild_id": GUILD, "role": role(ADMIN, "Administrateur", 5, 0x0000FF)})
    directory.apply("GUILD_ROLE_CREATE", {"guild_id": GUILD, "role": role("303", "Écologiste", 2)})
    directory.apply("CHANNEL_CREATE", channel("220", "nouveau", 0, CATEGORY))
    directory.apply("CHANNEL_UPDATE", {**channel(GENERAL, "principal", 0, CATEGORY)})
    directory.apply("THREAD_LIST_SYNC", {"guild_id": GUILD, "threads": [channel("230", "ancien fil", 11, "220")]})
    directory.apply("GUILD_UPDATE", {"id": GUILD, "name": "Autre nom", "icon": "iconhash"})
    doc = document(directory, message_create(1, "<@&303> <#220>", member_data=member(None, (ADMIN, "303"))), channel_id=GENERAL)
    assert doc["messages"][0]["content"] == "@Écologiste #nouveau"
    assert [r["name"] for r in doc["roles"]] == ["Administrateur", "Écologiste"] and doc["roles"][0]["color"] == "#0000FF"
    assert doc["channel"]["name"] == "principal" and doc["guild"]["name"] == "Autre nom"
    assert doc["guild"]["iconUrl"] == "https://cdn.discordapp.com/icons/100/iconhash.png?size=512"
    assert document(directory, message_create(2, "x", channel_id="230"), channel_id="230")["channel"]["category"] == "nouveau"
    directory.apply("GUILD_ROLE_DELETE", {"guild_id": GUILD, "role_id": "303"})
    directory.apply("CHANNEL_DELETE", channel("220", "nouveau", 0, CATEGORY))
    assert text_of(directory, "<@&303> <#220>") == "@deleted-role #deleted-channel"


def test_only_the_servers_that_are_followed_are_known():
    d = Directory([GUILD])
    assert d.apply("GUILD_CREATE", guild_create("777")) is False and d.guild("777") is None
    assert d.apply("CHANNEL_CREATE", channel("5", "x", guild_id="777")) is False
    assert d.apply("GUILD_CREATE", guild_create()) is True and d.guild(GUILD) is not None


def test_an_outage_keeps_what_is_known_and_leaving_the_server_forgets_it(directory):
    directory.apply("GUILD_DELETE", {"id": GUILD, "unavailable": True})
    assert directory.guild(GUILD) is not None
    directory.apply("GUILD_DELETE", {"id": GUILD})
    assert directory.guild(GUILD) is None


# ---------------------------------------------------------------------------------------------
# The adapter and the ingestion, together (with a database)
# ---------------------------------------------------------------------------------------------


def test_what_the_adapter_builds_is_ingested_and_the_links_are_there(ingest_db, directory):
    alice_says = message_create(100, "Vous avez vu ?", ALICE, member_data=member("Ali", (EUROPEAN,)))
    bob_replies = message_create(101, "Oui, <@1000000000000000001> !", BOB, reply_to=alice_says,
                                 mentions=((ALICE, member("Ali", (EUROPEAN,))),),
                                 member_data=member(None, (CITIZEN,)))
    doc = document(directory, alice_says, bob_replies)
    result = ingest_document(ingest_db, doc, "bot", digest(doc), only_new=True)
    assert (result.status, result.messages_new) == ("imported", 2)
    assert ingest_db.execute("SELECT content FROM messages WHERE id = 101").fetchone()[0] == "Oui, @Ali !"
    assert ingest_db.execute("SELECT nickname FROM members WHERE user_id = %s", (int(ALICE["id"]),)).fetchone()[0] == "Ali"
    roles = {r[0] for r in ingest_db.execute("SELECT role_id FROM member_roles WHERE user_id = %s", (int(ALICE["id"]),))}
    assert roles == {int(EUROPEAN)}
    assert ingest_db.execute("SELECT name FROM channels WHERE id = %s", (int(GENERAL),)).fetchone()[0] == "general"
    edges = {(f, t, k) for f, t, k in ingest_db.execute("SELECT from_user_id, to_user_id, kind FROM edges")}
    assert edges == {(int(BOB["id"]), int(ALICE["id"]), "reply"), (int(BOB["id"]), int(ALICE["id"]), "mention")}
    ingest_db.execute("SELECT rebuild_edges()")  # and what was kept up to date is what a rebuild gives
    assert {(f, t, k) for f, t, k in ingest_db.execute("SELECT from_user_id, to_user_id, kind FROM edges")} == edges
