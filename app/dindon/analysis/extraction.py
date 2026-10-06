"""Stage 4-5 of the cascade: what each person claims, with proof.

A model reads one conversation at a time, with the people as P1, P2... (their names are not given: the position must come from what they
write), and lists for each person the positions that they take, each with a quote. **The code does not trust the model**:

* a claim is kept only if every quote it gives is copied from a message of THAT person in THIS conversation (word for word, ignoring
  case, spaces and punctuation at the edges); a quote that is not there, or a message of somebody else, is refused and counted;
* a claim with no valid proof at all is dropped; a position (for / nuanced / against) is only kept for an opinion;
* a message that is only irony or a question is not a position.

The proposition that a claim is about is written by the model in general terms ("L'État doit augmenter le SMIC"); it is matched to an
existing proposition when its vector is close enough (cosine >= `SAME_PROPOSITION`), else it becomes a new proposition, *proposed*: nothing
here validates a proposition. A conversation that was read is recorded and is not read again (so this can be stopped and resumed).

KNOWN WEAKNESS: a proposition worded in the opposite sense ("Il ne faut pas augmenter le SMIC") has a close vector and may be merged with
its opposite while the stance keeps the sense of the wording: the model is told to word every proposition in the positive sense, which
reduces the problem without removing it. What is measured is in docs/commandes.md.
"""
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import tuple_row

from dindon.analysis.chunks import split_long
from dindon.analysis.embeddings import vector_literal
from dindon.analysis.ollama import Ollama, OllamaError

log = logging.getLogger("dindon.analysis")

PROMPT_VERSION = "extract-4"
MAX_CHARS = 7000
SAME_PROPOSITION = 0.80
MAX_CLAIMS_PER_PERSON = 3
FAILURES_IN_A_ROW = 3

SYSTEM = (
    "Tu lis une conversation d'un salon Discord. Les participants sont P1, P2, etc. Tu notes les POSITIONS que chaque participant prend dans ses propres "
    "messages, jamais d'après ce que les autres disent de lui. Ne note QUE les positions sur des sujets politiques, économiques, sociaux ou de société "
    "(institutions, économie, Europe, immigration, écologie, sécurité, laïcité, défense, droits, technologie et société). Ne note PAS les goûts personnels, la météo, "
    "les jeux, les films, la cuisine, les questions, les demandes de source, les remarques sans position, les salutations.\n"
    "Pour chaque position :\n"
    "- `proposition` : une affirmation générale, comprise sans la conversation, formulée dans le sens POSITIF d'un changement ou d'une thèse "
    "(par exemple « L'État doit augmenter le SMIC », jamais « Il ne faut pas augmenter le SMIC »), en 15 mots au plus ; ce n'est PAS une copie du message, "
    "c'est la thèse générale que le message défend ou combat ;\n"
    "- `stance` : 1 s'il est d'accord avec cette proposition, -1 s'il est contre, 0 s'il nuance ou est partagé ;\n"
    "- `kind` : `opinion`, ou `humour` si le message est une ironie ou une blague (le participant peut y dire le contraire de ce qu'il pense : mets alors stance = null) ;\n"
    "- `confidence` : de 0 à 1, à quel point c'est net ;\n"
    "- `evidence` : une ou deux preuves, chacune avec `ref` (le numéro #n du message) et `quote`, un extrait de 5 à 15 mots COPIÉ MOT POUR MOT depuis ce message, "
    "écrit par le participant lui-même.\n"
    "Un participant qui ne prend pas de position n'apparaît pas. Une position sans preuve exacte sera refusée."
)
SCHEMA = {"type": "object", "properties": {"claims": {"type": "array", "items": {"type": "object", "properties": {
    "participant": {"type": "string"}, "proposition": {"type": "string"}, "stance": {"type": ["integer", "null"]},
    "kind": {"type": "string", "enum": ["opinion", "humour"]}, "confidence": {"type": "number"},
    "evidence": {"type": "array", "items": {"type": "object", "properties": {"ref": {"type": "integer"}, "quote": {"type": "string"}},
                                           "required": ["ref", "quote"]}}},
    "required": ["participant", "proposition", "stance", "kind", "confidence", "evidence"]}}}, "required": ["claims"]}

_TODO = """
SELECT c.id FROM conversations c JOIN channels ch ON ch.id = c.channel_id
WHERE ch.guild_id = %(guild)s AND c.kept AND c.participants >= 1
  AND NOT EXISTS (SELECT 1 FROM conversation_extractions e WHERE e.conversation_id = c.id)
ORDER BY c.importance DESC, c.id
"""
_MESSAGES = """
SELECT m.id, m.author_id, m.content, m.sent_at FROM conversation_messages cm JOIN messages m ON m.id = cm.message_id
JOIN users u ON u.id = m.author_id
WHERE cm.conversation_id = %s AND NOT u.is_bot AND m.type IN ('Default', 'Reply')
  AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = m.author_id)   -- somebody who asked to stop being recorded is not read
ORDER BY m.sent_at, m.id
"""
_URL, _SPACES = re.compile(r"https?://\S+"), re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip(" .…,;:!?\"'«»()[]-–—")


