"""Real database and bot handlers; Discord publication is simulated locally."""
from dindon import automation, privacy
from dindon.analysis.axes import assign_axes
from dindon.debate import forum, polls, store
from test_debate_bot import ALICE_ID, BOB_ID, GENERAL, GUILD, MANAGE_MESSAGES, Debates, only_debate, run, world  # noqa: F401

POLL_CHANNEL = 700


def setup(world):
    world.add_forum(300, tags=(("politique", "Politique"),))
    world.forum(salon="300", sondages=str(POLL_CHANNEL), permissions=MANAGE_MESSAGES)


def poll_row(conn, debate_id):
    return conn.execute("SELECT debate_id, channel_id, message_id, question, description, revision FROM debate_polls WHERE debate_id = %s", (debate_id,)).fetchone()


def test_param_saves_both_destinations_and_invalid_input_saves_neither(world, ingest_db):
    world.add_forum(300, tags=(("politique", "Politique"),))
    world.discord.fail("GET", f"/channels/{POLL_CHANNEL}", 403)
    world.forum(salon="300", sondages=str(POLL_CHANNEL))
    assert forum.get(ingest_db, int(GUILD)) is None
    assert forum.poll_channel(ingest_db, int(GUILD)) is None
    setup(world)
    assert forum.get(ingest_db, int(GUILD)).channel_id == 300
    assert forum.poll_channel(ingest_db, int(GUILD)) == POLL_CHANNEL
    world.forum(retirer=True)
    assert forum.get(ingest_db, int(GUILD)) is None and forum.poll_channel(ingest_db, int(GUILD)) is None


def test_poll_has_three_choices_explanations_and_the_forum_post_link(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic="", axis="religion")
    debate = only_debate(ingest_db)
    row = poll_row(ingest_db, debate.id)
    message = world.discord.messages[(POLL_CHANNEL, row[2])]
    assert [b['label'] for b in message['components'][0]['components']] == ['Pour · 0', 'Ne sait pas · 0', 'Contre · 0']
    embed = message['embeds'][0]
    assert len(embed['title']) <= 256 and embed['title'].endswith('?')
    assert f'https://discord.com/channels/{GUILD}/{debate.thread_id}' in embed['description']
    assert debate.axis['for'] in embed['title'] and debate.axis['against'] in embed['title']
    assert row[4]  # The definitions of the two poles clarify the question even without the model.


def test_votes_in_either_place_are_shared_and_update_the_card_axes_without_double_counting(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic="", axis="religion")
    debate = only_debate(ingest_db)
    world.click(BOB_ID, POLL_CHANNEL, debate.id, 'pos', 'for')
    axis_id = ingest_db.execute("SELECT id FROM axes WHERE code = 'religion'").fetchone()[0]
    def score():
        return ingest_db.execute('SELECT score, n_propositions FROM person_axis_scores WHERE guild_id = %s AND user_id = %s AND axis_id = %s', (int(GUILD), BOB_ID, axis_id)).fetchone()
    assert score()[0] < 0 and score()[1] == 1
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'for')
    assert score()[1] == 1
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'against')
    assert score()[0] > 0 and score()[1] == 1
    world.tick(seconds=6)
    row = poll_row(ingest_db, debate.id)
    assert [b['label'] for b in world.discord.messages[(POLL_CHANNEL, row[2])]['components'][0]['components']] == ['Pour · 0', 'Ne sait pas · 0', 'Contre · 1']
    world.click(BOB_ID, POLL_CHANNEL, debate.id, 'pos', 'unsure')
    assert score() is None


def test_free_subject_votes_are_pending_for_analysis_and_use_the_result(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic="Faut-il augmenter les impôts ?")
    debate = only_debate(ingest_db)
    world.click(BOB_ID, POLL_CHANNEL, debate.id, 'pos', 'for')
    assert automation.pending(ingest_db, int(GUILD), 'test')['unlinked'] == 1
    pole = ingest_db.execute("SELECT negative_pole FROM axes WHERE code = 'controle'").fetchone()[0]
    class Model:
        def chat_json(self, model, system, user, schema):
            return {'axes': [{'axis': 'controle', 'toward': pole, 'strength': 'forte'}]}
    result = assign_axes(ingest_db, Model(), 'test', int(GUILD))
    assert result['done'] == 1
    axis = ingest_db.execute("SELECT id FROM axes WHERE code = 'controle'").fetchone()[0]
    assert ingest_db.execute('SELECT score FROM person_axis_scores WHERE user_id = %s AND axis_id = %s', (BOB_ID, axis)).fetchone()[0] < 0



def test_failed_publication_restarts_and_closure_disables_votes(world, ingest_db):
    setup(world)
    world.discord.fail('POST', f'/channels/{POLL_CHANNEL}/messages', 503)
    world.command(ALICE_ID, topic='', axis='religion')
    debate = only_debate(ingest_db)
    assert poll_row(ingest_db, debate.id)[2] is None
    restarted = Debates(world.url, world.discord, clock=world.time.now, mono=world.time.tick)
    run(restarted.tick())
    row = poll_row(ingest_db, debate.id)
    assert row[2] and len(world.discord.posted(POLL_CHANNEL)) == 1
    world.click(ALICE_ID, debate.thread_id, debate.id, 'end', 'now', permissions=8)
    world.tick(seconds=6)
    assert world.discord.messages[(POLL_CHANNEL, row[2])]['components'] == []
    world.click(BOB_ID, POLL_CHANNEL, debate.id, 'pos', 'for')
    assert store.positions(ingest_db, debate.id) == {}


def test_deleted_poll_is_recreated_and_privacy_applies_to_votes_and_settings(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic='', axis='religion')
    debate = only_debate(ingest_db)
    row = poll_row(ingest_db, debate.id)
    world.discord.messages.pop((POLL_CHANNEL, row[2]))
    world.debates.on_delete({'channel_id': str(POLL_CHANNEL)}, [str(row[2])])
    world.tick(seconds=6)
    assert poll_row(ingest_db, debate.id)[2] != row[2]
    privacy.stop_recording(ingest_db, BOB_ID)
    world.click(BOB_ID, POLL_CHANNEL, debate.id, 'pos', 'for')
    assert store.positions(ingest_db, debate.id) == {}
    privacy.release(ingest_db, BOB_ID)
    world.click(BOB_ID, POLL_CHANNEL, debate.id, 'pos', 'for')
    privacy.erase_person(ingest_db, BOB_ID)
    assert store.positions(ingest_db, debate.id) == {}
    assert not ingest_db.execute('SELECT 1 FROM person_axis_scores WHERE user_id = %s', (BOB_ID,)).fetchone()
    privacy.erase_server(ingest_db, int(GUILD))
    assert forum.poll_channel(ingest_db, int(GUILD)) is None
    assert poll_row(ingest_db, debate.id) is None
