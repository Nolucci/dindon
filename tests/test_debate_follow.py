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
