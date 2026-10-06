"""Searching the web for the verification of a claim (docs/regles-du-bot.md). Two services behind one shape, so that one can be changed without touching the rest:

* `FactCheckSearch`: Google's Fact Check Tools API, which finds **fact-checks that press desks already published** for a claim (a rating, the desk, the link). Needs an API key
  (`DINDON_FACTCHECK_API_KEY`).
* `SearxSearch`: a SearXNG instance that you run yourself (its JSON output must be switched on: `search: formats: [html, json]` in its settings): a general web search, with
  no account and no key. It asks other search engines for you, and those may refuse a machine that asks too often: it suits a few claims an hour, not hundreds.

**What leaves this machine** is a query, and only that: a short neutral sentence about the claim (`scrub_query`), never the message, never a name of a member or an
identifier, plus, for the fact-check service, the key. The query goes to the search service and, through it, to the engines it asks. That is stated to the members in `/dindon info`
as soon as this is switched on.

Nothing here logs a query, an address or a key. An error says what kind it is and the HTTP status, nothing else.

The shape of the answers is that of the services' documentation; it has not been checked against the real services (docs/regles-du-bot.md).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

MAX_URL = 2000


class SearchError(Exception):
    """The search could not be made. `status` is the HTTP status when there was one (403: refused, 429: too many, 5xx: the service is ill), None otherwise."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Hit:
    url: str
    title: str
    snippet: str
    via: str                              # 'factcheck' or 'searxng'
    rating: str | None = None             # a fact-check: the verdict of the desk, in its own words
    publisher: str | None = None          # a fact-check: the desk
    claim: str | None = None              # a fact-check: the claim that it examined (to see whether it is the same)
    reviewed_on: str | None = None


class Searcher(Protocol):
    def search(self, query: str, language: str = "fr", limit: int = 8) -> list[Hit]: ...


# --- the query ------------------------------------------------------------------------------------------------------------------

_DISCORD = re.compile(r"<(?:a?:\w+:|[@#!&]+)\d+>")                    # <@123>, <#123>, <:emoji:123>
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+33|0033|0)\s?[1-9](?:[\s.-]?\d{2}){4}(?!\d)")   # a French number, not a figure with spaces in it (3 500 000 000)
_ID = re.compile(r"(?<!\d)\d{15,}(?!\d)")                              # a Discord identifier
_MENTION = re.compile(r"@\w+")


def has_personal_data(text: str) -> bool:
    """Whether a text contains what must never be sent anywhere: a mention, an address, an e-mail, a phone number, an identifier."""
    return any(pattern.search(text) for pattern in (_DISCORD, _URL, _EMAIL, _PHONE, _ID, _MENTION))


def scrub_query(text: str, limit: int = 200) -> str:
    """What may be sent to a search service: the sentence without mentions, addresses, e-mails, phone numbers or identifiers, in 200 characters at most.
    A safety net, not a guarantee: the query is written by the model from the claim only (never from the message or its author), and this removes what should not be there."""
    for pattern in (_DISCORD, _URL, _EMAIL, _PHONE, _ID, _MENTION):
        text = pattern.sub(" ", text)
    text = " ".join(text.replace("\n", " ").split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return text.strip(" ,;:-")


# --- the services ---------------------------------------------------------------------------------------------------------------


def _get_json(url: str, timeout: float, what: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "DindonBot/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:           # nosec: the address is the operator's, from the settings
            raw = response.read(2_000_000)
    except urllib.error.HTTPError as error:
        raise SearchError(f"{what} answered {error.code}", error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SearchError(f"{what} cannot be reached ({type(error).__name__})") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise SearchError(f"{what} did not answer JSON") from None
    if not isinstance(data, dict):
        raise SearchError(f"{what} answered something unexpected")
    return data


def _clean(url: object) -> str | None:
    text = str(url or "").strip()
    return text if text.lower().startswith(("http://", "https://")) and len(text) <= MAX_URL else None


class SearxSearch:
    """A SearXNG instance (its address is that of your own, on the Docker network or this machine). JSON output must be switched on in its settings; the `search`
    profile of docker-compose.yml does."""

    def __init__(self, base_url: str, timeout: float = 15.0):
        self._base, self._timeout = base_url.rstrip("/"), timeout

    def search(self, query: str, language: str = "fr", limit: int = 8) -> list[Hit]:
        query = scrub_query(query)
        if not query:
            return []
        params = urllib.parse.urlencode({"q": query, "format": "json", "language": language, "safesearch": 0, "categories": "general"})
        data = _get_json(f"{self._base}/search?{params}", self._timeout, "the search service")
        hits, seen = [], set()
        for item in data.get("results") or []:
            url = _clean(item.get("url") if isinstance(item, dict) else None)
            if url is None or url in seen:
                continue
            seen.add(url)
            hits.append(Hit(url, str(item.get("title") or "")[:300], str(item.get("content") or "")[:500], "searxng"))
            if len(hits) >= limit:
                break
        return hits


class FactCheckSearch:
    """Google's Fact Check Tools API (`claims:search`): fact-checks already published for a claim. The key is sent in the address, as the service asks, and never written anywhere."""

    def __init__(self, api_key: str, base_url: str = "https://factchecktools.googleapis.com", timeout: float = 15.0):
        self._key, self._base, self._timeout = api_key, base_url.rstrip("/"), timeout

    def search(self, query: str, language: str = "fr", limit: int = 8) -> list[Hit]:
        query = scrub_query(query)
        if not query or not self._key:
            return []
        params = urllib.parse.urlencode({"query": query, "languageCode": language, "pageSize": min(limit, 20), "key": self._key})
        data = _get_json(f"{self._base}/v1alpha1/claims:search?{params}", self._timeout, "the fact-check service")
        hits, seen = [], set()
        for claim in data.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            for review in claim.get("claimReview") or []:
                url = _clean(review.get("url") if isinstance(review, dict) else None)
                if url is None or url in seen:
                    continue
                seen.add(url)
                publisher = review.get("publisher") if isinstance(review.get("publisher"), dict) else {}
                hits.append(Hit(url, str(review.get("title") or "")[:300], "", "factcheck", rating=str(review.get("textualRating") or "")[:200] or None,
                                publisher=str(publisher.get("name") or publisher.get("site") or "")[:200] or None, claim=str(claim.get("text") or "")[:500] or None,
                                reviewed_on=str(review.get("reviewDate") or "")[:30] or None))
                if len(hits) >= limit:
                    return hits
        return hits
