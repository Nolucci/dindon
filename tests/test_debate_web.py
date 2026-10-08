"""Reading the web for the verification of claims (docs/regles-du-bot.md, step D4a): the safe fetcher, the quotations that are checked against the page, the sources that count, the two search
services.

Level of proof: SIMULATED. Everything talks to a small web server on this machine (the tests may not leave it), with invented pages; the names of hosts are mapped to this machine by an
injected resolver, so that the real address checks run on real connections. One test performs a real TLS handshake against a local server with a certificate made for the test. Nothing here
has touched the real Internet, nor a real search service: the shape of their answers is that of their documentation.
"""
import ipaddress
import shutil
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dindon.debate import trust, web
from dindon.debate.search import FactCheckSearch, SearchError, SearxSearch, scrub_query
from dindon.debate.web import Fetcher, WebError

PAGE = """<!doctype html><html><head><title>  Chiffres &amp; repères  </title><style>.x{color:red}</style><script>var secret = "ne pas lire";</script></head>
<body><nav>Menu principal Accueil</nav><h1>Le chômage en France</h1><p>Au deuxième trimestre, le taux de chômage s&rsquo;établit à 7,3&nbsp;% de la population active.</p>
<form><input name="q"></form><aside>Publicité</aside><footer>Mentions légales</footer></body></html>"""


class Local:
    """A web server on this machine with the pages the test gives it, and a record of what was asked."""

    def __init__(self, tls: ssl.SSLContext | None = None):
        self.routes: dict = {}
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                route = outer.routes.get(self.path.split("?")[0], (404, {"Content-Type": "text/plain"}, b"not found"))
                try:
                    if callable(route):
                        route(self)
                        return
                    status, headers, body = route
                    self.send_response(status)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        if tls is not None:
            self.httpd.socket = tls.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def page(self, path: str, body: str | bytes = PAGE, type: str = "text/html; charset=utf-8", status: int = 200, **headers) -> None:
        self.routes[path] = (status, {"Content-Type": type, **headers}, body.encode() if isinstance(body, str) else body)

    def url(self, path: str = "/", host: str = "web.test", scheme: str = "http") -> str:
        return f"{scheme}://{host}:{self.port}{path}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def local():
    server = Local()
    yield server
    server.stop()


def fetcher(resolved: list | None = None, **options) -> Fetcher:
    """A fetcher that reaches this machine only (and only it), under any host name: the address checks themselves are the real ones, with a stricter or looser rule given by the test."""
    defaults = {"resolver": lambda host: ["127.0.0.1"], "ip_allowed": lambda ip: ip.is_loopback, "ports": None, "respect_robots": False}
    if resolved is not None:
        defaults["resolver"] = lambda host: (resolved.append(host), ["127.0.0.1"])[1]
    return Fetcher(**{**defaults, **options})


def refused(call, code: str) -> None:
    with pytest.raises(WebError) as error:
        call()
    assert error.value.code == code, str(error.value)


# --- which sources count ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("url", "tier"), [
    ("https://www.insee.fr/fr/statistiques/123", "official"),
    ("https://ec.europa.eu/eurostat/databrowser/view/une", "official"),
    ("https://www.service-public.gouv.fr/particuliers/vosdroits/F1", "official"),
    ("https://factuel.afp.com/doc.afp.com.34ZZ", "checker"),
    ("https://www.lemonde.fr/les-decodeurs/article/2026/10/01/x_123.html", "checker"),
    ("https://www.bra.se/publikationer/x", "official"),
    ("https://www.nature.com/articles/x", "official"),
    ("https://www.politifact.com/factchecks/x", "checker"),
    ("https://fr.wikipedia.org/wiki/Berlin", "other"),                                    # an encyclopedia is context, not a source that condemns
    ("https://www.lemonde.fr/politique/article/2026/10/01/x_123.html", "other"),           # a newspaper is not a checker as a whole
    ("https://www.liberation.fr/checknews/2026/10/01/x/", "checker"),
    ("https://www.liberation.fr/politique/x/", "other"),
    ("https://insee.fr.evil.example/phishing", "other"),                                 # the host must be the one, or a subdomain of it
    ("https://notinsee.fr/x", "other"),
    ("https://example.org/gouv.fr", "other"),                                            # nor a name in the path
    ("ftp://insee.fr/x", "other"),
    ("not an address", "other"),
])
def test_only_official_bodies_and_press_checkers_count_as_sources(url, tier):
    assert trust.Trust().tier(url) == tier and trust.Trust().can_condemn(url) == (tier != "other")


