"""How much of the machine Dindon may use, at the cost of its speed. One place for the numbers, read again by the bot and by the analysis while they run.

* **The AI** (`ai_*`): `ai_max_load` is the share of the time that the models may work. After a call that took t seconds, the analysis waits
  t * (100 / load - 1) seconds before the next one: at 50 % it takes twice as long and the machine is idle half of the time; at 25 %, four times as
  long. `ai_threads` limits the threads of the models (0: Ollama decides), `ai_keep_alive` how long a model stays in memory after use (0: freed at once,
  but loaded again at the next call), `ai_batch` how many conversations are turned into vectors at a time.
* **The bot** (`bot_batch_seconds`): the messages of a channel wait this long and are written together. Longer means fewer writes to the database and
  less work for it, and a map that shows a new message later (the messages are never lost by it).

The values live in `runtime_settings` (key `performance`), changed from the page Système.
"""
from __future__ import annotations

import json
import os

import psycopg
from psycopg.rows import tuple_row

KEY = "performance"
KEEP_ALIVE = ("0", "30s", "5m", "10m", "30m")
LIMITS = {"ai_max_load": (10, 100), "ai_threads": (0, 64), "ai_batch": (1, 32), "bot_batch_seconds": (0.1, 10.0)}
MAX_PAUSE = 300.0       # seconds: a very slow setting never makes the analysis look dead for longer than this between two calls

DEFAULT = {"preset": "full", "ai_max_load": 100, "ai_threads": 0, "ai_keep_alive": "10m", "ai_batch": 16, "bot_batch_seconds": 0.3}
PRESETS = {
    "saver": {"ai_max_load": 25, "ai_threads": max(1, (os.cpu_count() or 4) // 4), "ai_keep_alive": "0", "ai_batch": 4, "bot_batch_seconds": 3.0},
    "balanced": {"ai_max_load": 60, "ai_threads": 0, "ai_keep_alive": "5m", "ai_batch": 8, "bot_batch_seconds": 1.0},
    "full": {k: v for k, v in DEFAULT.items() if k != "preset"},
}


def clean(values: dict) -> dict:
    """A complete, valid set of settings from what was given (what is missing, or out of range, becomes the default or the nearest allowed value)."""
    preset = values.get("preset")
    base = {**{k: v for k, v in DEFAULT.items() if k != "preset"}, **PRESETS.get(preset, {})}
    out = {"preset": preset if preset in PRESETS else "custom"}
    for key, (low, high) in LIMITS.items():
        raw = values.get(key, base[key]) if preset not in PRESETS else base[key]
        try:
            number = float(raw)
        except (TypeError, ValueError):
            number = float(base[key])
        number = min(max(number, low), high)
        out[key] = round(number, 2) if isinstance(low, float) else int(number)
    keep = values.get("ai_keep_alive", base["ai_keep_alive"]) if preset not in PRESETS else base["ai_keep_alive"]
    out["ai_keep_alive"] = keep if keep in KEEP_ALIVE else base["ai_keep_alive"]
    if out["preset"] == "custom":                                          # values that are exactly a preset's are that preset
        for name, wanted in PRESETS.items():
            if all(out[k] == (float(v) if isinstance(LIMITS.get(k, (0,))[0], float) else v) for k, v in wanted.items()):
                out["preset"] = name
                break
    return out


def load(conn: psycopg.Connection) -> dict:
    """The settings in force (the defaults when nothing was ever saved, or when the table is not there yet)."""
    try:
        with conn.cursor(row_factory=tuple_row) as cur:
            row = cur.execute("SELECT value FROM runtime_settings WHERE key = %s", (KEY,)).fetchone()
    except psycopg.errors.UndefinedTable:
        return clean({})
    return clean(row[0] if row else {})


def save(conn: psycopg.Connection, values: dict) -> dict:
    cleaned = clean(values)
    conn.execute("""INSERT INTO runtime_settings (key, value) VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""", (KEY, json.dumps(cleaned)))
    return cleaned


def pause_for(elapsed: float, max_load: int) -> float:
    """How long to wait after work that took `elapsed` seconds so that the work takes `max_load` percent of the time."""
    if max_load >= 100 or elapsed <= 0:
        return 0.0
    return min(elapsed * (100 / max(max_load, 1) - 1), MAX_PAUSE)
