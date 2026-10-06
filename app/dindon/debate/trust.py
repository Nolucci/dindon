"""Which sources a correction may rest on. Not every page found on the web is worth a public correction in the name of Dindon.

* **official**: the bodies that produce the figures (statistics institutes, administrations, parliaments, international organisations). A claim can be
  declared false against them.
* **checker**: fact-checking desks of the press, which publish their method and their sources. A claim can be declared false against them too.
* **other**: anything else. It can be shown as context (« à vérifier »), but alone it is never enough to say that a claim is false.

An entry is a host (`insee.fr`: the host and its subdomains) or a host and a path (`lemonde.fr/les-decodeurs`: only that part of the site: a newspaper is not
a checker as a whole). The lists are a **starting point for the owner to read and change** (docs/regles-du-bot.md), not a judgement on anyone.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

OFFICIAL_DEFAULT = (
    "insee.fr", "gouv.fr", "assemblee-nationale.fr", "senat.fr", "conseil-constitutionnel.fr", "conseil-etat.fr", "ccomptes.fr", "banque-france.fr",
    "ademe.fr", "santepubliquefrance.fr", "cnil.fr", "europa.eu", "who.int", "oecd.org", "un.org", "worldbank.org", "imf.org", "iea.org", "ipcc.ch",
    "nasa.gov", "noaa.gov", "cdc.gov", "nih.gov",
    # The company itself is a primary source for the identity and products of its own shops.
    "marieblachere.com",
)
CHECKERS_DEFAULT = (
    "factuel.afp.com", "lemonde.fr/les-decodeurs", "liberation.fr/checknews", "francetvinfo.fr/vrai-ou-faux", "factcheck.org", "fullfact.org", "snopes.com",
    "reuters.com/fact-check", "apnews.com/hub/ap-fact-check",
)
OFFICIAL, CHECKER, OTHER = "official", "checker", "other"


def _split(entry: str) -> tuple[str, str]:
    host, _, path = entry.strip().lower().partition("/")
    return host, ("/" + path.strip("/") + "/") if path else ""


def _matches(entry: str, host: str, path: str) -> bool:
    entry_host, entry_path = _split(entry)
    if not entry_host or not (host == entry_host or host.endswith("." + entry_host)):
        return False
    return not entry_path or (path.lower().rstrip("/") + "/").startswith(entry_path)


@dataclass(frozen=True)
class Trust:
    official: tuple[str, ...] = OFFICIAL_DEFAULT
    checkers: tuple[str, ...] = CHECKERS_DEFAULT

    def tier(self, url: str) -> str:
        """`official`, `checker` or `other` for a page address. A malformed address is `other`."""
        try:
            parts = urlsplit(url)
        except ValueError:
            return OTHER
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in ("http", "https") or not host:
            return OTHER
        if any(_matches(e, host, parts.path) for e in self.official):
            return OFFICIAL
        if any(_matches(e, host, parts.path) for e in self.checkers):
            return CHECKER
        return OTHER

    def with_extra(self, official: tuple[str, ...] = (), checkers: tuple[str, ...] = ()) -> Trust:
        """The same lists with the owner's additions."""
        return Trust(self.official + tuple(official), self.checkers + tuple(checkers))

    def can_condemn(self, url: str) -> bool:
        """Whether a page of this kind is enough, by itself, to say that a claim is false."""
        return self.tier(url) in (OFFICIAL, CHECKER)

    def source_key(self, url: str) -> str | None:
        """The allowlist entry behind a trusted URL; pages from that entry are one source."""
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in ("http", "https"):
            return None
        return next((entry for entry in self.official + self.checkers if _matches(entry, host, parts.path)), None)