def test_the_owner_can_add_sources_without_touching_the_defaults():
    mine = trust.Trust().with_extra(official=("monsite.example/chiffres",), checkers=("verif.example",))
    assert mine.tier("https://monsite.example/chiffres/2026") == "official" and mine.tier("https://monsite.example/blog") == "other"
    assert mine.tier("https://www.verif.example/a") == "checker" and mine.tier("https://www.insee.fr/") == "official"
    assert trust.Trust().tier("https://verif.example/a") == "other"


# --- which addresses may be connected to ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.255.255.254", "10.0.0.5", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "192.0.0.1",
    "224.0.0.1", "255.255.255.255", "198.18.0.1", "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:10.1.2.3", "::ffff:169.254.169.254",                      # IPv6 that hides a private IPv4
    "2002:7f00:0001::1", "2002:0a00:0001::1",                                            # 6to4 around 127.0.0.1 and 10.0.0.1
    "64:ff9b::7f00:1", "64:ff9b::a00:1", "2001:0:4136:e378:8000:63bf:3fff:fdd2",              # NAT64 around 127.0.0.1 and 10.0.0.1, Teredo
])
def test_no_address_of_this_machine_or_its_network_is_ever_connected_to(address):
    assert web.public_only(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "151.101.1.69", "2606:2800:220:1:248:1893:25c8:1946", "2a00:1450:4007:80b::200e", "::ffff:8.8.8.8",
                                     "64:ff9b::c2fe:25a3"])                      # NAT64 around a public IPv4 (what a DNS64 resolver adds)
def test_public_addresses_are_allowed(address):
    assert web.public_only(ipaddress.ip_address(address)) is True


def test_by_default_a_server_on_this_machine_is_refused_before_any_connection(local):
    local.page("/")
    default = Fetcher(resolver=lambda host: ["127.0.0.1"], ports=None, respect_robots=False)                  # (only the resolver is the test's, to avoid the real DNS)
    refused(lambda: default.fetch(local.url("/")), "blocked")
    for literal in ("http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/", "http://[::ffff:7f00:1]/", "http://0.0.0.0/"):
        refused(lambda url=literal: default.fetch(url), "blocked")
    assert local.requests == []


def test_a_name_with_one_forbidden_answer_among_good_ones_is_refused():
    mixed = Fetcher(resolver=lambda host: ["93.184.216.34", "10.0.0.1"], respect_robots=False)
    refused(lambda: mixed.fetch("https://mixed.example/page"), "blocked")


def test_odd_addresses_are_refused_before_anything_is_looked_up():
    default = Fetcher(resolver=lambda host: pytest.fail("the name must not even be resolved"))
    refused(lambda: default.fetch("ftp://example.org/x"), "scheme")
    refused(lambda: default.fetch("file:///etc/passwd"), "scheme")
    refused(lambda: default.fetch("javascript:alert(1)"), "scheme")
    refused(lambda: default.fetch("https://user:secret@example.org/x"), "host")
    refused(lambda: default.fetch("https://example.org@10.0.0.1/x"), "host")
    refused(lambda: default.fetch("https://example.org:8080/x"), "port")
    refused(lambda: default.fetch("https://example.org:22/x"), "port")
    refused(lambda: default.fetch("http:///nohost"), "host")


# --- reading a page -----------------------------------------------------------------------------------------------------------


def test_a_page_is_read_as_text_without_scripts_menus_forms_or_footers(local):
    local.page("/chomage")
    asked = []
    page = fetcher(asked).fetch(local.url("/chomage"))
    assert page.title == "Chiffres & repères" and page.url == local.url("/chomage") and not page.truncated
    assert "Le chômage en France" in page.text and "7,3 % de la population active" in page.text
    for left_out in ("ne pas lire", "color:red", "Menu principal", "Publicité", "Mentions légales", "<p>", "&amp;"):
        assert left_out not in page.text
    assert len(page.sha256) == 64 and asked == ["web.test"]                                                   # one lookup of the name, for the page


def test_the_request_says_who_it_is_asks_for_text_and_connects_to_the_address_that_was_checked(local):
    local.page("/")
    fetcher(contact="direction@example.org").fetch(local.url("/"))
    headers = local.requests[0]["headers"]
    assert headers["user-agent"].startswith("DindonBot/1.0") and "direction@example.org" in headers["user-agent"]
    assert headers["host"] == f"web.test:{local.port}" and headers["accept-encoding"] == "identity" and "text/html" in headers["accept"]
    assert not {"cookie", "authorization", "referer"} & set(headers)


