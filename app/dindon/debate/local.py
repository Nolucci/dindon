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

PROMPT_VERSION = "local-5"
TRUE, FALSE, UNSURE = "true", "false", "unsure"
SYSTEM = (
    "Tu es un vérificateur de faits. On te donne UNE affirmation de fait, seule : tu ne sais ni qui l'a dite, ni dans quel débat, et tu n'as aucun avis. "
    "Sans chercher sur Internet, tu dis si elle est exacte (`true`), inexacte (`false`) ou si tu ne peux pas trancher (`unsure`). "
    "D'abord, dans `reasoning`, écris en une ou deux phrases ce que tu sais de l'objet de l'affirmation (le fait exact, l'ordre de grandeur) et si l'affirmation le respecte.\n"
    "Tu réponds `false` quand ce que tu sais est incompatible avec l'affirmation : un fait établi et stable (géographie, histoire, sciences, institutions), un nom ou une date que tu connais, "
    "un chiffre ou une proportion dont l'ordre de grandeur est connu et très éloigné de celui de l'affirmation (même sans connaître le chiffre exact), une personne ou une fonction qui n'existe pas ou n'a jamais existé, "
    "une généralisation absurde (« la majorité des X font Y » alors que ce n'est manifestement pas le cas). Tu réponds `true` quand tu es certain que l'affirmation est exacte. "
    "Tu réponds `unsure` pour ce qui change vraiment avec le temps (résultats récents, prix, personnes en poste dont tu n'es pas sûr), pour ce que tu ne connais pas, "
    "pour ce qui dépend d'une définition ou d'un périmètre flou, pour ce qui est invérifiable, et dès que ce que tu sais ne suffit pas pour trancher.\n"
    "Si tu réponds `false`, écris dans `answer` UNE phrase qui dit ce que tu sais d'exact (le bon fait, la bonne date, le bon ordre de grandeur), sans adresse Internet, sans « selon », sans adjectif, "
    "sans parler de la personne qui a affirmé. Cette phrase doit dire quelque chose de DIFFÉRENT de l'affirmation : si tu retrouves le même fait, c'est que l'affirmation est vraie. "
    "Si tu réponds `true` ou `unsure`, `answer` est vide. Donne aussi `certainty`, ton degré de certitude de 0 à 100 : sous 80, réponds `unsure`.\n"
    "Exemples. « La Terre tourne autour du Soleil. » → true. « Paris est la capitale de l'Allemagne. » → false, answer « La capitale de l'Allemagne est Berlin. » "
    "« 70 % des Français sont des moines. » → false, answer « Les moines ne représentent qu'une toute petite fraction de la population française. » "
    "« La France compte 80 millions de départements. » → false. « Le taux de chômage en France est de 7,3 %. » → unsure (un chiffre qui change). "
    "« Mon voisin a mangé deux pommes hier. » → unsure."
)
SCHEMA = {"type": "object", "properties": {"reasoning": {"type": "string"}, "verdict": {"type": "string", "enum": [TRUE, FALSE, UNSURE]}, "answer": {"type": "string"}, "certainty": {"type": "integer"}},
          "required": ["reasoning", "verdict", "answer", "certainty"]}
CHECK_SYSTEM = (
    "On te donne une AFFIRMATION et une CORRECTION proposée. Réponds `contradicts` seulement si la correction est incompatible avec l'affirmation : les deux ne peuvent pas être vraies en même temps "
    "(un autre fait, une autre date, un autre chiffre, un autre ordre de grandeur). Réponds `same` si la correction dit la même chose que l'affirmation (reformulée, ou avec les mêmes faits), "
    "`unrelated` si elle parle d'autre chose. En cas de doute : `same`."
)
CHECK_SCHEMA = {"type": "object", "properties": {"relation": {"type": "string", "enum": ["contradicts", "same", "unrelated"]}}, "required": ["relation"]}
MIN_ANSWER, MAX_ANSWER = 15, 400
MIN_CERTAINTY = 80                                                              # what the model says of its own certainty: not a proof, but a model that hesitates must not speak
MIN_CERTAINTY_COMPARING = 90                                                    # a claim that compares a figure with a threshold: the model must be surer (it gets the arithmetic wrong more often)
_NOT_CLEAN = re.compile(r"https?://|www\.|\[|\]|<|>|@", re.I)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
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
    """Dindon's answer to one claim, without the Internet. Raises what the model raises when it cannot answer (the message is tried again later); anything it gets wrong becomes `unsure`.
    The model reasons first, then says; a `false` is then read again by a second, narrow question (does the correction really contradict the claim?), because a model that is right about the
    fact sometimes says `false` while restating it."""
    said = llm.chat_json(model, SYSTEM, f"Affirmation :\n«{reading.claim}»", SCHEMA, num_ctx=2048)
    verdict = str(said.get("verdict") or "").strip().lower() if isinstance(said, dict) else ""
    try:
        certainty = int(said.get("certainty")) if isinstance(said, dict) else 0
    except (TypeError, ValueError):
        certainty = 0
    if verdict not in (TRUE, FALSE) or certainty < (MIN_CERTAINTY_COMPARING if _COMPARES.search(reading.claim) else MIN_CERTAINTY):
        return Local(UNSURE)                                                    # not certain, by its own account: Dindon says nothing
    if verdict == TRUE:
        return Local(TRUE)
    sentence = " ".join(str(said.get("answer") or "").split())
    if not MIN_ANSWER <= len(sentence) <= MAX_ANSWER or _NOT_CLEAN.search(sentence):
        return Local(UNSURE)                                                    # nothing to say, or something that must not be said: Dindon does not answer
    if _figures(reading.claim) and _figures(reading.claim) <= _figures(sentence):
        return Local(UNSURE)                                                    # a « correction » that keeps every figure of the claim corrects nothing: the model contradicts itself
    relation = llm.chat_json(model, CHECK_SYSTEM, f"AFFIRMATION : {reading.claim}\nCORRECTION : {sentence}", CHECK_SCHEMA, num_ctx=2048)
    if not isinstance(relation, dict) or relation.get("relation") != "contradicts":
        return Local(UNSURE)                                                    # the « correction » says what the claim says: not a correction
    return Local(FALSE, sentence)
