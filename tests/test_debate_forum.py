"""The forum of the debates (docs/regles-du-bot.md, « Un forum pour les débats »): a moderator tells Dindon which forum channel of the server holds the debates, and a debate opened in a thread is then
created there, as a post with labels, instead of a thread under the channel where the command was used.

Level of proof: SIMULATED, like test_debate_bot.py: the forum is a fake in memory built from Discord's documentation (https://docs.discord.com/developers/resources/channel: starting a thread in
a forum, `applied_tags`, REQUIRE_TAG), never the real one.
"""
import pytest

from dindon import privacy
from dindon.debate import forum, store, texts
from gateway_fixtures import BOB, GENERAL, GUILD, THREAD
from test_bot import event
from test_debate_bot import ADMINISTRATOR, ALICE_ID, BOB_ID, MANAGE_MESSAGES, SEND_MESSAGES, TOPIC, fields_of, only_debate, run, world  # noqa: F401 (the fixture)

FORUM = 300
TAGS = (("t_eco", "Économie"), ("t_rel", "Religion"), ("t_intl", "International"), ("t_pol", "Politique", True), ("t_ident", "Identité"), ("t_edu", "Éducation"))


@pytest.fixture
def conn(conn):
    """The `conn` of the other tests, with its transaction already open (see tests/test_debate.py): what the code under test commits stays inside it, and is rolled back."""
    conn.execute("SELECT 1")
    return conn


@pytest.fixture
def with_forum(world):  # noqa: F811
    world.add_forum(FORUM, tags=TAGS)
    return world


# --- the pieces, with no Discord ---------------------------------------------------------------------------------------------


def test_names_are_compared_by_their_words_without_accents_case_or_punctuation():
    assert forum.words("Contrôle de l'économie") == {"controle", "de", "l", "economie"} and forum.words("Économie") == {"economie"} and forum.words("") == set()


def test_a_label_is_found_by_its_name_as_typed_or_its_start_when_only_one_fits():
    tags = [{"id": "1", "name": "Économie"}, {"id": "2", "name": "Service Public"}, {"id": "3", "name": "Service civique"}]
    assert forum.find_tag(tags, "economie")["id"] == "1" and forum.find_tag(tags, "ÉCONOMIE ")["id"] == "1" and forum.find_tag(tags, "service public")["id"] == "2"
    assert forum.find_tag(tags, "service") is None and forum.find_tag(tags, "public")["id"] == "2" and forum.find_tag(tags, "sport") is None and forum.find_tag(tags, "") is None


def test_the_labels_of_a_debate_are_the_chosen_one_then_the_open_ones_named_in_the_axis_and_at_most_five():
    available = [{"id": "e", "name": "Économie"}, {"id": "r", "name": "Religion"}, {"id": "i", "name": "International"}, {"id": "p", "name": "Politique", "moderated": True},
                 {"id": "pc", "name": "Politique commerciale"}]
    assert forum.pick_tags(available, None, None) == [] and forum.pick_tags(available, "p", None) == ["p"]
    assert forum.pick_tags(available, "p", "Religion et État") == ["p", "r"]                                    # the chosen one first, then what the axis names
    assert forum.pick_tags(available, None, "Commerce international") == ["i"]
    assert forum.pick_tags(available, None, "Politique") == []                                                   # a label that only moderators may apply is never guessed
    assert forum.pick_tags(available, "gone", "Contrôle de l'économie") == ["e"]                                # a label that no longer exists is not used
    many = [{"id": str(n), "name": f"Mot{n}"} for n in range(9)]
    assert len(forum.pick_tags(many, "0", " ".join(f"Mot{n}" for n in range(9)))) == 5


def test_the_forum_is_kept_for_each_server_and_taken_off(conn):
    assert forum.get(conn, 1) is None and forum.clear(conn, 1) is False
    forum.save(conn, 1, forum.Forum(300, "Débats", "t_eco", "Économie"))
    forum.save(conn, 2, forum.Forum(400, "Autre"))
    assert forum.get(conn, 1) == forum.Forum(300, "Débats", "t_eco", "Économie") and forum.get(conn, 2) == forum.Forum(400, "Autre", None, None)
    forum.save(conn, 1, forum.Forum(301, "Nouveau"))
    assert forum.get(conn, 1).channel_id == 301 and forum.clear(conn, 1) is True and forum.get(conn, 1) is None and forum.get(conn, 2) is not None


