"""Approval before publication and private live debate summaries."""
import json

import pytest

from dindon.debate import polls, store
from test_debate_bot import ALICE_ID, BOB_ID, GENERAL, GUILD, button, debat, only_debate, run, world  # noqa: F401

QUESTION = 'Faut-il instaurer une semaine de travail de quatre jours en France ?'
DESCRIPTION = 'Le débat porte sur la réduction du nombre de jours travaillés en France, sans baisse de salaire.'


class Model:
    def __init__(self):
        self.calls = []

    def chat_json(self, model, system, user, schema):
        self.calls.append(json.loads(user))
        return {'question': QUESTION, 'description': DESCRIPTION}


def preview(world):
    world.debates.poll_client = Model()
    popup = world.ask(topic='La semaine de quatre jours')
    world.submit(ALICE_ID, popup, context='En France, sans baisse de salaire.', confirm=False)
    return next(iter(world.debates._drafts))


def follow(world, channel=GENERAL, number=None, guild=GUILD):
    data = debat(BOB_ID, channel=channel, guild=guild)
    data['data']['options'] = [{'type': 1, 'name': 'suivi', 'options': [{'name': 'debat', 'value': number}] if number else []}]
    run(world.interactions.answer(data))
    body = world.sent.calls[-1][2]
    return body.get('data', body)


def test_proposal_is_private_and_nothing_exists_until_author_confirms(world, ingest_db):
    token = preview(world)
    assert ingest_db.execute('SELECT count(*) FROM debates').fetchone()[0] == 0
    assert world.discord.calls == []
    proposal = world.sent.calls[-1][2]
    assert QUESTION in proposal['embeds'][0]['description'] and DESCRIPTION in proposal['embeds'][0]['description']
    assert [b['label'] for b in proposal['components'][0]['components']] == ['Ouvrir le débat', 'Annuler']
    assert world.sent.calls[-2][2]['data']['flags'] == 64
    world.confirm(BOB_ID, token=token)
    world.confirm(ALICE_ID, token=token, guild='123')
    assert not world.discord.calls
    world.confirm(ALICE_ID, token=token)
    debate = only_debate(ingest_db)
    assert (debate.topic, debate.context, debate.status) == (QUESTION, DESCRIPTION, 'open')
    assert len(world.debates.poll_client.calls) == 1
    assert not world.sent.calls[-1][2]['components'] and not world.sent.calls[-1][2]['embeds']
    launch = world.discord.posted(debate.thread_id)[0]
    assert all(':end:' not in b['custom_id'] for row in launch['components'] for b in row['components'])
    world.confirm(ALICE_ID, token=token)
    assert ingest_db.execute('SELECT count(*) FROM debates').fetchone()[0] == 1


@pytest.mark.parametrize('action', ['cancel', 'expired', 'restart'])
def test_cancel_expiry_and_restart_never_publish(world, ingest_db, action):
    token = preview(world)
    if action == 'expired':
        world.time.advance(minutes=16)
    elif action == 'restart':
        world.restart()
    world.confirm(ALICE_ID, token=token, action='cancel' if action == 'cancel' else 'confirm')
    assert ingest_db.execute('SELECT count(*) FROM debates').fetchone()[0] == 0
    assert not world.discord.calls


def test_limits_and_privacy_are_checked_again_at_confirmation(world, ingest_db):
    from dindon import privacy
    token = preview(world)
    privacy.stop_recording(ingest_db, ALICE_ID)
    world.confirm(ALICE_ID, token=token)
    assert ingest_db.execute('SELECT count(*) FROM debates').fetchone()[0] == 0
    assert not world.discord.calls


@pytest.mark.parametrize('value', [None, {}, {'question': 'Sans point d’interrogation', 'description': DESCRIPTION}, {'question': QUESTION, 'description': ''}])
def test_invalid_or_unavailable_model_does_not_open_debate(world, ingest_db, value):
    class BadModel:
        def chat_json(self, *args):
            return value
    world.debates.poll_client = None if value is None else BadModel()
    world.submit(ALICE_ID, world.ask(), confirm=False)
    assert not world.debates._drafts and not world.discord.calls
    assert ingest_db.execute('SELECT count(*) FROM debates').fetchone()[0] == 0
    assert 'n’a pas pu' in world.sent.last()


def test_follow_flushes_votes_and_messages_without_closing_or_replacing_launch(world, ingest_db):
    world.command()
    debate = only_debate(ingest_db)
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'for')
    world.write(debate.thread_id)
    world.time.advance(minutes=2)
    payload = follow(world, channel=str(debate.thread_id))
    embed = payload['embeds'][0]
    assert 'Débat en cours' in embed['title']
    assert 'Pour **1**' in embed['description'] and '**1** message(s)' in embed['description'] and '**2 min**' in embed['description']
    assert store.get(ingest_db, debate.id).status == 'open'
    world.click(ALICE_ID, debate.thread_id, debate.id, 'end', 'now', permissions=8)
    assert store.get(ingest_db, debate.id).status == 'open'
    assert world.discord.posted(debate.thread_id)[0]['embeds'][0]['title'] == '🗳️ Débat'
    payload = follow(world, number=debate.id, guild='123')
    assert not payload.get('embeds') and debate.topic not in payload['content']
    data = button(BOB_ID, GENERAL, f'dindon:debat:stats:{debate.id}:0')
    data['guild_id'] = '123'
    run(world.interactions.answer(data))
    assert world.sent.calls[-1][2]['data']['content']


