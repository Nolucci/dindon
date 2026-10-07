"""The server and a helper computer work at the same time: the loop that asks the model, and the pool that sends each call to the computer that is free.

Level of proof: SIMULATED (two fake Ollama, real database).
"""
import threading
import time

from dindon.analysis.conversations import build_conversations
from dindon.analysis.extraction import extract_claims
from dindon.analysis.ollama import Ollama, OllamaPool
from dindon.analysis.parallel import pipeline, workers_for
from fake_ollama import FakeOllama
from test_analysis import NOW, Talk, ingest
from test_extraction import ALICE, BOB, GUILD_ID, GOOD, SAYS_A, SAYS_B, SAYS_C


def test_the_items_are_worked_on_two_at_a_time_and_a_failure_is_given_back_not_raised():
    running, most = 0, 0
    lock = threading.Lock()

    def work(item):
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        time.sleep(0.15)
        with lock:
            running -= 1
        if item == 3:
            raise ValueError("no")
        return item * 10

    out = {item: (result, error) for item, result, error in pipeline(range(6), work, 2)}
    assert most == 2 and sorted(out) == [0, 1, 2, 3, 4, 5]
    assert out[4] == (40, None) and out[3][0] is None and isinstance(out[3][1], ValueError)


def test_nothing_new_is_started_once_cancelled():
    stop = threading.Event()
    started = []

    def work(item):
        started.append(item)
        stop.set()
        return item

    done = [item for item, _, _ in pipeline(range(10), work, 2, stop.is_set)]
    assert len(started) <= 2 and len(done) == len(started)


def test_one_computer_is_one_at_a_time_and_each_computer_that_has_the_model_adds_one():
    local, helper = FakeOllama().start(), FakeOllama().start()
    try:
        assert workers_for(Ollama(local.url), "qwen3:14b") == 1
        assert workers_for(OllamaPool(local.url, (helper.url,)), "qwen3:14b") == 2
        assert workers_for(OllamaPool(local.url, (helper.url,)), "a-model-nobody-has") == 1
    finally:
        local.stop()
        helper.stop()


def test_two_questions_at_once_go_to_two_computers_and_one_at_a_time_goes_to_the_helper():
    local, helper = FakeOllama().start(), FakeOllama().start()
    try:
        for fake in (local, helper):
            fake.chat_delay = 0.4
            fake.chat_handler = lambda body: {"claims": []}
        pool = OllamaPool(local.url, (helper.url,), timeout=5)
        pool.models()
        chats = lambda fake: sum(path == "/api/chat" for path, _ in fake.requests)  # noqa: E731
        pool.chat_json("qwen3:14b", "s", "u", {"type": "object"})
        assert (chats(helper), chats(local)) == (1, 0)                                              # alone: the helper, as before
        threads = [threading.Thread(target=pool.chat_json, args=("qwen3:14b", "s", "u", {"type": "object"})) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert (chats(helper), chats(local)) == (2, 1)                                              # together: one each
    finally:
        local.stop()
        helper.stop()


def test_the_conversations_are_read_by_both_computers_and_all_of_them_are_recorded(ingest_db):
    talk = Talk()
    ingest(ingest_db, [m for _ in range(4) for m in (talk.say(SAYS_A, ALICE, 60), talk.say(SAYS_B, BOB), talk.say(SAYS_C, ALICE))])
    assert build_conversations(ingest_db, GUILD_ID, now=NOW)["made"] == 4
    local, helper = FakeOllama().start(), FakeOllama().start()
    try:
        for fake in (local, helper):
            fake.chat_delay = 0.3
            fake.chat_handler = lambda body: {"claims": GOOD}
        pool = OllamaPool(local.url, (helper.url,), timeout=10)
        result = extract_claims(ingest_db, pool, "qwen3:14b", "bge-m3", GUILD_ID)
        assert result["done"] == 4 and result["failed"] == 0 and result["claims"] == 8
        assert any(path == "/api/chat" for path, _ in local.requests) and any(path == "/api/chat" for path, _ in helper.requests)
        assert ingest_db.execute("SELECT count(*) FROM conversation_extractions").fetchone()[0] == 4
        assert extract_claims(ingest_db, pool, "qwen3:14b", "bge-m3", GUILD_ID)["done"] == 0       # recorded: not read again
    finally:
        local.stop()
        helper.stop()
