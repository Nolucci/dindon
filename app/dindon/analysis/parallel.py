"""The part of a loop that asks the model, run on several machines at once; the database is only ever touched by the thread that calls.

Reading a conversation, checking a position, linking a proposition to the axes: each is one independent question to the model followed by a write. With the
server and a helper computer both available, two of them are in flight at the same time (the pool of `ollama.py` sends each call to the machine that is free).
"""
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

_END = object()


def workers_for(client, model: str) -> int:
    """Reserve work for reconnecting computers too; the dispatcher enforces one call per available host."""
    count = getattr(client, "capacity_for", None) or getattr(client, "parallelism_for", None)
    return max(1, count(model)) if callable(count) else 1


def pipeline(items: Iterable, work: Callable, workers: int, cancelled: Callable[[], bool] = lambda: False) -> Iterator[tuple]:
    """Runs `work(item)` for the items, `workers` at a time, and yields `(item, result, error)` in the order that they finish (`error` is the exception that `work`
    raised, `result` is None then). The items are taken one by one in the calling thread, so a generator may read the database to make them. Nothing new is started
    once `cancelled()`; what is running is waited for (the model client stops its own calls when the analysis is cancelled)."""
    source = iter(items)
    pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="analysis-work")
    pending: dict[Future, object] = {}
    try:
        while True:
            while len(pending) < workers and not cancelled():
                item = next(source, _END)
                if item is _END:
                    break
                pending[pool.submit(work, item)] = item
            if not pending:
                return
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                item = pending.pop(future)
                error = future.exception()
                yield item, (None if error else future.result()), error
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
