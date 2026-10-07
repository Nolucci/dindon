"""Stage 3 of the cascade, the topics: found automatically from the conversations, **without any regard to who wrote them**, then
proposed to the person, who validates, renames, merges or rejects them (nothing downstream uses a topic that is not validated).

How, and why this way:

* the vectors of the kept conversations are grouped by their direction (spherical k-means, k-means++ start, a few restarts). The number
  of topics is chosen by the silhouette (how well each conversation fits its own group against the nearest other one) among a few
  candidates, unless the person gives it. It is a heuristic, and every score is recorded with the run;
* a group of fewer than `MIN_SIZE` conversations is noise, not a topic: its conversations are left without topic;
* each group is named by a local language model from its keywords and its most typical conversations, without names. The name is a
  proposal: when the model fails, the keywords stand in for it;
* a new run replaces the topics that were only *proposed* by the previous runs and that nobody touched; what the person validated,
  rejected, renamed or merged (or merged something into) is never replaced.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable

import numpy as np
import psycopg

from dindon.analysis.embeddings import conversation_chunks, conversation_texts
from dindon.analysis.ollama import Ollama, OllamaError

log = logging.getLogger("dindon.analysis")

MIN_SIZE = 3            # conversations: below this a group is noise
MIN_CONVERSATIONS = 16  # below this there is not enough to find topics
MIN_SIMILARITY = 0.35   # a distant conversation has no topic
MIN_MARGIN = 0.01       # a borderline tie between two topics is left unclassified
TOKEN = re.compile(r"[a-zàâäçéèêëîïôöùûüÿœæ]{4,}")
STOPWORDS = frozenset(["alors", "aucun", "aussi", "autre", "autres", "avec", "avez", "avoir", "avons", "beaucoup", "bien", "cela", "celle", "celles", "celui", "cependant", "certains", "chaque", "comme", "comment", "contre", "dans", "depuis", "dire", "dont", "donc", "elle", "elles", "encore", "entre", "était", "étaient", "être", "faire", "fait", "faut", "fois", "haha", "leur", "leurs", "lors", "mais", "même", "mdr", "merci", "moins", "notre", "nous", "oui", "parce", "pareil", "peut", "peuvent", "plus", "plutôt", "pour", "pourquoi", "pourtant", "puis", "quand", "quel", "quelle", "quelles", "quels", "quelque", "quoi", "sans", "selon", "sera", "seront", "ses", "sont", "sous", "tellement", "tout", "toute", "toutes", "tous", "très", "trop", "vous", "votre", "vraiment", "voir", "voilà", "autant", "bonjour", "bonsoir", "ceci", "chez", "déjà", "être", "jamais", "jusqu", "juste", "lorsque", "ouais", "parfois", "peut-être", "pense", "penses", "pourrait", "sinon", "souvent", "tant", "toujours", "veut", "veux", "vois", "vers", "ceux", "ainsi", "après", "avant", "avait", "avaient", "cette", "cettes", "ces", "ils", "ilsa", "non", "pas", "pareil", "quand", "quelqu", "rien", "suis", "tiens", "vais", "voulais", "allez", "aller", "ailleurs", "apres", "aucune", "aurait", "autres", "bref", "bon", "bonne", "car", "cas", "cela", "chose", "choses", "dit", "dites", "disait", "donne", "entre", "eux", "facon", "gens", "grand", "grande", "hier", "ici", "jour", "jours", "lequel", "mieux", "moi", "mon", "mes", "mêmes", "nos", "nouvelle", "part", "pense", "petit", "peu", "peux", "pris", "pu", "quoi", "sais", "savoir", "sera", "sommes", "soit", "sur", "tes", "ton", "trois", "très", "une", "unes", "vas", "veux", "vieux", "vite", "vois", "vos"])

NAMING_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
    "required": ["label", "description"],
}
NAMING_SYSTEM = (
    "Tu donnes un nom à un sujet de discussion d'un serveur Discord francophone. Tu réponds uniquement par un objet JSON. "
    "Le nom décrit le SUJET en 2 à 6 mots (par exemple « Salaire minimum et pouvoir d'achat »), jamais une personne ni un lieu de "
    "discussion générique comme « discussion » ou « sujets variés ». La description tient en une phrase."
)


class NotEnough(Exception):
    """Not enough conversations with a vector to find topics."""


# ---------------------------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------------------------


def spherical_kmeans(x: np.ndarray, k: int, rng: np.random.Generator, restarts: int = 3, iterations: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """Groups the rows of `x` (unit vectors) by direction. Returns the group of each row and the centers, of the best restart."""
    n = len(x)
    best: tuple[float, np.ndarray, np.ndarray] | None = None
    for _ in range(restarts):
        first = int(rng.integers(n))
        centers = [x[first]]
        distance = 1 - x @ x[first]
        for _ in range(1, k):                                   # k-means++: far points are likelier starts
            weight = np.clip(distance, 0, None) ** 2
            total = weight.sum()
            pick = int(rng.choice(n, p=weight / total)) if total > 0 else int(rng.integers(n))
            centers.append(x[pick])
            distance = np.minimum(distance, 1 - x @ x[pick])
        c = np.stack(centers)
        labels: np.ndarray | None = None
        for _ in range(iterations):
            similarity = x @ c.T
            new = similarity.argmax(1)
            if labels is not None and (new == labels).all():
                break
            labels = new
            for j in range(k):
                members = x[labels == j]
                if len(members):
                    total = members.sum(0)
                    norm = np.linalg.norm(total)
                    c[j] = total / norm if norm else x[int(rng.integers(n))]
                else:                                           # an empty group takes the row that fits worst
                    c[j] = x[int(similarity.max(1).argmin())]
        assert labels is not None
        score = float((x @ c.T).max(1).sum())
        if best is None or score > best[0]:
            best = (score, labels.copy(), c.copy())
    assert best is not None
    return best[1], best[2]


def silhouette(x: np.ndarray, labels: np.ndarray, rng: np.random.Generator, sample: int = 1500) -> float:
    """Mean silhouette with cosine distance, on a sample of at most `sample` rows."""
    n = len(x)
    pick = rng.choice(n, min(n, sample), replace=False)
    xs, ls = x[pick], labels[pick]
    groups = np.unique(ls)
    if len(groups) < 2:
        return -1.0
    onehot = (ls[:, None] == groups[None, :]).astype(np.float64)       # (m, g)
    counts = onehot.sum(0)
    sums = (1 - xs @ xs.T) @ onehot                                    # distance of each row to every group, summed
    own = onehot.argmax(1)
    rows = np.arange(len(xs))
    a = sums[rows, own] / np.maximum(counts[own] - 1, 1)
    others = sums / np.maximum(counts, 1)
    others[rows, own] = np.inf
    b = others.min(1)
    scale = np.maximum(a, b)
    s = np.where((counts[own] > 1) & (scale > 0), (b - a) / np.where(scale > 0, scale, 1), 0.0)
    return float(s.mean())


def choose_topics(x: np.ndarray, rng: np.random.Generator, forced: int | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """The grouping to propose: the number that the person asked for, or the best silhouette among a few candidates."""
    n = len(x)
    if forced is not None:
        labels, centers = spherical_kmeans(x, max(2, min(forced, n)), rng)
        return labels, centers, {"k": int(len(centers)), "chosen_by": "person", "scores": {}}
    kmax = max(2, min(40, n // 8))
    kmin = min(4, kmax)
    candidates = sorted({int(round(v)) for v in np.linspace(kmin, kmax, 8)})
    scores, best = {}, None
    for k in candidates:
        labels, centers = spherical_kmeans(x, k, rng, restarts=2)
        scores[k] = round(silhouette(x, labels, rng), 4)
        if best is None or scores[k] > best[0]:
            best = (scores[k], labels, centers)
    assert best is not None
    return best[1], best[2], {"k": int(len(best[2])), "chosen_by": "silhouette", "scores": scores}


def confident_assignments(similarities: np.ndarray, labels: np.ndarray) -> list[int]:
    """Indices with a credible topic; K-means labels alone always assign noise."""
    chosen = similarities[np.arange(len(labels)), labels]
    runner_up = np.partition(similarities, -2, axis=1)[:, -2]
    minimum = {g: max(MIN_SIMILARITY, float(np.quantile(chosen[labels == g], 0.10)))
               for g in np.unique(labels)}
    median = {g: float(np.median(chosen[labels == g])) for g in minimum}
    return [i for i, g in enumerate(labels)
            if chosen[i] >= minimum[g] and
            (chosen[i] - runner_up[i] >= MIN_MARGIN or chosen[i] >= median[g])]


# ---------------------------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------------------------


def tokens(text: str) -> set[str]:
    return {t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS}


class Keywords:
    """The words that mark each group: frequent in its conversations, rare in the others (document frequency, tf-idf like). Fed with
    texts one by one, so that nothing needs all the texts in memory at once."""

    def __init__(self) -> None:
        self.total = 0
        self.overall: Counter[str] = Counter()
        self.local: dict[int, Counter[str]] = {}
        self.size: Counter[int] = Counter()

    def add(self, group: int, text: str) -> None:
        found = tokens(text)
        self.total += 1
        self.size[group] += 1
        self.overall.update(found)
        self.local.setdefault(group, Counter()).update(found)

    def result(self, per_group: int = 8) -> dict[int, list[str]]:
        result = {}
        for g, counter in self.local.items():
            floor = 2 if self.size[g] < 12 else 3
            scored = [(count / self.size[g] * float(np.log(self.total / (1 + self.overall[w]))), w) for w, count in counter.items() if count >= floor]
            result[g] = [w for _, w in sorted(scored, reverse=True)[:per_group]]
        return result


def fallback_label(words: list[str]) -> str:
    return ", ".join(words[:3]) if words else "Sujet sans nom"


def representative_excerpt(text: str, words: list[str], limit: int = 400) -> str:
    """Show the model lines about this group, not the arbitrary start of a chat."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    marks = set(words)
    ranked = sorted(enumerate(lines), key=lambda item: (-len(tokens(item[1]) & marks), item[0]))
    relevant = [i for i, line in ranked if tokens(line) & marks]
    selected = sorted((relevant or [i for i, _ in ranked])[:4])
    return " / ".join(lines[i] for i in selected)[:limit]


