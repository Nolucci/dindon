"""Dindon's first answer to a claim: from what its local model knows, without going on the Internet (docs/regles-du-bot.md, « Répondre d'abord, chercher ensuite »).

It is **blind**, like the reading of messages: the model gets the claim, alone. Not who said it, not the debate, not the camps. It is asked for certainty, in both directions, and it is told that
whatever changes with time, whatever it does not know precisely, and whatever needs a source is `unsure`: Dindon then does not answer, and goes on the Internet as before.

**The code does not trust the model**, as everywhere else: a `false` without a clean, short, sourceless sentence to say becomes `unsure`; an address, a link or a bracket in what it says drops the
answer. Nothing in this module reaches the network but the local model.

What it says has **no source**, and the message that carries it says so. That is why the participants judge it (Valide / Invalide), and why Dindon looks on the Internet when they reject it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from dindon.debate.reading import Chat, Reading

PROMPT_VERSION = "local-4"
TRUE, FALSE, UNSURE = "true", "false", "unsure"
SYSTEM = (
    "Tu es un vérificateur de faits très prudent. On te donne UNE affirmation de fait, seule : tu ne sais ni qui l'a dite, ni dans quel débat, et tu n'as aucun avis. "
    "Sans chercher sur Internet, réponds `true` seulement si tu es CERTAIN qu'elle est exacte, `false` seulement si tu es CERTAIN qu'elle est inexacte, et `unsure` dans tous les autres cas. "
    "Tu réponds `unsure` pour tout ce qui change avec le temps (chiffres récents, prix, résultats, personnes en poste, lois récentes), pour tout ce que tu ne connais pas précisément, "
    "pour tout ce qui dépend d'une définition ou d'un périmètre, et dès que tu hésites : mieux vaut se taire que se tromper. "
    "Si tu réponds `false`, écris dans `answer` UNE phrase qui dit ce que tu sais d'exact (le bon chiffre, la bonne date, le bon fait), sans adresse Internet, sans « selon », sans adjectif, "
    "sans parler de la personne qui a affirmé. Si tu réponds `true` ou `unsure`, `answer` est vide. Donne aussi `certainty`, ton degré de certitude de 0 à 100 : "
    "sous 80, réponds `unsure`. Une correction doit dire quelque chose de DIFFÉRENT de l'affirmation (un autre chiffre, une autre date, un autre fait) : si tu retrouves les mêmes chiffres, c'est que tu n'as pas de correction.\n"
    "Exemples. « La Terre tourne autour du Soleil. » → true. « Paris est la capitale de l'Allemagne. » → false, answer « La capitale de l'Allemagne est Berlin. » "
    "« Le taux de chômage en France est de 7,3 %. » → unsure (un chiffre qui change)."
)
SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": [TRUE, FALSE, UNSURE]}, "answer": {"type": "string"}, "certainty": {"type": "integer"}},
          "required": ["verdict", "answer", "certainty"]}
MIN_ANSWER, MAX_ANSWER = 15, 400
MIN_CERTAINTY = 80                                                              # what the model says of its own certainty: not a proof, but a model that hesitates must not speak
_NOT_CLEAN = re.compile(r"https?://|www\.|\[|\]|<|>|@", re.I)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# A claim that compares a figure with a threshold (« plus de 50 % », « inférieur à 1 000 euros ») needs the exact figure AND the arithmetic: a language model that answers from memory gets the comparison
# wrong too often (measured: docs/regles-du-bot.md « Mesure »). Dindon does not answer those on its own: they go on the Internet, or nothing is said.
_COMPARES = re.compile(r"\b(?:plus|moins) (?:de|que|d')|\bau (?:moins|plus)\b|\b(?:sup[ée]rieur|inf[ée]rieur)e?s?\b|\bd[ée]pass\w*|\bexc[èe]d\w*|\bau[- ](?:dessus|dessous)\b|\ben dessous\b|\bla moiti[ée]\b|\ble (?:double|triple|quart|tiers)\b|\bmajorit|\bminorit|[<>]", re.I)


def _figures(text: str) -> set[str]:
    """The numbers of a text (« 1 800 » is 1800, « 5,5 » is 5.5): what a correction of a figure must change."""
    return {n.replace(",", ".") for n in _NUMBER.findall(re.sub(r"(?<=\d)[\s\u202f\u00a0](?=\d{3}\b)", "", text))}


@dataclass(frozen=True)
class Local:
    """What the local model says of a claim: `verdict` true / false / unsure, and, for false, the sentence that Dindon will say."""
    verdict: str
    answer: str | None = None


def answer_claim(llm: Chat, model: str, reading: Reading) -> Local:
    """Dindon's answer to one claim, without the Internet. Raises what the model raises when it cannot answer (the message is tried again later); anything it gets wrong becomes `unsure`."""
    if _COMPARES.search(reading.claim):
        return Local(UNSURE)                                                    # a figure against a threshold: not for a model's memory (the model is not even asked)
    said = llm.chat_json(model, SYSTEM, f"Affirmation :\n«{reading.claim}»", SCHEMA, num_ctx=2048)
    verdict = str(said.get("verdict") or "").strip().lower() if isinstance(said, dict) else ""
    try:
        certainty = int(said.get("certainty")) if isinstance(said, dict) else 0
    except (TypeError, ValueError):
        certainty = 0
    if verdict not in (TRUE, FALSE) or certainty < MIN_CERTAINTY:
        return Local(UNSURE)                                                    # not certain, by its own account: Dindon says nothing
    if verdict == TRUE:
        return Local(TRUE)
    sentence = " ".join(str(said.get("answer") or "").split())
    if not MIN_ANSWER <= len(sentence) <= MAX_ANSWER or _NOT_CLEAN.search(sentence):
        return Local(UNSURE)                                                    # nothing to say, or something that must not be said: Dindon does not answer
    if _figures(reading.claim) and _figures(reading.claim) <= _figures(sentence):
        return Local(UNSURE)                                                    # a « correction » that keeps every figure of the claim corrects nothing: the model contradicts itself
    return Local(FALSE, sentence)