@dataclass
class Read:
    """A conversation as the model sees it, and what is needed to check its answer."""
    text: str
    people: dict[str, int]                  # "P1" -> user id
    messages: dict[int, tuple[int, str, object]]   # ref number -> (author id, content, when)
    message_ids: dict[int, int]             # ref number -> message id


def prepare(rows: list[tuple]) -> Read | None:
    """Prepare a small conversation for one model call (also used by validation tests)."""
    windows = prepare_windows(rows)
    return windows[0] if len(windows) == 1 else None


def prepare_windows(rows: list[tuple]) -> list[Read]:
    """Give every message a stable reference and send all its text in bounded windows."""
    people: dict[str, int] = {}
    label_of: dict[int, str] = {}
    windows: list[Read] = []
    lines: list[str] = []
    messages: dict[int, tuple[int, str, object]] = {}
    ids: dict[int, int] = {}
    size = 0
    number = 0

    def flush() -> None:
        nonlocal lines, messages, ids, size
        if lines:
            windows.append(Read("\n".join(lines), people.copy(), messages, ids))
        lines, messages, ids, size = [], {}, {}, 0

    for message_id, author, content, when in rows:
        text = _SPACES.sub(" ", _URL.sub(" ", content or "")).strip()
        if not text:
            continue
        if author not in label_of:
            label_of[author] = f"P{len(label_of) + 1}"
            people[label_of[author]] = author
        number += 1
        prefix = f"#{number} {label_of[author]}: "
        for piece in split_long(text, MAX_CHARS - len(prefix)):
            line = prefix + piece
            if lines and size + 1 + len(line) > MAX_CHARS:
                flush()
            lines.append(line)
            messages[number] = (author, piece, when)
            ids[number] = message_id
            size += len(line) + (1 if size else 0)
    flush()
    return windows


@dataclass
class Claim:
    user_id: int
    proposition: str
    stance: int | None
    kind: str
    text: str
    confidence: float
    evidence: list[tuple[int, str]]         # (ref number, quote as found in the message)


def validate(answer: dict, read: Read) -> tuple[list[Claim], int]:
    """The claims of `answer` that hold up, and how many were refused. This is where the model is not trusted."""
    kept: list[Claim] = []
    refused = 0
    per_person: dict[int, int] = {}
    for raw in answer.get("claims", []):
        if not isinstance(raw, dict):
            refused += 1
            continue
        user_id = read.people.get(str(raw.get("participant", "")).strip())
        proposition = _SPACES.sub(" ", str(raw.get("proposition", ""))).strip()
        kind = raw.get("kind")
        stance = raw.get("stance")
        if user_id is None or kind not in ("opinion", "fait", "question", "humour") or not proposition or len(proposition) > 300:
            refused += 1
            continue
        if kind == "opinion" and stance not in (-1, 0, 1):          # an opinion has a position; the others have none
            refused += 1
            continue
        if kind != "opinion":
            stance = None
        proofs: list[tuple[int, str]] = []
        for e in raw.get("evidence", []) if isinstance(raw.get("evidence"), list) else []:
            ref, quote = (e or {}).get("ref"), _SPACES.sub(" ", str((e or {}).get("quote", ""))).strip()
            message = read.messages.get(ref) if isinstance(ref, int) else None
            if message is None or message[0] != user_id or len(_norm(quote)) < 6 or _norm(quote) not in _norm(message[1]):
                continue                                                  # not a message of that person, or not in it
            if all(p[0] != ref for p in proofs):
                proofs.append((ref, quote[:400]))
        if not proofs or per_person.get(user_id, 0) >= MAX_CLAIMS_PER_PERSON:
            refused += 1
            continue
        per_person[user_id] = per_person.get(user_id, 0) + 1
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        kept.append(Claim(user_id, proposition, stance, kind, _SPACES.sub(" ", str(raw.get("claim", ""))).strip()[:400] or proposition, confidence, proofs))   # (`claim`: optional)
    return kept, refused