def test_the_name_is_looked_up_once_per_address_not_again_by_the_connection(local):
    """A name that answers a public address the first time and a private one the second (DNS rebinding) cannot trick the connection: it goes to the address that was checked."""
    local.page("/")
    answers = iter([["127.0.0.1"], ["10.0.0.1"], ["10.0.0.1"]])
    assert fetcher(resolver=lambda host: next(answers)).fetch(local.url("/")).text


@pytest.mark.parametrize(("encoding", "body", "expected"), [
    ("text/html; charset=iso-8859-1", "<p>Prix : 3,5 € à Noël — élevé</p>".encode("latin-1", "replace"), "Prix : 3,5 ? à No"),
    ("text/html", b'<html><head><meta charset="windows-1252"></head><body><p>Caf\xe9 \x93cit\xe9\x94</p></body></html>', "Café “cité”"),
    ("text/html; charset=utf-8", "<p>Déjà vu</p>".encode(), "Déjà vu"),
    ("text/html; charset=nonsense", "<p>Résumé</p>".encode(), "Résumé"),
])
def test_the_character_set_is_the_servers_then_the_pages_then_utf8(local, encoding, body, expected):
    local.page("/", body, encoding)
    assert expected in fetcher().fetch(local.url("/")).text


def test_a_plain_text_page_is_read_as_it_is(local):
    local.page("/data.txt", "Taux : 7,3 %\n\n\n\nFin", "text/plain; charset=utf-8")
    assert fetcher().fetch(local.url("/data.txt")).text == "Taux : 7,3 %\n\nFin"