def name_topic(client: Ollama, model: str, words: list[str], excerpts: list[str]) -> tuple[str, str | None, bool]:
    """(label, description, named by the model). The model gets keywords and excerpts, never a name of a person."""
    listing = "\n".join(f"{i}. {e}" for i, e in enumerate(excerpts, 1))
    user = f"Mots fréquents : {', '.join(words) or '(aucun)'}\n\nExtraits de conversations sur ce sujet :\n{listing}\n\nDonne le nom du sujet et une description."
    for _ in range(2):
        try:
            answer = client.chat_json(model, NAMING_SYSTEM, user, NAMING_SCHEMA)
        except OllamaError as error:
            log.warning("topic naming failed: %s", error)
            continue
        label, description = str(answer.get("label", "")).strip(), str(answer.get("description", "")).strip()
        if 3 <= len(label) <= 80 and "@" not in label:
            return label, description[:400] or None, True
    return fallback_label(words), None, False


# ---------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------


def load_vectors(conn: psycopg.Connection, guild_id: int, model: str) -> tuple[list[int], np.ndarray]:
    """The ids of the kept conversations that have a vector for `model`, and the vectors as unit rows of one array. Each vector is read
    from its text straight into the array: a Python list of 1024 floats per row would take ten times the memory (and the time)."""
    rows = conn.execute(
        """SELECT e.conversation_id, e.embedding::text FROM conversation_embeddings e
           JOIN conversations c ON c.id = e.conversation_id JOIN channels ch ON ch.id = c.channel_id
           WHERE ch.guild_id = %s AND e.model = %s AND c.kept ORDER BY e.conversation_id""", (guild_id, model)).fetchall()
    ids = [r[0] for r in rows]
    x = np.zeros((len(rows), 1024), dtype=np.float32)
    for i, (_, text) in enumerate(rows):
        x[i] = np.fromstring(text.strip("[]"), dtype=np.float32, sep=",")
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return ids, x / np.where(norms == 0, 1, norms)