def test_removing_a_server_removes_its_forum_setting(conn):
    forum.save(conn, 1, forum.Forum(300, "Débats"))
    forum.save(conn, 2, forum.Forum(400, "Autre"))
    privacy.erase_server(conn, 1, source="test")
    assert forum.get(conn, 1) is None and forum.get(conn, 2) is not None


# --- /dindon forum -----------------------------------------------------------------------------------------------------------


def test_the_command_has_a_forum_channel_option_and_the_labels(world):  # noqa: F811
    from dindon.bot.privacy_commands import COMMAND

    [command] = [o for o in COMMAND["options"] if o["name"] == "forum"]
    salon, etiquette, retirer = command["options"]
    assert (salon["type"], salon["channel_types"], etiquette["type"], retirer["type"]) == (7, [15], 3, 5) and all(not o.get("required") for o in command["options"])
    assert all(len(o["description"]) <= 100 for o in [command, *command["options"]]) and etiquette["max_length"] == 20          # (Discord: a label is 20 characters at most)


def test_a_moderator_chooses_the_forum_and_the_answer_says_so_privately(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM))
    assert f"<#{FORUM}>" in with_forum.sent.last() and "un post chacun" in with_forum.sent.last()
    assert with_forum.sent.calls[0][2]["data"]["flags"] == 64                                                  # only they see it
    assert forum.get(ingest_db, int(GUILD)) == forum.Forum(FORUM, "Débats", None, None)
    assert [c[:2] for c in with_forum.discord.calls] == [("GET", f"/channels/{FORUM}")]


@pytest.mark.parametrize(("permissions", "allowed"), [(MANAGE_MESSAGES, True), (ADMINISTRATOR, True), (None, False), (SEND_MESSAGES, False), (0, False)])
def test_only_a_moderator_can_choose_or_take_off_the_forum_but_anybody_can_look(with_forum, ingest_db, permissions, allowed):
    with_forum.forum(salon=str(FORUM), permissions=permissions)
    assert (forum.get(ingest_db, int(GUILD)) is not None) is allowed and ("modérateurs" in with_forum.sent.last()) is (not allowed)
    forum.save(ingest_db, int(GUILD), forum.Forum(FORUM, "Débats"))
    with_forum.forum(retirer=True, permissions=permissions)
    assert (forum.get(ingest_db, int(GUILD)) is None) is allowed
    with_forum.forum(permissions=permissions)
    assert "modérateurs" not in with_forum.sent.last() and ("aucun forum" in with_forum.sent.last().lower()) is allowed


def test_asking_without_an_option_shows_the_forum_or_says_there_is_none(with_forum, ingest_db):
    with_forum.forum(permissions=None)
    assert "Aucun forum n'est réglé" in with_forum.sent.last()
    forum.save(ingest_db, int(GUILD), forum.Forum(FORUM, "Débats", "t_pol", "Politique"))
    with_forum.forum(permissions=None)
    assert f"<#{FORUM}>" in with_forum.sent.last() and "étiquette « Politique »" in with_forum.sent.last() and "retirer" in with_forum.sent.last()


def test_the_label_is_found_by_its_name_and_a_label_that_does_not_exist_lists_the_ones_that_do(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM), etiquette="politique")
    assert forum.get(ingest_db, int(GUILD)) == forum.Forum(FORUM, "Débats", "t_pol", "Politique") and "réservée aux modérateurs" in with_forum.sent.last()
    forum.clear(ingest_db, int(GUILD))
    with_forum.forum(salon=str(FORUM), etiquette="sport")
    assert forum.get(ingest_db, int(GUILD)) is None and "« Économie »" in with_forum.sent.last() and "« Éducation »" in with_forum.sent.last()


def test_a_forum_that_requires_a_label_is_not_accepted_without_one(world, ingest_db):  # noqa: F811
    world.add_forum(FORUM, tags=TAGS, flags=16)
    world.forum(salon=str(FORUM))
    assert forum.get(ingest_db, int(GUILD)) is None and "exige une étiquette" in world.sent.last() and "« Religion »" in world.sent.last()
    world.forum(salon=str(FORUM), etiquette="économie")
    assert forum.get(ingest_db, int(GUILD)).tag_id == "t_eco"


