"""What Dindon may do on the Internet for ONE claim, and nothing more (docs/regles-du-bot.md, « Vérification sur Internet »).

The rule given by the owner: the AI goes out on the Internet **only to check what a person says, without looking further**. This module is where that rule is enforced by the
shape of the code instead of being promised in a text. Whatever reads the claim (the model, the code around it) reaches the Internet only through a `Lookup`, and a `Lookup`:

* answers **one claim**: it is made for it and thrown away after;
* sends **at most `max_queries` queries** (2; a deeper check that a person asked for: 4), each to every search service, a failed query included (no hidden retries);
* reads **at most `max_pages` pages** (5; a deeper check that a person asked for: 8), and **only pages that the search itself returned**: never an address that a member wrote in a message, never a link found inside a
  page, never an address the model made up. Nothing is crawled, nothing is followed from page to page;
* refuses an empty query (nothing is sent for it);
* **counts** what it did (`spent`), so that it can be shown and audited: how many queries, how many pages. Never what they contained.

It does not decide whether a claim should be checked at all (a claim about a private person, an opinion, a question is not: that is the reading of the message, before this),
nor what the pages prove (that is the verdict, after this).
"""
from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urldefrag, urlsplit

from dindon.debate.search import Hit, Searcher, SearchError, scrub_query
from dindon.debate.web import Fetcher, Page

MAX_QUERIES = 2
MAX_PAGES = 5                  # reads, an unreadable or empty page included; `verify` stops sooner, at USEFUL_PAGES pages that had something to read
DEEP_QUERIES = 4               # a check that a person asked for (the button « Vérifier »): the claim itself is searched too
DEEP_PAGES = 8


class OutOfScope(Exception):
    """Something that checking one claim does not allow. `code`: empty (nothing to search), queries (budget used), pages (budget used), unlisted (not a page the search returned)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _key(url: str) -> str:
    """An address as compared: without its fragment, the scheme and the host in lower case."""
    clean = urldefrag(url.strip())[0]
    parts = urlsplit(clean)
    return parts._replace(scheme=parts.scheme.lower(), netloc=parts.netloc.lower()).geturl()


class Lookup:
    def __init__(self, searchers: Sequence[Searcher], fetcher: Fetcher, *, max_queries: int = MAX_QUERIES, max_pages: int = MAX_PAGES, language: str = "fr"):
        self._searchers, self._fetcher, self._language = tuple(searchers), fetcher, language
        self._max_queries, self._max_pages = max_queries, max_pages
        self._queries = self._pages = 0
        self._offered: dict[str, Hit] = {}                     # every page that a search returned for this claim, and only those

    def search(self, query: str) -> list[Hit]:
        """The hits of every search service for this query (the same cleaned sentence goes to all of them), without duplicates. Counts as one query."""
        cleaned = scrub_query(query)
        if not cleaned:
            raise OutOfScope("empty")
        if self._queries >= self._max_queries:
            raise OutOfScope("queries")
        self._queries += 1
        answered, failure, found = 0, None, {}
        for service in self._searchers:
            try:
                hits = service.search(cleaned, self._language)
            except SearchError as error:                       # one service may be down while the other answers
                failure = error
                continue
            answered += 1
            for hit in hits:
                key = _key(hit.url)
                found.setdefault(key, hit)
                self._offered.setdefault(key, hit)
        if not answered and failure is not None:
            raise failure
        return list(found.values())

    def read(self, url: str) -> Page:
        """The text of a page that a search of this claim returned. Counts as one page, even if it cannot be read."""
        key = _key(url)
        if key not in self._offered:
            raise OutOfScope("unlisted")
        if self._pages >= self._max_pages:
            raise OutOfScope("pages")
        self._pages += 1
        return self._fetcher.fetch(self._offered[key].url)

    @property
    def offered(self) -> list[Hit]:
        return list(self._offered.values())

    def spent(self) -> dict[str, int]:
        """What was done on the Internet for this claim: counts only."""
        return {"queries": self._queries, "pages": self._pages}