def _proposition_ids(conn: psycopg.Connection, client: Ollama, embed_model: str, texts: list[str], model: str) -> dict[str, int]:
    """The proposition (existing, or new and *proposed*) that each text is about."""
    out: dict[str, int] = {}
    unique = sorted(set(texts))
    vectors = client.embed(embed_model, unique) if unique else []
    for text, vector in zip(unique, vectors, strict=True):
        literal = vector_literal(vector)
        near = conn.execute("""SELECT proposition_id, 1 - (embedding <=> %s::vector) FROM proposition_embeddings WHERE model = %s
                               ORDER BY embedding <=> %s::vector LIMIT 1""", (literal, embed_model, literal)).fetchone()
        if near is not None and near[1] >= SAME_PROPOSITION:
            out[text] = near[0]
            continue
        pid = conn.execute("INSERT INTO propositions (text, created_by) VALUES (%s, %s) RETURNING id", (text, model)).fetchone()[0]
        conn.execute("INSERT INTO proposition_embeddings (proposition_id, model, embedding) VALUES (%s, %s, %s::vector)", (pid, embed_model, literal))
        out[text] = pid
    return out


def extract_claims(conn: psycopg.Connection, client: Ollama, model: str, embed_model: str, guild_id: int, *, limit: int | None = None,
                   progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Reads the kept conversations that were not read yet (the most important first). Returns what was done."""
    with conn.cursor(row_factory=tuple_row) as cur:
        todo = [r[0] for r in cur.execute(_TODO, {"guild": guild_id}).fetchall()]
    if limit is not None:
        todo = todo[:limit]
    done = kept = refused = failed = unread = in_a_row = 0
    for n, cid in enumerate(todo, 1):
        if cancelled():
            break
        with conn.cursor(row_factory=tuple_row) as cur:
            reads = prepare_windows(cur.execute(_MESSAGES, (cid,)).fetchall())
        if not reads:                                                     # nothing to read: recorded, not read again
            conn.execute("INSERT INTO conversation_extractions (conversation_id, model, prompt_version, claims, refused) VALUES (%s, %s, %s, 0, 0) "
                         "ON CONFLICT DO NOTHING", (cid, model, PROMPT_VERSION))
            unread += 1
            continue
        validated: list[tuple[Claim, Read]] = []
        bad = 0
        try:
            for read in reads:
                if cancelled():
                    break
                answer = client.chat_json(model, SYSTEM, "Conversation :\n" + read.text, SCHEMA)
                claims, refused_here = validate(answer, read)
                validated.extend((claim, read) for claim in claims)
                bad += refused_here
            if cancelled():
                break
            in_a_row = 0
        except OllamaError as error:
            failed += 1
            in_a_row += 1
            log.warning("extraction: conversation skipped (%s)", str(error)[:80])
            if in_a_row >= FAILURES_IN_A_ROW:
                raise
            continue
        with conn.transaction():
            ids = _proposition_ids(conn, client, embed_model, [c.proposition for c, _ in validated if c.stance is not None], model) if validated else {}
            reviewed = conn.execute("SELECT EXISTS (SELECT 1 FROM claims WHERE conversation_id = %s AND review_status <> 'auto')", (cid,)).fetchone()[0]
            stored = 0
            for c, read in validated:
                proposition_id = ids.get(c.proposition) if c.stance is not None else None
                proof_ids = [read.message_ids[ref] for ref, _ in c.evidence]
                if reviewed and conn.execute(
                    """SELECT EXISTS (SELECT 1 FROM claims cl JOIN claim_evidence e ON e.claim_id = cl.id
                       WHERE cl.conversation_id = %s AND cl.user_id = %s AND cl.review_status <> 'auto'
                         AND cl.kind = %s AND cl.proposition_id IS NOT DISTINCT FROM %s AND e.message_id = ANY(%s))""",
                    (cid, c.user_id, c.kind, proposition_id, proof_ids),
                ).fetchone()[0]:
                    continue
                first = min(read.messages[ref][2] for ref, _ in c.evidence)
                claim_id = conn.execute(
                    """INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version, conversation_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (guild_id, c.user_id, proposition_id, c.kind, c.text, c.stance, c.confidence, first,
                     model, PROMPT_VERSION, cid)).fetchone()[0]
                stored += 1
                for ref, quote in c.evidence:
                    conn.execute("INSERT INTO claim_evidence (claim_id, message_id, quote) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                                 (claim_id, read.message_ids[ref], quote))
            conn.execute("INSERT INTO conversation_extractions (conversation_id, model, prompt_version, claims, refused) VALUES (%s, %s, %s, %s, %s) "
                         "ON CONFLICT DO NOTHING", (cid, model, PROMPT_VERSION, stored, bad))
        done += 1
        kept += stored
        refused += bad
        if progress:
            progress(n, len(todo))
    log.info("extraction: %d conversations read, %d claims kept, %d refused, %d failed", done, kept, refused, failed)
    return {"done": done, "claims": kept, "refused": refused, "failed": failed, "waiting": len(todo), "unread": unread}