@pytest.mark.parametrize(("status", "headers", "code"), [
    (404, {"Content-Type": "text/html"}, "status"),
    (500, {"Content-Type": "text/html"}, "status"),
    (200, {"Content-Type": "application/pdf"}, "type"),
    (200, {"Content-Type": "image/png"}, "type"),
    (200, {}, "type"),
    (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"}, "encoding"),
])
def test_what_is_not_a_text_page_is_refused(local, status, headers, code):
    local.routes["/x"] = (status, headers, b"<p>whatever</p>")
    refused(lambda: fetcher().fetch(local.url("/x")), code)


def test_a_huge_page_is_cut_and_says_so(local):
    local.page("/big", "<p>" + "mot " * 400_000 + "</p>")
    page = fetcher(max_bytes=50_000).fetch(local.url("/big"))
    assert page.truncated and 40_000 < len(page.text) <= 50_000
    shorter = fetcher(max_text=1000).fetch(local.url("/big"))                                                  # (the default limit on bytes read, 1 MB, cuts it first)
    assert shorter.truncated and len(shorter.text) == 1000


# --- redirects ----------------------------------------------------------------------------------------------------------------


def test_redirects_are_followed_a_few_times_and_each_one_is_checked_again(local):
    local.page("/final")
    local.routes["/a"] = (302, {"Location": "/b"}, b"")
    local.routes["/b"] = (301, {"Location": local.url("/final")}, b"")
    page = fetcher().fetch(local.url("/a"))
    assert page.url == local.url("/final") and [r["path"] for r in local.requests] == ["/a", "/b", "/final"]


def test_too_many_redirects_end_the_reading(local):
    local.routes["/loop"] = (302, {"Location": "/loop"}, b"")
    refused(lambda: fetcher().fetch(local.url("/loop")), "redirects")
    assert len(local.requests) == 4                                                                           # the page and three redirects, not more


@pytest.mark.parametrize(("target", "code"), [
    ("http://169.254.169.254/latest/meta-data/", "blocked"), ("http://[::1]:9/", "blocked"), ("http://internal.test/admin", "blocked"),
    ("file:///etc/passwd", "scheme"), ("http://user:pw@web.test/", "host"),
])
def test_a_redirect_to_somewhere_forbidden_is_refused_after_the_first_page_and_never_followed(local, target, code):
    local.routes["/go"] = (302, {"Location": target}, b"")
    only_the_test_server = Fetcher(resolver=lambda host: ["10.0.0.5"] if host == "internal.test" else ["127.0.0.1"], ip_allowed=lambda ip: str(ip) == "127.0.0.1",
                                   ports=None, respect_robots=False)                                          # (exactly this address: not ::1, not the rest of 127.0.0.0/8)
    refused(lambda: only_the_test_server.fetch(local.url("/go")), code)
    assert [r["path"] for r in local.requests] == ["/go"]


# --- slowness -----------------------------------------------------------------------------------------------------------------


def test_a_server_that_does_not_answer_is_given_up_on(local):
    def silent(handler):
        time.sleep(1.5)

    local.routes["/silent"] = silent
    started = time.monotonic()
    refused(lambda: fetcher(timeout=0.3).fetch(local.url("/silent")), "timeout")
    assert time.monotonic() - started < 1.2


def test_a_server_that_drips_a_byte_at_a_time_cannot_outlast_the_total_time(local):
    def drip(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html")
        handler.end_headers()
        for _ in range(60):
            handler.wfile.write(b"x")
            handler.wfile.flush()
            time.sleep(0.1)

    local.routes["/drip"] = drip
    started = time.monotonic()
    refused(lambda: fetcher(timeout=1.0, total_timeout=0.5).fetch(local.url("/drip")), "timeout")
    assert time.monotonic() - started < 2.0


# --- robots.txt ---------------------------------------------------------------------------------------------------------------


def test_robots_txt_is_respected(local):
    local.page("/robots.txt", "User-agent: *\nDisallow: /prive/\n\nUser-agent: DindonBot\nDisallow: /interdit/\n", "text/plain")
    local.page("/ok")
    local.page("/prive/page")
    local.page("/interdit/page")
    strict = fetcher(respect_robots=True)
    assert strict.fetch(local.url("/ok")).text
    refused(lambda: strict.fetch(local.url("/interdit/page")), "robots")                                      # the rules for DindonBot win over the general ones
    assert strict.fetch(local.url("/prive/page")).text                                                         # (the general rule is not meant for it)
    assert [r["path"] for r in local.requests].count("/robots.txt") == 1                                      # read once, then remembered
    assert "/interdit/page" not in [r["path"] for r in local.requests]


def test_a_site_that_forbids_everyone_is_not_read_and_no_robots_file_means_free(local):
    local.page("/robots.txt", "User-agent: *\nDisallow: /\n", "text/plain")
    local.page("/x")
    refused(lambda: fetcher(respect_robots=True).fetch(local.url("/x")), "robots")
    local.routes.pop("/robots.txt")
    assert fetcher(respect_robots=True).fetch(local.url("/x")).text


def test_a_robots_file_that_cannot_be_read_closes_the_site(local):
    local.routes["/robots.txt"] = (503, {"Content-Type": "text/plain"}, b"down")
    local.page("/x")
    refused(lambda: fetcher(respect_robots=True).fetch(local.url("/x")), "robots")


# --- a real TLS handshake -----------------------------------------------------------------------------------------------------


@pytest.fixture
def tls_server(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not installed")
    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server = Local(tls=server_context)
    server.client_context = ssl.create_default_context(cafile=str(cert))
    yield server
    server.stop()


def test_a_secure_page_is_read_with_the_certificate_checked_against_the_host_name(tls_server):
    tls_server.page("/")
    page = fetcher(ssl_context=tls_server.client_context).fetch(tls_server.url("/", host="localhost", scheme="https"))
    assert "Le chômage en France" in page.text and tls_server.requests[0]["headers"]["host"] == f"localhost:{tls_server.port}"


def test_the_connection_is_pinned_to_an_address_but_the_certificate_is_still_checked_against_the_name(tls_server):
    """The address is the one checked beforehand, yet a server that is not the one the name stands for is refused: the name `other.test` is not on the certificate."""
    tls_server.page("/")
    refused(lambda: fetcher(ssl_context=tls_server.client_context).fetch(tls_server.url("/", host="other.test", scheme="https")), "tls")
    assert tls_server.requests == []                                                                           # the handshake failed: no request was sent


def test_a_certificate_that_nobody_vouches_for_is_refused(tls_server):
    tls_server.page("/")
    refused(lambda: fetcher().fetch(tls_server.url("/", host="localhost", scheme="https")), "tls")           # the default context does not know this certificate


# --- text and quotations ------------------------------------------------------------------------------------------------------


def test_html_becomes_lines_and_the_odd_html_does_not_break_it():
    title, text = web.extract_text("<html><body><div>Un</div><div>Deux<br>Trois</div><ul><li>a</li><li>b</li></ul><p>&eacute;t&#233; &lt;3</p><script>x</script><p>fin")
    assert title == "" and text.split("\n") == ["Un", "Deux", "Trois", "a", "b", "été <3", "fin"]
    assert web.extract_text("")[1] == "" and web.extract_text("<<<>>>&&&")[1] != "<script>"


def test_a_block_that_is_only_links_is_a_menu_and_is_left_out_while_content_that_holds_a_link_stays():
    html = ('<div><a href="/a">Accueil</a> <a href="/b">Actualités</a> <a href="/c">Contact</a></div><p>Le Sénat compte <a href="/x">348 sénateurs</a> depuis 2023.</p>'
            '<ul><li><a href="/1">Groupes politiques</a></li><li><a href="/2">Commissions</a></li></ul><table><tr><td><a href="/p">Paris</a></td><td>2,1 millions</td></tr></table>')
    _, text = web.extract_text(html)
    for menu in ("Accueil", "Actualités", "Contact", "Groupes politiques", "Commissions"):
        assert menu not in text
    assert "Le Sénat compte 348 sénateurs depuis 2023." in text and "Paris 2,1 millions" in text


QUOTE = "le taux de chômage s'établit à 7,3 % de la population active"


@pytest.mark.parametrize("page_text", [
    "Au deuxième trimestre, le taux de chômage s’établit à 7,3 % de la population active.",                  # typographic apostrophe
    "…LE TAUX DE CHÔMAGE S'ÉTABLIT À 7,3 % DE LA POPULATION ACTIVE…",                                         # case
    "le taux de chômage\n  s'établit à 7,3 % de la population   active",                          # lines, narrow and non-breaking spaces
    "le taux de chômage s'établit à 7,3% de la population active",                                           # French spacing before %
])
def test_a_quotation_is_found_whatever_the_spaces_and_typography(page_text):
    assert web.contains_quote(page_text, QUOTE)


@pytest.mark.parametrize(("page_text", "quote"), [
    ("le taux de chômage s'établit à 7,8 % de la population active", QUOTE),                                  # a different figure
    ("la population active compte 7,3 % de chômeurs, le taux de chômage s'établit", QUOTE),                  # same words, another order
    ("le taux de chômage, selon les sources, s'établit à 7,3 % de la population active", QUOTE),              # something in the middle
    ("Au deuxième trimestre, le taux de chômage s'établit à 7,3 % de la population active.", "7,3 %"),        # too short to prove anything
    ("x " * 500, "x " * 250),                                                                                  # too long to be a quotation
    ("", QUOTE),
])
def test_a_quotation_that_is_not_on_the_page_is_not_a_proof(page_text, quote):
    assert not web.contains_quote(page_text, quote)


# --- what is asked of a search service ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [
    ("taux de chômage en France en 2026", "taux de chômage en France en 2026"),
    ("<@1000000000000000001> a dit que le SMIC est à 1 800 euros", "a dit que le SMIC est à 1 800 euros"),
    ("regarde https://exemple.org/a?b=1 le SMIC", "regarde le SMIC"),
    ("écris à jean.dupont@example.org pour la dette", "écris à pour la dette"),
    ("appelle le 06 12 34 56 78 pour la dette à 3 500 000 000 euros", "appelle le pour la dette à 3 500 000 000 euros"),    # the phone goes, the figure stays
    ("le salon <#1234567890123456789> et le compte 1000000000000000009", "le salon et le compte"),
    ("@pseudo dit que la dette est à 110 % du PIB", "dit que la dette est à 110 % du PIB"),
])
def test_what_is_sent_to_a_search_service_has_no_mention_address_or_identifier(raw, expected):
    assert scrub_query(raw) == expected


def test_a_query_is_short():
    cut = scrub_query("la dette publique " * 40)
    assert 0 < len(cut) <= 200 and not cut.endswith(" ")


# --- the two search services --------------------------------------------------------------------------------------------------


SEARX = '{"results": [{"url": "https://www.insee.fr/a", "title": "A", "content": "texte a"}, {"url": "https://www.insee.fr/a", "title": "doublon"}, {"url": "javascript:x", "title": "mauvais"}, {"url": "https://x.example/b", "title": "B"}]}'


def test_searx_gives_hits_without_duplicates_or_odd_addresses_and_sends_a_clean_query(local):
    local.page("/search", SEARX, "application/json")
    hits = SearxSearch(f"http://127.0.0.1:{local.port}").search("<@100000000000000001> chômage 2026 https://spam.example", limit=8)
    assert [(h.url, h.title, h.via) for h in hits] == [("https://www.insee.fr/a", "A", "searxng"), ("https://x.example/b", "B", "searxng")]
    path = local.requests[0]["path"]
    assert "q=ch%C3%B4mage+2026" in path and "format=json" in path and "language=fr" in path and "spam" not in path and "100000000000000001" not in path


def test_searx_limits_the_hits_and_does_not_ask_for_an_empty_query(local):
    local.page("/search", SEARX, "application/json")
    service = SearxSearch(f"http://127.0.0.1:{local.port}")
    assert len(service.search("chômage", limit=1)) == 1
    assert service.search("   <@100000000000000001>  ") == [] and len(local.requests) == 1


@pytest.mark.parametrize(("status", "body"), [(403, "forbidden"), (429, "slow down"), (500, "oops")])
def test_a_search_service_that_refuses_is_an_error_with_its_status(local, status, body):
    local.page("/search", body, "text/plain", status=status)
    with pytest.raises(SearchError) as error:
        SearxSearch(f"http://127.0.0.1:{local.port}").search("chômage")
    assert error.value.status == status


def test_a_search_service_that_answers_nonsense_or_is_not_there_is_an_error(local):
    local.page("/search", "<html>not json</html>", "text/html")
    with pytest.raises(SearchError):
        SearxSearch(f"http://127.0.0.1:{local.port}").search("chômage")
    local.page("/search", "[1, 2]", "application/json")
    with pytest.raises(SearchError):
        SearxSearch(f"http://127.0.0.1:{local.port}").search("chômage")
    with pytest.raises(SearchError) as error:
        SearxSearch("http://127.0.0.1:9", timeout=1).search("chômage")
    assert error.value.status is None


FACTCHECK = """{"claims": [{"text": "Le chômage a doublé", "claimant": "Un tweet", "claimReview": [
  {"publisher": {"name": "AFP Factuel", "site": "factuel.afp.com"}, "url": "https://factuel.afp.com/doc.1", "title": "Non, le chômage n'a pas doublé",
   "reviewDate": "2026-09-01T00:00:00Z", "textualRating": "Faux", "languageCode": "fr"},
  {"publisher": {"site": "liberation.fr"}, "url": "https://www.liberation.fr/checknews/x", "title": "CheckNews", "textualRating": "Trompeur"}]},
  {"text": "autre", "claimReview": [{"url": "ftp://bad", "title": "x"}]}]}"""


def test_factcheck_gives_the_fact_checks_that_were_published_with_their_rating_and_desk(local):
    local.page("/v1alpha1/claims:search", FACTCHECK, "application/json")
    hits = FactCheckSearch("SECRET-KEY", f"http://127.0.0.1:{local.port}").search("le chômage a doublé")
    assert [(h.url, h.rating, h.publisher, h.claim) for h in hits] == [
        ("https://factuel.afp.com/doc.1", "Faux", "AFP Factuel", "Le chômage a doublé"),
        ("https://www.liberation.fr/checknews/x", "Trompeur", "liberation.fr", "Le chômage a doublé")]
    assert hits[0].reviewed_on == "2026-09-01T00:00:00Z" and hits[0].via == "factcheck"
    path = local.requests[0]["path"]
    assert "languageCode=fr" in path and "query=le+ch%C3%B4mage+a+doubl%C3%A9" in path and "key=SECRET-KEY" in path


def test_the_key_never_appears_in_an_error_and_without_a_key_nothing_is_asked(local):
    local.page("/v1alpha1/claims:search", "denied", "text/plain", status=403)
    service = FactCheckSearch("SECRET-KEY", f"http://127.0.0.1:{local.port}")
    with pytest.raises(SearchError) as error:
        service.search("chômage")
    assert "SECRET-KEY" not in str(error.value) and "127.0.0.1" not in str(error.value) and error.value.status == 403
    with pytest.raises(SearchError) as unreachable:
        FactCheckSearch("SECRET-KEY", "http://127.0.0.1:9", timeout=1).search("chômage")
    assert "SECRET-KEY" not in str(unreachable.value)
    before = len(local.requests)
    assert FactCheckSearch("", f"http://127.0.0.1:{local.port}").search("chômage") == [] and len(local.requests) == before