@pytest.mark.parametrize("what", ["a text channel", "another server", "unreachable"])
def test_what_is_not_a_forum_of_this_server_is_refused(world, ingest_db, what):  # noqa: F811
    if what == "another server":
        world.add_forum(FORUM, tags=TAGS, guild="999")
    elif what == "unreachable":
        world.discord.fail("GET", f"/channels/{FORUM}", 403, code=50001)
    world.forum(salon=str(FORUM if what != "a text channel" else GENERAL))
    assert forum.get(ingest_db, int(GUILD)) is None
    assert ("ne peut pas lire" in world.sent.last()) is (what == "unreachable") and ("n'est pas un forum" in world.sent.last()) is (what != "unreachable")


def test_a_server_that_is_not_followed_cannot_have_a_forum(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM), guild="999")
    assert "salon d'un serveur" in with_forum.sent.last() and ingest_db.execute("SELECT count(*) FROM runtime_settings WHERE key LIKE 'debate_forum.%'").fetchone()[0] == 0


# --- a debate as a post of the forum -----------------------------------------------------------------------------------------


def test_a_debate_opened_in_a_thread_is_created_in_the_forum_as_a_post_with_its_launch_message_and_not_under_the_channel(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM), etiquette="Politique")
    with_forum.command(ALICE_ID)
    debate = only_debate(ingest_db)
    [post] = with_forum.discord.threads
    assert with_forum.discord.threads[post]["parent"] == FORUM and with_forum.discord.threads[post]["applied_tags"] == ["t_pol"]
    assert [c[:2] for c in with_forum.discord.calls[1:]] == [("GET", f"/channels/{FORUM}"), ("POST", f"/channels/{FORUM}/threads"), ("PUT", f"/channels/{post}/thread-members/@me")]   # (after `/dindon forum` itself)
    posted = [c for c in with_forum.discord.calls if c[0] == "POST"]
    assert [c[1] for c in posted] == [f"/channels/{FORUM}/threads"]                                              # one call: the post and its first message, nothing under #général
    assert not [c for c in with_forum.discord.calls if f"/channels/{GENERAL}/threads" in c[1]]
    assert (debate.thread_id, debate.question_message_id, debate.start_message_id, debate.in_thread, debate.channel_id) == (post, post, post, True, int(GENERAL))
    body = posted[0][2]
    assert body["name"] == texts.thread_name(TOPIC) and body["auto_archive_duration"] == 1440 and body["message"]["allowed_mentions"] == {"parse": []}
    [launch] = with_forum.discord.posted(post)
    assert TOPIC in launch["embeds"][0]["description"] and [b["label"] for b in launch["components"][0]["components"]] == ["Pour · 0", "Ne sait pas · 0", "Contre · 0"]
    assert f"<#{post}>" in with_forum.sent.last() and "forum" not in with_forum.sent.last().lower().replace("<#", "")                       # (no apology: it worked)
    run(with_forum.debates.tick())
    assert with_forum.debates.is_debate_thread(post) and not with_forum.debates.is_debate_thread(GENERAL)


def test_without_a_forum_nothing_changes_and_a_debate_is_a_thread_under_the_channel(with_forum, ingest_db):
    with_forum.command(ALICE_ID)
    [thread] = with_forum.discord.threads
    assert with_forum.discord.threads[thread]["parent"] == int(GENERAL) and not [c for c in with_forum.discord.calls if f"/channels/{FORUM}" in c[1]]


def test_the_popup_says_where_the_thread_will_be_made(with_forum, ingest_db):
    plain = fields_of(with_forum.ask(ALICE_ID))["thread"]
    forum.save(ingest_db, int(GUILD), forum.Forum(FORUM, "Débats"))
    popup = with_forum.ask(ALICE_ID, id="778")
    [field] = [f for f in popup["components"] if f["component"]["custom_id"] == "thread"]
    assert "forum « Débats »" in field["description"] and plain["default"] is True and len(field["description"]) <= 100


def test_a_debate_in_the_channel_or_asked_from_a_thread_ignores_the_forum(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM))
    with_forum.command(ALICE_ID, thread=False)
    assert with_forum.discord.threads == {} and only_debate(ingest_db).thread_id == int(GENERAL)
    ingest_db.execute("DELETE FROM debates")
    with_forum.command(BOB_ID, channel=THREAD, channel_type=11)
    assert with_forum.discord.threads == {} and only_debate(ingest_db).thread_id == int(THREAD)


def test_the_labels_of_an_axis_debate_are_the_chosen_one_and_the_ones_named_in_the_axis(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM), etiquette="Politique")
    with_forum.command(ALICE_ID, topic="", axis="religion")
    [post] = with_forum.discord.threads
    assert with_forum.discord.threads[post]["applied_tags"] == ["t_pol", "t_rel"]
    ingest_db.execute("DELETE FROM debates")
    with_forum.command(BOB_ID, topic="", axis="commerce")
    assert with_forum.discord.threads[max(with_forum.discord.threads)]["applied_tags"] == ["t_pol", "t_intl"]


