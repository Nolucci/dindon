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
    assert [a['poll_media']['text'] for a in message['poll']['answers']] == ['Pour', 'Ne sait pas', 'Contre']
    assert message['poll']['allow_multiselect'] is False
    assert not message.get('components')
    question = message['poll']['question']['text']
    assert len(question) <= 256 and question.endswith('?')
    assert f'https://discord.com/channels/{GUILD}/{debate.thread_id}' in message['content']
    assert debate.axis['for'] in question and debate.axis['against'] in question
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
    assert store.position_counts(ingest_db, debate.id)['against'] == 1
    assert not world.discord.of('PATCH', f'/messages/{row[2]}')
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
    world.end(ALICE_ID, debate.thread_id, debate.id, permissions=8)
    world.tick(seconds=6)
    assert world.discord.of('POST', f'/polls/{row[2]}/expire')
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


def native_vote(world, debate, row, position, added=True, user=BOB_ID):
    mapping = world.debates._db(lambda c: c.execute('SELECT answer_ids FROM debate_polls WHERE debate_id = %s', (debate.id,)).fetchone()[0])
    answer = next(key for key, value in mapping.items() if value == position)
    world.debates.on_poll_vote(dict(guild_id=GUILD, channel_id=str(POLL_CHANNEL), message_id=str(row[2]), user_id=str(user), answer_id=answer), added)


def test_native_vote_change_withdrawal_and_old_removal(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic='', axis='religion')
    debate = only_debate(ingest_db)
    row = poll_row(ingest_db, debate.id)
    native_vote(world, debate, row, 'for')
    world.tick(seconds=6)
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'for'
    native_vote(world, debate, row, 'for', False)
    native_vote(world, debate, row, 'against')
    world.tick(seconds=6)
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'against'
    # A later choice in the debate survives removing the earlier native vote.
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'unsure')
    native_vote(world, debate, row, 'against', False)
    world.tick(seconds=6)
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'unsure'
    native_vote(world, debate, row, 'for')
    world.tick(seconds=6)
    native_vote(world, debate, row, 'for', False)
    world.tick(seconds=6)
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'witness'


def test_native_votes_recovered_after_restart_with_pagination(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic='', axis='religion')
    debate = only_debate(ingest_db)
    row = poll_row(ingest_db, debate.id)
    mapping = ingest_db.execute('SELECT answer_ids FROM debate_polls WHERE debate_id = %s', (debate.id,)).fetchone()[0]
    answer = int(next(k for k, v in mapping.items() if v == 'for'))
    world.discord.voters = {(row[2], answer): [{'id': str(BOB_ID + i), 'username': f'voter{i}'} for i in range(101)]}
    restarted = Debates(world.url, world.discord, clock=world.time.now, mono=world.time.tick)
    run(restarted.tick())
    assert len(store.positions(ingest_db, debate.id)) == 101
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'for'
    privacy.stop_recording(ingest_db, BOB_ID)
    privacy.erase_person(ingest_db, BOB_ID)
    restarted.note_gap()
    run(restarted.tick())
    assert BOB_ID not in store.positions(ingest_db, debate.id)


def test_join_invites_once_retries_and_skips_chosen_camp(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    event = {'id': str(debate.thread_id), 'added_members': [{'user_id': str(BOB_ID), 'member': {'user': {'id': str(BOB_ID)}}}]}
    world.discord.fail('POST', f'/channels/{debate.thread_id}/messages', 503)
    world.debates.on_members(event)
    world.tick(seconds=6)
    assert not ingest_db.execute('SELECT 1 FROM debate_welcomes').fetchone()
    world.tick(seconds=60)
    invites = [m for m in world.discord.posted(debate.thread_id) if f'<@{BOB_ID}>' in m.get('content', '')]
    assert len(invites) == 1
    assert invites[0]['allowed_mentions'] == {'parse': [], 'users': [str(BOB_ID)]}
    assert len(invites[0]['components'][0]['components']) == 3
    world.debates.on_members(event)
    world.tick(seconds=6)
    assert len([m for m in world.discord.posted(debate.thread_id) if f'<@{BOB_ID}>' in m.get('content', '')]) == 1
    restarted = Debates(world.url, world.discord, clock=world.time.now, mono=world.time.tick)
    run(restarted.load())
    restarted.on_members(event)
    run(restarted.tick())
    assert len([m for m in world.discord.posted(debate.thread_id) if f'<@{BOB_ID}>' in m.get('content', '')]) == 1
    world.click(ALICE_ID, debate.thread_id, debate.id, 'pos', 'for')
    world.debates.on_members({'id': str(debate.thread_id), 'added_members': [{'user_id': str(ALICE_ID)}]})
    world.tick(seconds=6)
    assert not any(f'<@{ALICE_ID}>' in m.get('content', '') and 'Choisis ton camp' in m.get('content', '') for m in world.discord.posted(debate.thread_id))


def test_remove_before_add_across_ticks_records_new_choice_before_closure(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic='', axis='religion')
    debate = only_debate(ingest_db)
    row = poll_row(ingest_db, debate.id)
    world.click(ALICE_ID, debate.thread_id, debate.id, 'pos', 'against')
    native_vote(world, debate, row, 'for')
    world.tick(seconds=6)
    mapping = ingest_db.execute('SELECT answer_ids FROM debate_polls WHERE debate_id = %s', (debate.id,)).fetchone()[0]
    answer = int(next(k for k, v in mapping.items() if v == 'unsure'))
    world.discord.voters = {(row[2], answer): [{'id': str(BOB_ID), 'username': 'Bob'}]}
    native_vote(world, debate, row, 'for', False)
    world.tick(seconds=6)
    assert store.get(ingest_db, debate.id).status == 'closed'  # The last member leaving a camp ends the debate.
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'unsure'
    native_vote(world, debate, row, 'unsure')
    world.tick(seconds=6)
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'unsure'


def test_existing_button_poll_becomes_native_without_erasing_positions(world, ingest_db):
    setup(world)
    world.command(ALICE_ID, topic='', axis='religion')
    debate = only_debate(ingest_db)
    row = poll_row(ingest_db, debate.id)
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'for')
    ingest_db.execute('UPDATE debate_polls SET answer_ids = NULL, dirty = true WHERE debate_id = %s', (debate.id,))
    world.tick(seconds=6)
    new = poll_row(ingest_db, debate.id)
    assert new[2] != row[2]
    assert 'poll' in world.discord.messages[(POLL_CHANNEL, new[2])]
    assert store.positions(ingest_db, debate.id)[BOB_ID] == 'for'
