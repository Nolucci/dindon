"""The check before production: it says what blocks, and it never writes anything nor shows the token. Level of proof: SIMULATED (fake Discord, real PostgreSQL)."""
import dataclasses

import pytest

from dindon.preflight import check_configuration, check_database, check_discord, check_runtime, render
from fake_discord import FakeDiscord
from synthetic import settings_for
from test_collector import TOKEN, world  # noqa: F401 (fixture)


@pytest.fixture
def discord(world):
    server = FakeDiscord(world, token=TOKEN, bot=True).start()
    server.bot_public = False                                                                         # a private bot: what is recommended
    yield server
    server.stop()


@pytest.fixture
def settings(discord, world, ingest_url, tmp_path):
    return dataclasses.replace(settings_for(ingest_url, tmp_path, "a long and unique password, not an example"), discord_api_url=discord.api_url, discord_token=TOKEN,
                               guild_ids=(world.guild_id,), retention_days=365)


STRONG_DATABASE = "postgresql://dindon:a-long-and-unique-database-password@127.0.0.1:5432/dindon"      # (the test database has a throwaway password: it would be flagged)


def levels(checks):
    return {(c.level, c.area) for c in checks}


def texts(checks, level):
    return " ".join(c.text for c in checks if c.level == level)


def test_a_good_configuration_blocks_nothing(settings):
    found = check_configuration(dataclasses.replace(settings, database_url=STRONG_DATABASE))
    assert not [c for c in found if c.level in ("fail", "warn")]


def test_what_blocks_is_told_in_words(settings):
    bare = dataclasses.replace(settings, password="demo", retention_days=0, discord_token="", guild_ids=(), follow_all=True)
    found = check_configuration(bare)
    assert "mot de passe d'exemple" in texts(found, "fail") and "Aucun jeton" in texts(found, "fail")
    assert "illimitée" in texts(found, "warn") and "tous" in texts(found, "warn")                     # not blocking, but to decide


def test_the_token_and_the_passwords_are_never_shown(settings):
    shown = render(check_configuration(settings) + check_discord(settings))
    assert TOKEN not in shown and settings.password not in shown


def test_discord_is_happy_with_a_private_bot_with_just_the_right_permissions(settings, discord):
    found = check_discord(settings)
    assert not [c for c in found if c.level in ("fail", "warn")], [c.text for c in found if c.level in ("fail", "warn")]
    assert "droits justes" in texts(found, "ok") and "/dindon" in texts(found, "ok")


def test_without_the_message_content_intent_it_blocks(settings, discord):
    discord.message_content = False
    assert "Message Content Intent" in texts(check_discord(settings), "fail")


def test_a_public_bot_and_too_many_permissions_are_flagged(settings, discord):
    discord.bot_public = True
    discord.permissions = 66560 | (1 << 3)                                                           # administrator
    assert "public" in texts(check_discord(settings), "warn") and "administrateur" in texts(check_discord(settings), "warn")
    discord.permissions = 66560 | (1 << 2) | (1 << 28)                                               # ban members, manage roles
    assert "bannir des membres" in texts(check_discord(settings), "warn")


def test_debates_need_more_rights_than_recording_and_the_check_says_so_without_blocking(settings, discord):
    found = check_discord(settings)                                                                  # the fake bot has the rights of the first invitation: see + read
    assert "`/dindon debat` ne marchera pas" in texts(found, "info") and "créer des fils publics" in texts(found, "info")
    assert not [c for c in found if c.level in ("fail", "warn")]                                      # recording works: nothing blocks
    discord.permissions = 66560 | (1 << 35) | (1 << 11) | (1 << 38) | (1 << 14)
    found = check_discord(settings)
    assert "peut ouvrir des débats" in texts(found, "ok") and "ne marchera pas" not in texts(found, "info")


def test_missing_permissions_and_a_missing_command_block(settings, discord):
    discord.permissions = 1 << 10                                                                    # can see the channels, cannot read the history
    discord.commands = []
    found = check_discord(settings)
    assert "lire l'historique" in texts(found, "fail") and "`/dindon` n'est pas enregistrée" in texts(found, "fail")


def test_a_listed_server_where_the_bot_is_not_blocks_and_an_unlisted_one_is_only_noted(settings, discord):
    found = check_discord(dataclasses.replace(settings, guild_ids=(settings.guild_ids[0], 123456789012345678)))
    assert "123456789012345678" in texts(found, "fail")
    discord.other_servers = [{"id": "999000000000000001", "name": "Zèbre"}]
    assert "ne le suit pas" in texts(check_discord(settings), "info")


def test_a_personal_account_blocks(settings, world):
    account = FakeDiscord(world, token=TOKEN, bot=False).start()
    try:
        assert "compte personnel" in texts(check_discord(dataclasses.replace(settings, discord_api_url=account.api_url)), "fail")
    finally:
        account.stop()