def test_follow_offers_open_debates_and_closed_debate_remains_accessible(world, ingest_db):
    world.command(ALICE_ID)
    world.command(BOB_ID)
    payload = follow(world)
    assert payload['content'] == 'Choisissez un débat.'
    assert len(payload['components'][0]['components']) == 2
    first = ingest_db.execute('SELECT id, thread_id FROM debates ORDER BY id LIMIT 1').fetchone()
    world.end(ALICE_ID, first[1], first[0], permissions=8)
    payload = follow(world, channel=str(first[1]))
    assert payload['embeds'][0]['title'] == '🏁 Débat terminé'


def end_by_command(world, user=ALICE_ID, *, channel=GENERAL, number=None, permissions=None):
    data = debat(user, channel=channel)
    data['data']['options'] = [{'type': 1, 'name': 'terminer', 'options': [{'name': 'debat', 'value': number}] if number else []}]
    if permissions is not None:
        data['member']['permissions'] = str(permissions)
    run(world.interactions.answer(data))
    body = world.sent.calls[-1][2]
    return body.get('data', body)


@pytest.mark.parametrize('from_thread', [False, True])
def test_author_can_close_existing_debate_and_open_another_without_losing_votes(world, ingest_db, from_thread):
    world.command()
    debate = only_debate(ingest_db)
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'for')
    world.discord.say(debate.thread_id, {'id': str(BOB_ID)})
    world.ask()
    assert '/dindon terminer' in world.sent.last()
    assert f'https://discord.com/channels/{GUILD}/{debate.thread_id}' in world.sent.last()
    # An existing debate is found even after restarting, before the first tick.
    world.restart()
    world.write(debate.thread_id)
    payload = end_by_command(world, channel=str(debate.thread_id) if from_thread else GENERAL)
    assert 'débat est terminé' in payload['content']
    assert not payload['components']
    assert store.get(ingest_db, debate.id).status == 'closed'
    assert store.position_counts(ingest_db, debate.id)['for'] == 1
    assert store.summary(ingest_db, debate.id)['messages'] == 2
    world.tick(seconds=6)
    assert len(world.discord.posted(debate.thread_id, 'Débat terminé')) == 1
    world.command(topic='Faut-il augmenter les congés ?')
    assert ingest_db.execute("SELECT count(*) FROM debates WHERE status = 'open'").fetchone()[0] == 1
    assert ingest_db.execute('SELECT count(*) FROM debates').fetchone()[0] == 2


@pytest.mark.parametrize('by_number', [False, True])
def test_other_participant_cannot_close_debate(world, ingest_db, by_number):
    world.command()
    debate = only_debate(ingest_db)
    world.click(BOB_ID, debate.thread_id, debate.id, 'pos', 'for')
    payload = end_by_command(world, BOB_ID, channel=GENERAL if by_number else str(debate.thread_id), number=debate.id if by_number else None)
    assert 'auteur' in payload['content']
    assert store.get(ingest_db, debate.id).status == 'open'


def test_moderator_must_choose_between_multiple_debates_and_can_close_one(world, ingest_db):
    from test_debate_bot import CAROL_ID
    world.command()
    world.command(BOB_ID)
    rows = ingest_db.execute('SELECT id FROM debates ORDER BY id').fetchall()
    payload = end_by_command(world, CAROL_ID, permissions=8)
    assert '/dindon terminer debat:NUMÉRO' in payload['content'] and not payload['components']
    assert len(store.active(ingest_db)) == 2
    end_by_command(world, CAROL_ID, number=rows[0][0], permissions=8)
    assert store.get(ingest_db, rows[0][0]).status == 'closed'
    assert store.get(ingest_db, rows[1][0]).status == 'open'


def test_end_command_cannot_close_foreign_or_unknown_debate(world, ingest_db):
    other = store.start(ingest_db, guild_id=123, channel_id=456, topic='Un autre débat', created_by=BOB_ID)
    other = store.attach_thread(ingest_db, other.id, thread_id=789, question_message_id=999)
    payload = end_by_command(world, number=other.id, permissions=8)
    assert 'existe' in payload['content'] and store.get(ingest_db, other.id).status == 'open'
    payload = end_by_command(world, number=other.id + 1000, permissions=8)
    assert 'existe' in payload['content']


def test_end_command_with_no_debate_or_closed_debate_changes_nothing(world, ingest_db):
    assert 'aucun débat ouvert' in end_by_command(world)['content']
    world.command()
    debate = only_debate(ingest_db)
    end_by_command(world, number=debate.id)
    assert 'Ce débat est terminé' in end_by_command(world, number=debate.id)['content']



def test_failed_history_recovery_leaves_debate_open_for_retry(world, ingest_db):
    world.command()
    debate = only_debate(ingest_db)
    world.restart()
    world.discord.fail('GET', f'/channels/{debate.thread_id}/messages.*', 503)
    payload = end_by_command(world)
    assert 'Réessayez' in payload['content']
    assert store.get(ingest_db, debate.id).status == 'open'
    end_by_command(world)
    assert store.get(ingest_db, debate.id).status == 'closed'
