"""The filter of an import (people who wrote, people who are mentioned), applied to the messages **before** anything else is asked of Discord for them.

The grammar is the part of the original exporter's that Dindon writes (collector/selection.py): `from:ID`, `mentions:ID`, `|` for "or", a space for
"and", parentheses to group. Anything else is refused, in words: a filter that is silently ignored would import everybody.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from dindon.export.errors import ExporterError

_TOKENS = re.compile(r"\(|\)|\||[^\s()|]+")


def compile_filter(expression: str | None) -> Callable[[dict], bool]:
    """A function that says whether a message (as Discord's REST API gives it) matches. No expression: everything matches."""
    if not expression or not expression.strip():
        return lambda message: True
    tokens = _TOKENS.findall(expression)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def either() -> Callable[[dict], bool]:
        nonlocal position
        parts = [both()]
        while peek() == "|":
            position += 1
            parts.append(both())
        return lambda m: any(p(m) for p in parts)

    def both() -> Callable[[dict], bool]:
        parts = [single()]
        while peek() not in (None, "|", ")"):
            parts.append(single())
        return lambda m: all(p(m) for p in parts)

    def single() -> Callable[[dict], bool]:
        nonlocal position
        if position >= len(tokens):
            raise ExporterError(f"Filtre « {expression} » : il manque quelque chose à la fin.")
        token = tokens[position]
        position += 1
        if token == "(":
            inner = either()
            if peek() != ")":
                raise ExporterError(f"Filtre « {expression} » : une parenthèse n'est pas fermée.")
            position += 1
            return inner
        key, _, value = token.partition(":")
        if key not in ("from", "mentions") or not value.isdigit():
            raise ExporterError(f"Filtre « {expression} » : « {token} » n'est pas compris (seuls from:ID et mentions:ID le sont).")
        if key == "from":
            return lambda m: str(m["author"]["id"]) == value
        return lambda m: any(str(u["id"]) == value for u in m.get("mentions", []))

    result = either()
    if position != len(tokens):
        raise ExporterError(f"Filtre « {expression} » : « {tokens[position]} » est de trop.")
    return result