def test_the_database_part_says_what_is_waiting_and_that_the_folders_work(settings, ingest_db):
    found = check_database(settings, ingest_db)
    assert "à jour" in texts(found, "ok") and "inscriptible" in texts(found, "ok")
    ingest_db.execute("DELETE FROM schema_migrations WHERE name = '0014_decisive_thresholds.sql'")
    assert "0014_decisive_thresholds.sql" in texts(check_database(settings, ingest_db), "fail")


def test_the_bot_is_alive_only_when_it_gave_a_sign_lately(settings, ingest_db):
    assert "ne donne pas signe de vie" in texts(check_runtime(settings, ingest_db), "warn")
    ingest_db.execute("INSERT INTO service_status (name, updated_at, data) VALUES ('bot', now(), '{\"connected\": true, \"sessions\": 1, \"gaps\": 0}'::jsonb)")
    assert "vivant" in texts(check_runtime(settings, ingest_db), "ok")


def test_the_verdict_follows_what_blocks(settings):
    assert "NON" in render(check_configuration(dataclasses.replace(settings, password="demo")))
    assert "OUI" in render(check_configuration(dataclasses.replace(settings, database_url=STRONG_DATABASE)))


# --- the debates (docs/regles-du-bot.md) ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def ollama():
    from fake_ollama import FakeOllama

    server = FakeOllama(models=("qwen3:14b",)).start()
    yield server
    server.stop()


def debate_settings(settings, ollama=None, **options):
    from pathlib import Path  # noqa: F401

    return dataclasses.replace(settings, ollama_url=ollama.url if ollama is not None else settings.ollama_url, **options)


def debate_texts(checks, level):
    return " ".join(c.text for c in checks if c.level == level and c.area == "Débats")


def test_with_the_checks_off_the_preflight_says_that_nothing_is_read_and_nothing_leaves(settings):
    from dindon.preflight import check_debates

    [only] = check_debates(settings)
    assert only.level == "info" and "désactivée" in only.text and "aucun message de débat n'est lu" in only.text


def test_with_the_checks_on_it_says_what_will_be_sent_and_that_the_model_is_there(settings, ollama):
    from dindon.preflight import check_debates

    found = check_debates(debate_settings(settings, ollama, debate_checks="observe", searxng_url="http://searxng:8080", factcheck_api_key="SECRET-KEY"))
    assert "ACTIVE" in debate_texts(found, "warn") and "Fact Check Tools" in debate_texts(found, "warn") and "un SearXNG" in debate_texts(found, "warn")
    assert "est installé" in debate_texts(found, "ok") and "Mode observation" in debate_texts(found, "ok") and debate_texts(found, "fail") == ""
    assert "SECRET-KEY" not in render(found)                                                                 # the key is never printed


def test_it_blocks_when_the_checks_are_on_with_nothing_to_search_with_a_model_that_is_missing_or_ollama_away(settings, ollama):
    from dindon.preflight import check_debates

    assert "aucun service de recherche" in debate_texts(check_debates(debate_settings(settings, ollama, debate_checks="observe")), "fail")
    assert "n'est pas installé" in debate_texts(check_debates(debate_settings(settings, ollama, debate_checks="observe", searxng_url="http://x", debate_model="inconnu:1b")), "fail")
    assert "ne répond pas" in debate_texts(check_debates(debate_settings(settings, debate_checks="observe", searxng_url="http://x")), "fail")


def test_the_public_corrections_are_flagged_loudly_and_only_active_with_a_measured_precision(settings, ollama):
    from dindon.preflight import check_debates

    asked = dict(debate_checks="live", searxng_url="http://x")
    locked = check_debates(debate_settings(settings, ollama, **asked))
    assert "ne sont PAS actives" in debate_texts(locked, "warn") and "DINDON_DEBATE_PRECISION" in debate_texts(locked, "warn") and "CORRECTIONS PUBLIQUES sont actives" not in debate_texts(locked, "warn")
    under = check_debates(debate_settings(settings, ollama, debate_precision=0.8, **asked))
    assert "ne sont PAS actives" in debate_texts(under, "warn") and "seuil" in debate_texts(under, "warn")
    opened = check_debates(debate_settings(settings, ollama, debate_precision=0.95, **asked))
    assert "CORRECTIONS PUBLIQUES sont actives" in debate_texts(opened, "warn") and "0.95" in debate_texts(opened, "warn") and "ne sont PAS" not in debate_texts(opened, "warn")


def test_the_answer_level_says_that_dindon_speaks_without_a_source_and_works_without_a_search_service(settings, ollama):
    from dindon.preflight import check_debates

    with_search = debate_texts(check_debates(debate_settings(settings, ollama, debate_checks="answer", searxng_url="http://x")), "warn")
    assert "RÉPOND D'ABORD" in with_search and "sans source" in with_search and "Valide / Invalide" in with_search and "ne sont PAS actives" not in with_search
    alone = check_debates(debate_settings(settings, ollama, debate_checks="answer"))
    assert "aucun service de recherche" in debate_texts(alone, "warn") and "La vérification n'envoie rien à Internet" in debate_texts(alone, "warn") and debate_texts(alone, "fail") == ""
