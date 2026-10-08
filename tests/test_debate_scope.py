"""The limit on what Dindon does on the Internet for one claim (docs/regles-du-bot.md): two queries, three pages, only pages that the search returned, nothing for an empty query.

Level of proof: SIMULATED. In-memory search services and fetcher: nothing is sent anywhere.
"""
import pytest

from dindon.debate import scope
from dindon.debate.scope import Lookup, OutOfScope
from dindon.debate.search import Hit, SearchError
from dindon.debate.web import Page, WebError


class Service:
    def __init__(self, hits=(), error=None):
        self.hits, self.error, self.asked = list(hits), error, []

    def search(self, query, language="fr", limit=8):
        self.asked.append((query, language))
        if self.error:
            raise self.error
        return list(self.hits)


class Reader:
    def __init__(self, fail=None):
        self.read, self.fail = [], fail

    def fetch(self, url):
        self.read.append(url)
        if self.fail:
            raise self.fail
        return Page(url, "T", "texte", "0" * 64, False)


def hit(url, via="searxng"):
    return Hit(url, "titre", "extrait", via)


A, B, C, D, E, F = (hit(f"https://www.insee.fr/{x}") for x in "abcdef")


def test_a_query_goes_to_every_service_in_the_same_cleaned_form_and_the_hits_are_merged_without_duplicates():
    check, web = Service([hit("https://factuel.afp.com/1", "factcheck"), A]), Service([A, B])
    lookup = Lookup([check, web], Reader())
    found = lookup.search("<@100000000000000001> chômage 2026 https://spam.example")
    assert [h.url for h in found] == ["https://factuel.afp.com/1", A.url, B.url]
    assert check.asked == web.asked == [("chômage 2026", "fr")]                                       # no mention, no address, the same sentence for both
    assert lookup.spent() == {"queries": 1, "pages": 0}


def test_only_two_queries_are_sent_for_one_claim_and_a_failed_one_counts():
    service = Service([A], error=SearchError("down", 500))
    lookup = Lookup([service], Reader())
    for _ in range(2):
        with pytest.raises(SearchError):
            lookup.search("chômage")
    with pytest.raises(OutOfScope) as error:
        lookup.search("chômage 2026")
    assert error.value.code == "queries" and len(service.asked) == 2                                   # the third was never sent, and nothing was retried by itself


def test_nothing_is_sent_for_a_query_with_nothing_left_in_it():
    service = Service([A])
    lookup = Lookup([service], Reader())
    for empty in ("", "   ", "<@100000000000000001>", "https://spam.example"):
        with pytest.raises(OutOfScope) as error:
            lookup.search(empty)
        assert error.value.code == "empty"
    assert service.asked == [] and lookup.spent() == {"queries": 0, "pages": 0}


def test_one_service_down_is_not_the_end_but_all_of_them_down_is():
    lookup = Lookup([Service(error=SearchError("down")), Service([A])], Reader())
    assert [h.url for h in lookup.search("chômage")] == [A.url]
    with pytest.raises(SearchError):
        Lookup([Service(error=SearchError("down")), Service(error=SearchError("refused", 403))], Reader()).search("chômage")


def test_only_a_page_that_the_search_returned_can_be_read():
    reader = Reader()
    lookup = Lookup([Service([A, B])], reader)
    with pytest.raises(OutOfScope) as before:                                                          # before any search: nothing is known
        lookup.read(A.url)
    lookup.search("chômage")
    for foreign in ("https://example.org/lien-ecrit-par-un-membre", "http://169.254.169.254/", "https://www.insee.fr/z", A.url + "/autre-page", "javascript:x"):
        with pytest.raises(OutOfScope) as error:
            lookup.read(foreign)
        assert error.value.code == "unlisted"
    assert before.value.code == "unlisted" and reader.read == [] and lookup.spent()["pages"] == 0
    assert lookup.read(A.url).url == A.url and reader.read == [A.url]


def test_an_address_is_the_same_whatever_its_fragment_or_the_case_of_the_host():
    reader = Reader()
    lookup = Lookup([Service([A])], reader)
    lookup.search("chômage")
    lookup.read("HTTPS://WWW.INSEE.FR/a#section-3")
    assert reader.read == [A.url]


def test_only_five_pages_are_read_for_one_claim_and_an_unreadable_one_counts():
    reader = Reader(fail=WebError("status", "404"))
    lookup = Lookup([Service([A, B, C, D, E, F])], reader)
    lookup.search("chômage")
    for page in (A, B, C, D, E):
        with pytest.raises(WebError):
            lookup.read(page.url)
    with pytest.raises(OutOfScope) as error:
        lookup.read(F.url)
    assert error.value.code == "pages" and reader.read == [A.url, B.url, C.url, D.url, E.url] and lookup.spent() == {"queries": 1, "pages": 5}


def test_a_check_that_a_person_asked_for_may_search_and_read_more_but_never_without_a_limit():
    lookup = Lookup([Service([A, B, C, D, E, F])], Reader(), max_queries=scope.DEEP_QUERIES, max_pages=scope.DEEP_PAGES)
    for query in ("a b", "c d", "e f", "g h"):
        lookup.search(query)
    with pytest.raises(OutOfScope):
        lookup.search("i j")
    assert (scope.DEEP_QUERIES, scope.DEEP_PAGES) == (4, 8)


def test_the_limits_can_be_made_stricter_never_looser_by_accident():
    lookup = Lookup([Service([A, B])], Reader(), max_queries=1, max_pages=1)
    lookup.search("chômage")
    with pytest.raises(OutOfScope):
        lookup.search("chômage encore")
    lookup.read(A.url)
    with pytest.raises(OutOfScope):
        lookup.read(B.url)
    assert (Lookup([], Reader())._max_queries, Lookup([], Reader())._max_pages) == (2, 5)


def test_a_lookup_remembers_nothing_beyond_its_claim():
    first, second = Lookup([Service([A])], Reader()), Lookup([Service([B])], Reader())
    first.search("chômage")
    second.search("chômage")
    with pytest.raises(OutOfScope):
        second.read(A.url)                                                                              # what the first claim found is not offered to the second
    assert [h.url for h in second.offered] == [B.url]
