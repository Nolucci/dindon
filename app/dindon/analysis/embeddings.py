"""Stage 3 of the cascade: the vector of each kept conversation.

The text that is embedded is what was said, in order, without the names of the people, and only the messages that say something.
Long conversations are embedded in bounded pieces and their vectors are combined, so their ends still affect the result.
"""
import logging
import math
import re
from collections.abc import Callable

import psycopg
from psycopg.rows import tuple_row

from dindon.analysis.ollama import Ollama, OllamaError
from dindon.analysis.chunks import pack_lines

log = logging.getLogger("dindon.analysis")

MAX_CHARS = 6000
BATCH = 16

_TODO = """
SELECT c.id FROM conversations c JOIN channels ch ON ch.id = c.channel_id
WHERE ch.guild_id = %(guild)s AND c.kept
  AND NOT EXISTS (SELECT 1 FROM conversation_embeddings e WHERE e.conversation_id = c.id AND e.model = %(model)s)
ORDER BY c.importance DESC, c.id
"""

_TEXTS = """
SELECT cm.conversation_id, m.content,
       COALESCE((SELECT array_agg(DISTINCT n) FROM mentions mn JOIN users u ON u.id = mn.user_id
                   LEFT JOIN members mem ON mem.user_id = u.id AND mem.guild_id = ch.guild_id
                   CROSS JOIN LATERAL unnest(ARRAY[mem.nickname, u.global_name, u.name]) AS n
                  WHERE mn.message_id = m.id AND n IS NOT NULL AND length(n) >= 2), ARRAY[]::text[]) AS names
FROM conversation_messages cm JOIN messages m ON m.id = cm.message_id
JOIN conversations c ON c.id = cm.conversation_id JOIN channels ch ON ch.id = c.channel_id
WHERE cm.conversation_id = ANY(%s) AND analysis_substantive(m.content)
ORDER BY cm.conversation_id, m.sent_at, m.id
"""

_URL, _EMOJI, _MENTION, _SPACES = re.compile(r"https?://\S+"), re.compile(r"<a?:\w+:\d+>"), re.compile(r"@\S+"), re.compile(r"\s+")


def clean_text(content: str, names: list[str]) -> str:
    """A message as the analysis reads it: without links, custom emoji, and mentions. A mention is "@" and the name of a person, which
    can have several words ("@Jean Dupont"): the names of the people that the message mentions are removed whole (longest first), and
    whatever else follows an "@" is removed up to the next space."""
    for name in sorted(names, key=len, reverse=True):
        content = re.sub("@" + re.escape(name), " ", content, flags=re.IGNORECASE)
    for pattern in (_URL, _EMOJI, _MENTION):
        content = pattern.sub(" ", content)
    return _SPACES.sub(" ", content).strip()


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def conversation_chunks(conn: psycopg.Connection, ids: list[int]) -> dict[int, list[str]]:
    """All substantive text, cleaned and bounded for the embedding model."""
    parts: dict[int, list[str]] = {}
    with conn.cursor(row_factory=tuple_row) as cursor:
        for cid, content, names in cursor.execute(_TEXTS, (ids,)).fetchall():
            text = clean_text(content, names)
            if text:
                parts.setdefault(cid, []).append(text)
    return {cid: pack_lines(texts, MAX_CHARS) for cid, texts in parts.items()}


def conversation_texts(conn: psycopg.Connection, ids: list[int]) -> dict[int, str]:
    """A bounded opening excerpt for topic names; full text is used for the vector."""
    return {cid: chunks[0] for cid, chunks in conversation_chunks(conn, ids).items() if chunks}


def _combined(vectors: list[list[float]], weights: list[int]) -> list[float]:
    total = [sum(vector[i] * weight for vector, weight in zip(vectors, weights, strict=True)) for i in range(len(vectors[0]))]
    norm = math.sqrt(sum(value * value for value in total))
    return [value / norm for value in total] if norm else total


def embed_conversations(conn: psycopg.Connection, client: Ollama, model: str, guild_id: int, *, limit: int | None = None, batch: Callable[[], int] | int = BATCH,
                        progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Computes and stores the vector of the kept conversations that have none for `model`. Returns what was done."""
    todo = [row[0] for row in conn.execute(_TODO, {"guild": guild_id, "model": model}).fetchall()]
    if limit is not None:
        todo = todo[:limit]
    if progress:
        progress(0, len(todo))
    done = 0
    start = 0
    while start < len(todo):
        if cancelled():
            break
        size = max(1, batch() if callable(batch) else batch)       # the size of a batch is a setting that can change while this runs
        ids = todo[start:start + size]
        chunks = conversation_chunks(conn, ids)
        ids = [i for i in ids if chunks.get(i)]
        if ids:
            pieces = [(cid, text) for cid in ids for text in chunks[cid]]
            by_id: dict[int, list[tuple[list[float], int]]] = {cid: [] for cid in ids}
            for offset in range(0, len(pieces), size):
                group = pieces[offset:offset + size]
                vectors = client.embed(model, [text for _, text in group])
                for (cid, piece), vector in zip(group, vectors, strict=True):
                    if len(vector) != 1024:
                        raise OllamaError(f"Le modèle de vecteurs « {model} » en donne de {len(vector)} nombres : la base en attend 1024 "
                                          "(schema-vector.sql). Choisissez un modèle à 1024 dimensions, comme bge-m3.")
                    by_id[cid].append((vector, len(piece)))
            with conn.transaction():
                for cid in ids:
                    parts = by_id[cid]
                    vector = _combined([part[0] for part in parts], [part[1] for part in parts])
                    conn.execute("INSERT INTO conversation_embeddings (conversation_id, model, embedding) VALUES (%s, %s, %s::vector) "
                                 "ON CONFLICT DO NOTHING", (cid, model, vector_literal(vector)))
        done += len(ids)
        start += size
        if progress:
            progress(min(start, len(todo)), len(todo))
    log.info("embeddings: %d conversations done with %s (of %d waiting)", done, model, len(todo))
    return {"done": done, "waiting": len(todo)}