def discover_themes(conn: psycopg.Connection, client: Ollama, guild_id: int, *, embed_model: str, name_model: str, topics: int | None = None,
                    seed: int = 0, progress: Callable[[str], None] | None = None,
                    step_progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Finds the topics of the conversations that have a vector, and records them as proposals. Returns what was found."""
    say = progress or (lambda _text: None)
    ids, x = load_vectors(conn, guild_id, embed_model)
    if len(ids) < MIN_CONVERSATIONS:
        raise NotEnough(f"{len(ids)} conversations avec un vecteur : il en faut au moins {MIN_CONVERSATIONS} pour trouver des thèmes")
    rng = np.random.default_rng(seed)
    say(f"regroupement de {len(ids)} conversations")
    labels, centers, how = choose_topics(x, rng, topics)
    all_similarity = x @ centers.T
    similarity = all_similarity[np.arange(len(ids)), labels]

    # K-means always gives every point a label, even when the point is unrelated
    # to that centre. Admit a low-fit point only if its closest topic is clear.
    useful = confident_assignments(all_similarity, labels)
    groups = {g: [i for i in useful if labels[i] == g] for g in range(len(centers))}
    groups = {g: members for g, members in groups.items() if len(members) >= MIN_SIZE}
    if step_progress:
        step_progress(0, len(groups))
    group_of = {ids[i]: g for g, members in groups.items() for i in members}
    keyword_counter = Keywords()
    ordered = sorted(group_of)
    for start in range(0, len(ordered), 500):                  # the texts come 500 conversations at a time, and are forgotten
        for cid, chunks in conversation_chunks(conn, ordered[start:start + 500]).items():
            keyword_counter.add(group_of[cid], "\n".join(chunks))
    words = keyword_counter.result()
    nearest_of = {g: sorted(members, key=lambda i: -similarity[i])[:6] for g, members in groups.items()}
    wanted = [ids[i] for nearest in nearest_of.values() for i in nearest]
    texts = conversation_texts(conn, wanted)                   # only the typical conversations are kept, to show the model
    found = []
    for n, (g, members) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        if cancelled():
            raise InterruptedError("annulé")
        nearest = nearest_of[g]
        excerpts = [representative_excerpt(texts.get(ids[i], ""), words.get(g, [])) for i in nearest]
        say(f"nom du thème {n}/{len(groups)}")
        label, description, named = name_topic(client, name_model, words.get(g, []), excerpts)
        found.append({"group": g, "members": members, "label": label, "description": description, "named": named, "keywords": words.get(g, [])})
        if step_progress:
            step_progress(n, len(groups))

    with conn.transaction():
        # The proposals that nobody has touched are replaced; one that the person renamed, or that another was merged into, stays
        removed = conn.execute(
            """DELETE FROM topics WHERE guild_id = %s AND status = 'proposed' AND origin = 'discovered' AND touched_at IS NULL
                 AND NOT EXISTS (SELECT 1 FROM topics child WHERE child.merged_into = topics.id)""", (guild_id,)).rowcount
        run_id = conn.execute(
            "INSERT INTO topic_runs (guild_id, method, model, parameters, message_count) VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING id",
            (guild_id, "embeddings clustering + model naming", f"{embed_model} + {name_model}",
             json.dumps({**how, "seed": seed, "min_size": MIN_SIZE, "min_similarity": MIN_SIMILARITY,
                         "min_margin": MIN_MARGIN, "unassigned": len(ids) - sum(len(f["members"]) for f in found),
                         "named_by_model": sum(f["named"] for f in found)}), len(ids))).fetchone()[0]
        for f in found:
            topic_id = conn.execute(
                """INSERT INTO topics (guild_id, label, description, keywords, origin, status, run_id)
                   VALUES (%s, %s, %s, %s, 'discovered', 'proposed', %s) RETURNING id""",
                (guild_id, f["label"], f["description"], f["keywords"], run_id)).fetchone()[0]
            f["topic_id"] = topic_id
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO topic_assignments (run_id, conversation_id, topic_id, similarity) VALUES (%s, %s, %s, %s)",
                                [(run_id, ids[i], topic_id, float(similarity[i])) for i in f["members"]])
    log.info("themes: %d topics from %d conversations (k=%s, %s); %d earlier proposals replaced", len(found), len(ids), how["k"],
             how["chosen_by"], removed)
    return {"run_id": run_id, "topics": len(found), "conversations": len(ids), "assigned": sum(len(f["members"]) for f in found),
            "replaced": removed, **how, "named_by_model": sum(f["named"] for f in found)}
