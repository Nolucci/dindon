"""Which part of a server to import: some channels, some people, a period.

An import of everything is `dindon backfill`. This narrows it: only some channels (by name or id), only the messages written by some
people, only the messages that mention some people, only a period. It is the exporter that filters (its `--filter`, `--after` and
`--before`), so what does not match is not even downloaded.

An import that is narrowed by people or by a period brings only a part of what its channels contain. It is therefore recorded as
**partial** and never taken for a complete history: it is not a first import, and a later complete import still brings everything
(the importer goes on "after the newest message it has", which would be wrong here). Choosing channels only is not partial: those
channels are imported completely.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from dindon.collector.discord_api import Watched
from dindon.collector.snowflake import snowflake_at

MAX_IDS = 50
_MENTION = re.compile(r"<@!?([0-9]+)>")  # what pasting a mention gives


class SelectionError(ValueError):
    """The selection cannot be understood. The message says why, in words for the person who wrote it."""


def _ids(values, what: str) -> tuple[int, ...]:
    found: list[int] = []
    for raw in values or ():
        for token in re.split(r"[\s,;]+", str(raw).strip()):
            if not token:
                continue
            token = (_MENTION.fullmatch(token) or [None, token])[1]
            if not re.fullmatch(r"[0-9]{1,20}", token):
                raise SelectionError(f"{what} : « {token} » n'est pas un identifiant Discord (des chiffres seulement).")
            if int(token) not in found:
                found.append(int(token))
    if len(found) > MAX_IDS:
        raise SelectionError(f"{what} : {len(found)} identifiants, {MAX_IDS} au plus.")
    return tuple(found)


def _day(value, what: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value).strip())
    except ValueError:
        raise SelectionError(f"{what} : « {value} » n'est pas une date (AAAA-MM-JJ).") from None


def _fold(text: str) -> str:
    """For comparing names: no case, no accents, no leading #."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return plain.casefold().strip().lstrip("#").strip()


@dataclass(frozen=True)
class ImportSelection:
    channels: tuple[str, ...] = ()     # names or ids; empty: every channel of the server
    authors: tuple[int, ...] = ()      # only the messages written by these people
    mentions: tuple[int, ...] = ()     # only the messages that mention these people
    after: date | None = None          # first day included (UTC)
    before: date | None = None         # last day included (UTC)

    @classmethod
    def parse(cls, channels=(), authors=(), mentions=(), after=None, before=None) -> "ImportSelection":
        names = tuple(dict.fromkeys(t for raw in channels or () for t in re.split(r"[\n,;]+", str(raw)) if t.strip()))
        selection = cls(tuple(n.strip() for n in names), _ids(authors, "Auteurs"), _ids(mentions, "Personnes mentionnées"),
                        _day(after, "Du"), _day(before, "Au"))
        if selection.after and selection.before and selection.after > selection.before:
            raise SelectionError("La période est à l'envers : « Du » est après « Au ».")
        return selection

    @property
    def partial(self) -> bool:
        """Does it bring only a part of what its channels contain?"""
        return bool(self.authors or self.mentions or self.after or self.before)

    def message_filter(self) -> str | None:
        """The exporter's filter: people of a group are 'or', the groups are 'and' (see .docs/Message-filters.md)."""
        groups = [f"({' | '.join(f'{key}:{i}' for i in ids)})" for key, ids in (("from", self.authors), ("mentions", self.mentions)) if ids]
        return " ".join(groups) or None

    def after_id(self) -> int | None:
        return snowflake_at(datetime.combine(self.after, time.min, timezone.utc)) if self.after else None

    def before_id(self) -> int | None:
        """The last day is included: messages are wanted up to the start of the next one."""
        return snowflake_at(datetime.combine(self.before + timedelta(days=1), time.min, timezone.utc)) if self.before else None

    def describe(self) -> dict:
        return {"channels": list(self.channels), "authors": [str(i) for i in self.authors], "mentions": [str(i) for i in self.mentions],
                "after": self.after.isoformat() if self.after else None, "before": self.before.isoformat() if self.before else None,
                "partial": self.partial}


def resolve_channels(wanted: tuple[str, ...], available: list[Watched]) -> list[Watched]:
    """The channels of the server that were asked for, by id or by name (case and accents do not matter)."""
    by_id = {c.id: c for c in available}
    chosen: dict[int, Watched] = {}
    for token in wanted:
        token = token.strip().lstrip("#").strip()
        if token.isdigit():
            if int(token) not in by_id:
                raise SelectionError(f"Salon {token} : inconnu, ou pas visible pour le bot.")
            chosen[int(token)] = by_id[int(token)]
            continue
        matches = [c for c in available if c.name and _fold(c.name) == _fold(token)]
        if not matches:
            names = ", ".join(sorted(c.name for c in available if c.name and c.kind != "thread"))
            raise SelectionError(f"Salon « {token} » : inconnu. Salons visibles : {names}.")
        if len(matches) > 1:
            raise SelectionError(f"Salon « {token} » : plusieurs salons portent ce nom, donnez l'identifiant ({', '.join(str(c.id) for c in matches)}).")
        chosen[matches[0].id] = matches[0]
    return list(chosen.values())
