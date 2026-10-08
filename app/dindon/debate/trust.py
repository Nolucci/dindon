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
    # France: statistics, administrations (gouv.fr covers the ministries, DREES, DARES, France Stratégie, Légifrance, data.gouv.fr...), parliament, courts, auditors, public research.
    "insee.fr", "gouv.fr", "assemblee-nationale.fr", "senat.fr", "conseil-constitutionnel.fr", "conseil-etat.fr", "ccomptes.fr", "banque-france.fr",
    "ademe.fr", "santepubliquefrance.fr", "cnil.fr", "vie-publique.fr", "ined.fr", "cepii.fr", "cae-eco.fr", "ipp.eu", "ofce.sciences-po.fr", "ires.fr", "cnesco.fr",
    "cnrs.fr", "inserm.fr", "inrae.fr", "inrap.fr", "meteofrance.fr", "afa.gouv.fr", "anlci.gouv.fr", "academie-francaise.fr", "acpr.banque-france.fr", "cour-de-cassation.fr",
    "has-sante.fr", "ansm.sante.fr", "anses.fr", "rte-france.com", "cre.fr", "ofpra.gouv.fr",
    # Europe and international organisations (europa.eu covers Eurostat, the ECB, the Commission, the Court of Justice, EUR-Lex).
    "europa.eu", "coe.int", "echr.coe.int", "who.int", "oecd.org", "oecd-ilibrary.org", "un.org", "worldbank.org", "imf.org", "iea.org", "ipcc.ch", "bis.org", "wto.org", "ilo.org",
    "unesco.org", "unhcr.org", "unicef.org", "fao.org", "iaea.org", "irena.org", "oecd-nea.org", "wmo.int", "ifrc.org", "icrc.org", "interpol.int", "iom.int", "undp.org",
    "unfccc.int", "unodc.org", "ohchr.org", "eea.europa.eu", "ecb.europa.eu", "eurofound.europa.eu", "ourworldindata.org",
    # Other countries: statistics offices, governments, parliaments, central banks, courts.
    "nasa.gov", "noaa.gov", "cdc.gov", "nih.gov", "bls.gov", "census.gov", "bea.gov", "cbo.gov", "congress.gov", "federalreserve.gov", "treasury.gov", "justice.gov", "fbi.gov",
    "supremecourt.gov", "whitehouse.gov", "usda.gov", "epa.gov", "energy.gov", "eia.gov", "ed.gov", "gao.gov", "sec.gov",
    "gov.uk", "ons.gov.uk", "parliament.uk", "nhs.uk", "bankofengland.co.uk", "legislation.gov.uk", "nao.org.uk", "ifs.org.uk", "supremecourt.uk",
    "canada.ca", "statcan.gc.ca", "gc.ca", "abs.gov.au", "mdba.gov.au", "gov.au", "stats.govt.nz", "govt.nz",
    "admin.ch", "bfs.admin.ch", "bag.admin.ch", "snb.ch", "bundesregierung.de", "destatis.de", "bundesbank.de", "bundestag.de", "bundesverfassungsgericht.de",
    "government.se", "regeringen.se", "scb.se", "bra.se", "riksbank.se", "riksdagen.se", "dst.dk", "ssb.no", "stat.fi", "vm.fi", "istat.it", "ine.es", "bde.es", "cbs.nl",
    "statbel.fgov.be", "belgium.be", "bancaditalia.it", "indec.gob.ar", "bcra.gob.ar", "argentina.gob.ar", "ibge.gov.br", "stats.gov.cn", "e-stat.go.jp", "kostat.go.kr",
    # Research bodies and the scientific literature (peer-reviewed publishers and public repositories).
    "nber.org", "aeaweb.org", "nature.com", "science.org", "thelancet.com", "nejm.org", "bmj.com", "pnas.org", "cairn.info", "persee.fr", "jstor.org", "arxiv.org", "ssrn.com", "sciencedirect.com", "springer.com", "wiley.com", "tandfonline.com", "oup.com", 
    "cambridge.org", "sagepub.com", "plos.org", "frontiersin.org", "mdpi.com", "apa.org", "psychiatry.org", "aap.org", "cochranelibrary.com",
    "nobelprize.org", "plato.stanford.edu", 
    "sciencespo.fr", "ens.fr", "ens-lyon.fr", "college-de-france.fr", 
    # The company itself is a primary source for the identity and products of its own shops.
    "marieblachere.com",
)
CHECKERS_DEFAULT = (
    "factuel.afp.com", "factcheck.afp.com", "lemonde.fr/les-decodeurs", "liberation.fr/checknews", "francetvinfo.fr/vrai-ou-faux", "factcheck.org", "fullfact.org", "snopes.com",
    "reuters.com/fact-check", "apnews.com/hub/ap-fact-check", "politifact.com", "africacheck.org", "leadstories.com", "science.feedback.org", "climatefeedback.org", "healthfeedback.org",
    "bbc.com/news/reality_check", "bbc.co.uk/news/reality_check", "usatoday.com/news/factcheck", "washingtonpost.com/politics/fact-checker",
    "correctiv.org/faktencheck", "faktencheck.dpa.com", "maldita.es", "newtral.es", "pagellapolitica.it", "facta.news", "factcheck.eu", "factcheckeu.info", "edmo.eu", "euvsdisinfo.eu",
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