def test_a_debate_on_a_subject_written_by_a_person_carries_only_the_chosen_label(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM), etiquette="Économie")
    with_forum.command(ALICE_ID)
    assert with_forum.discord.threads[max(with_forum.discord.threads)]["applied_tags"] == ["t_eco"]


def test_with_no_chosen_label_a_debate_carries_none_on_a_forum_that_does_not_ask(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM))
    with_forum.command(ALICE_ID)
    assert with_forum.discord.threads[max(with_forum.discord.threads)]["applied_tags"] == []


@pytest.mark.parametrize("failure", ["deleted", "not a forum any more", "refused", "label gone"])
def test_when_the_forum_does_not_work_the_debate_goes_in_a_thread_under_the_channel_and_the_author_is_told(with_forum, ingest_db, failure):
    with_forum.forum(salon=str(FORUM), etiquette="Politique")
    if failure == "deleted":
        with_forum.discord.delete_thread(FORUM)
    elif failure == "not a forum any more":
        with_forum.discord.forums[FORUM]["type"] = 0
    elif failure == "refused":
        with_forum.discord.fail("POST", f"/channels/{FORUM}/threads", 403, code=50013)
    else:
        forum.save(ingest_db, int(GUILD), forum.Forum(FORUM, "Débats", "t_old", "Ancienne"))
        with_forum.discord.forums[FORUM]["flags"] = 16                                                           # and the forum now wants a label that Dindon cannot name
        with_forum.discord.forums[FORUM]["available_tags"] = []
    with_forum.command(ALICE_ID)
    debate = only_debate(ingest_db)
    [thread] = with_forum.discord.threads
    assert with_forum.discord.threads[thread]["parent"] == int(GENERAL) and debate.status == "open" and debate.thread_id == thread
    assert "Le forum des débats n'a pas répondu" in with_forum.sent.last() and f"<#{thread}>" in with_forum.sent.last()


def test_the_launch_message_of_a_post_is_edited_like_any_other_and_the_post_is_archived_at_the_end(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM))
    with_forum.command(ALICE_ID)
    debate = only_debate(ingest_db)
    post = debate.thread_id
    run(with_forum.debates.tick())
    with_forum.write(post, BOB)
    with_forum.click(BOB_ID, post, debate.id, "pos", "for")
    with_forum.tick(seconds=6)
    assert [b["label"] for b in with_forum.discord.messages[(post, post)]["components"][0]["components"]] == ["Pour · 1", "Ne sait pas · 0", "Contre · 0"]
    with_forum.click(ALICE_ID, post, debate.id, "end", "now")
    with_forum.tick(seconds=1)
    assert len(with_forum.discord.posted(post, "Débat terminé")) == 1 and with_forum.discord.threads[post]["archived"] is True
    assert with_forum.discord.messages[(post, post)]["components"] == []


def test_a_post_deleted_on_discord_ends_its_debate(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM))
    with_forum.command(ALICE_ID)
    debate = only_debate(ingest_db)
    run(with_forum.debates.tick())
    with_forum.runner.handle(event("THREAD_DELETE", {"id": str(debate.thread_id), "guild_id": GUILD, "parent_id": str(FORUM), "type": 11}))
    with_forum.tick(seconds=1)
    assert store.get(ingest_db, debate.id).close_reason == "failed"


def test_a_person_who_already_has_a_debate_is_told_before_anything_is_made_in_the_forum(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM))
    with_forum.command(ALICE_ID)
    calls = len(with_forum.discord.calls)
    assert with_forum.ask(ALICE_ID) is None and "déjà un débat ouvert" in with_forum.sent.last() and len(with_forum.discord.calls) == calls


def test_what_is_kept_of_the_setting_is_the_channel_its_name_and_the_label_and_nothing_of_a_person(with_forum, ingest_db):
    with_forum.forum(salon=str(FORUM), etiquette="Religion")
    row = ingest_db.execute("SELECT value FROM runtime_settings WHERE key = %s", (f"debate_forum.{GUILD}",)).fetchone()[0]
    assert row == {"channel_id": str(FORUM), "name": "Débats", "tag_id": "t_rel", "tag_name": "Religion"} and str(ALICE_ID) not in str(row)
