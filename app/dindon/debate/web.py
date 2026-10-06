"""Reading a page of the web, safely. Used by the verification of claims in a debate (docs/DEBAT.md): the address of a page comes from a search, that is to say from
anybody, and what the page says is text written by anybody. Nothing here trusts either.

What it protects against:

* **Reaching this machine or its network** (SSRF). Only public addresses are connected to: every address that the name resolves to is checked (private, loopback, link-local,
  carrier-grade NAT, reserved, multicast, and IPv6 forms that hide an IPv4 address: mapped, 6to4, Teredo, NAT64). The check is made again on **every redirect**, and the
  connection goes to the address that was checked (not to a name that could answer differently the second time: DNS rebinding), while TLS still checks the certificate
  against the real host name. Only the ports 80 and 443, and no credentials in the address.
* **Heavy or hostile answers**: a limit on the size read (the rest is dropped), on the total time, on redirects, only text pages (HTML, plain text), no compressed
  answer, nothing is executed, no cookie is kept, no script is run.
* **Pages that do not want to be read**: `robots.txt` is respected (an unreachable one counts as a refusal, as the standard says), and the program says who it is.
* **A quote that is not on the page**: `contains_quote` is how a quotation is *verified*, so that nothing is shown as « the page says » unless it does.

What it does not do: it does not judge whether a page is right (that is `trust.py` and the verification), and it does not defend against a page that lies. Text from a page is
data, never an instruction (the verification enforces that where the model reads it).
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
import unicodedata
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

USER_AGENT_TOKEN = "DindonBot"
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
QUOTE_MIN, QUOTE_MAX = 25, 400                 # a quotation that proves something is a sentence, not a number; and it stays a quotation, not a page
NAT64 = ipaddress.ip_network("64:ff9b::/96")
TEREDO = ipaddress.ip_network("2001::/32")


class WebError(Exception):
    """A page that was not read. `code`: scheme, host, port, blocked, robots, redirects, timeout, network, tls, status, type, encoding."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}{': ' + detail if detail else ''}")
        self.code = code


@dataclass(frozen=True)
class Page:
    url: str                    # where it was read (after redirects)
    title: str
    text: str
    sha256: str                 # of what was read, so that the same page can be told from a changed one
    truncated: bool             # the page was longer than the limit: only its beginning is here


def public_only(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether Dindon may connect to this address: only addresses of the public Internet."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return public_only(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return public_only(ip.sixtofour)
        if ip in TEREDO or ip in NAT64:
            return False
    return ip.is_global and not ip.is_multicast


def _system_resolver(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except OSError as error:
        raise WebError("host", "the name does not resolve") from error


@dataclass(frozen=True)
class _Target:
    scheme: str
    host: str
    port: int
    path: str
    ips: tuple[str, ...]                                   # every address of the name, all checked; they are tried in turn

    @property
    def origin(self) -> tuple[str, str, int]:
        return self.scheme, self.host, self.port


class _Pinned:
    """Connects to a given address while the request, and the TLS check, are about the real host name."""

    @staticmethod
    def open(target: _Target, timeout: float, context: ssl.SSLContext | None) -> http.client.HTTPConnection:
        def reach() -> socket.socket:
            """The first address that answers (a name can have an IPv6 address that this machine cannot reach)."""
            failure: OSError = OSError("no address")
            for ip in target.ips:
                try:
                    return socket.create_connection((ip, target.port), timeout)
                except OSError as error:
                    failure = error
            raise failure

        if target.scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(target.host, target.port, timeout=timeout, context=context or ssl.create_default_context())

            def connect() -> None:
                connection.sock = connection._context.wrap_socket(reach(), server_hostname=target.host)   # type: ignore[attr-defined]
        else:
            connection = http.client.HTTPConnection(target.host, target.port, timeout=timeout)

            def connect() -> None:
                connection.sock = reach()
        connection.connect = connect                                             # type: ignore[method-assign]
        return connection


class Fetcher:
    def __init__(self, *, resolver: Callable[[str], list[str]] = _system_resolver, ip_allowed: Callable[[ipaddress.IPv4Address | ipaddress.IPv6Address], bool] = public_only,
                 contact: str = "", timeout: float = 10.0, total_timeout: float = 20.0, max_bytes: int = 1_000_000, max_redirects: int = 3, max_text: int = 200_000,
                 ports: tuple[int, ...] | None = (80, 443), respect_robots: bool = True, ssl_context: ssl.SSLContext | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._resolve, self._ip_allowed = resolver, ip_allowed
        self.user_agent = f"{USER_AGENT_TOKEN}/1.0 (+fact-checking in a Discord debate{'; ' + contact if contact else ''})"
        self._timeout, self._total_timeout, self._max_bytes, self._max_redirects, self._max_text = timeout, total_timeout, max_bytes, max_redirects, max_text
        self._ports, self._respect_robots, self._context, self._clock = ports, respect_robots, ssl_context, clock
        self._robots: dict[tuple[str, str, int], tuple[float, urllib.robotparser.RobotFileParser | None]] = {}   # origin -> (until, rules; None = everything refused)

    # --- checking an address --------------------------------------------------------------------------------------

    def _target(self, url: str) -> _Target:
        try:
            parts = urlsplit(url.strip())
            port = parts.port
        except ValueError as error:
            raise WebError("host", "malformed address") from error
        if parts.scheme not in ("http", "https"):
            raise WebError("scheme", parts.scheme or "none")
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise WebError("host", "credentials in the address")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise WebError("host", "no host")
        port = port or (443 if parts.scheme == "https" else 80)
        if self._ports is not None and port not in self._ports:
            raise WebError("port", str(port))
        try:
            candidates = [str(ipaddress.ip_address(host))]                       # an address typed as such
        except ValueError:
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as error:
                raise WebError("host", "malformed name") from error
            candidates = self._resolve(host)
        if not candidates:
            raise WebError("host", "the name does not resolve")
        for candidate in candidates:                                              # one forbidden answer among the others is enough to refuse
            if not self._ip_allowed(ipaddress.ip_address(candidate)):
                raise WebError("blocked", "not an address of the public Internet")
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return _Target(parts.scheme, host, port, path, tuple(candidates))

    # --- one request ----------------------------------------------------------------------------------------------

    def _get(self, target: _Target, accept: str, limit: int, deadline: float) -> tuple[int, dict[str, str], bytes, bool]:
        """(status, headers in lower case, body read up to `limit`, whether the body was longer). Nothing is followed here."""
        connection = _Pinned.open(target, self._timeout, self._context)
        try:
            connection.request("GET", target.path, headers={"User-Agent": self.user_agent, "Accept": accept, "Accept-Language": "fr,en;q=0.7",
                                                            "Accept-Encoding": "identity", "Connection": "close"})
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            body, truncated = b"", False
            if response.status == 200:
                chunks, size = [], 0
                while True:
                    if self._clock() > deadline:
                        raise WebError("timeout", "too slow")
                    chunk = response.read1(min(65_536, limit + 1 - size))      # (not `read`: it waits for the whole amount, and a server dripping a byte at a time would outlast the deadline)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        truncated = True
                        break
                body = b"".join(chunks)[:limit]
            return response.status, headers, body, truncated
        except WebError:
            raise
        except TimeoutError as error:
            raise WebError("timeout") from error
        except ssl.SSLError as error:
            raise WebError("tls", error.__class__.__name__) from error
        except (OSError, http.client.HTTPException) as error:
            raise WebError("network", error.__class__.__name__) from error
        finally:
            connection.close()

    # --- robots.txt -----------------------------------------------------------------------------------------------

    def _allowed_by_robots(self, target: _Target, deadline: float) -> bool:
        if not self._respect_robots:
            return True
        now = self._clock()
        until, rules = self._robots.get(target.origin, (0.0, None))
        if now >= until:
            rules = self._read_robots(target, deadline)
            self._robots[target.origin] = (now + 3600, rules)
        return rules is not None and rules.can_fetch(USER_AGENT_TOKEN, f"{target.scheme}://{target.host}:{target.port}{target.path}")

    def _read_robots(self, target: _Target, deadline: float) -> urllib.robotparser.RobotFileParser | None:
        try:
            status, headers, body, _ = self._get(_Target(target.scheme, target.host, target.port, "/robots.txt", target.ips), "text/plain", 500_000, deadline)
        except WebError:
            return None                                                           # cannot be reached: the standard says to treat the site as closed
        rules = urllib.robotparser.RobotFileParser()
        if 200 <= status < 300:
            rules.parse(body.decode("utf-8", errors="replace").splitlines())
            return rules
        if 400 <= status < 500:                                                   # no robots.txt: everything is allowed
            rules.parse([])
            return rules
        return None

    # --- reading a page -------------------------------------------------------------------------------------------

    def fetch(self, url: str) -> Page:
        """The text of the page at this address. Raises WebError (with a `code`) for anything that is not a page that may be read."""
        deadline = self._clock() + self._total_timeout
        current = url
        for _ in range(self._max_redirects + 1):
            target = self._target(current)
            if not self._allowed_by_robots(target, deadline):
                raise WebError("robots")
            status, headers, body, truncated = self._get(target, "text/html,application/xhtml+xml,text/plain;q=0.9", self._max_bytes, deadline)
            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                current = urljoin(current, headers["location"])
                continue
            if status != 200:
                raise WebError("status", str(status))
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise WebError("encoding", headers["content-encoding"])
            kind = headers.get("content-type", "").split(";")[0].strip().lower()
            if kind not in TEXT_TYPES:
                raise WebError("type", kind or "unknown")
            title, text = extract_text(decode(body, headers.get("content-type", "")), plain=kind == "text/plain")
            return Page(current, title, text[: self._max_text], hashlib.sha256(body).hexdigest(), truncated or len(text) > self._max_text)
        raise WebError("redirects")


# --- from bytes to text ---------------------------------------------------------------------------------------------------------


def decode(body: bytes, content_type: str) -> str:
    """The text of a page: in the character set that the server announces, or else that the page announces itself, or else UTF-8."""
    header = re.search(r"charset=([\w.:-]+)", content_type, re.I)
    meta = re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", body[:4096], re.I)
    charset = header.group(1) if header else meta.group(1).decode("ascii", "ignore") if meta else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "object", "canvas", "nav", "footer", "aside", "form", "button", "select", "dialog"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre", "hr", "header", "main"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._in_link = 0
        self._block: list[str] = []
        self._chars = self._link_chars = 0

    def _end_block(self) -> None:
        """A block that is (almost) nothing but links is a menu, not content: it is left out. The rest becomes a line."""
        text = "".join(self._block)
        if text.strip() and not (self._chars and self._link_chars >= 0.9 * self._chars):
            self.parts.append(text)
        self.parts.append("\n")
        self._block, self._chars, self._link_chars = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self.SKIP:
            self._skip += 1
        elif tag == "a":
            self._in_link += 1
        elif tag in ("td", "th"):
            self._block.append(" ")                                         # the cells of a row do not run together (« Paris2,1 »)
        elif tag in self.BLOCK:
            self._end_block()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "a":
            self._in_link = max(0, self._in_link - 1)
        elif tag in ("td", "th"):
            self._block.append(" ")
        elif tag in self.BLOCK:
            self._end_block()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._block.append(data)
            size = len(data.strip())
            self._chars += size
            if self._in_link:
                self._link_chars += size

    def close(self):
        super().close()
        self._end_block()


def extract_text(html: str, plain: bool = False) -> tuple[str, str]:
    """(title, readable text) of a page. Scripts, styles, menus, footers and forms are left out; blocks become lines."""
    if plain:
        title, text = "", html
    else:
        parser = _Text()
        parser.feed(html)
        parser.close()
        title, text = parser.title, "".join(parser.parts)                       # (blocks that are only links, the menus, are already out)
    text = re.sub(r"[ \t\r\f\v  ]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text) if plain else re.sub(r"\n+", "\n", text)       # a web page: one block per line; a text file keeps its paragraphs
    return " ".join(title.split()), text.strip()


# --- is it really on the page ---------------------------------------------------------------------------------------------------


_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"', "–": "-", "—": "-", "…": "..."})


def normalize(text: str) -> str:
    """Text as compared when checking a quotation: spaces, typographic quotes, dashes and the French spacing before « % : ; ? ! » do not count; case does not either."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return re.sub(r"\s+([%:;?!])", r"\1", text)


def contains_quote(page_text: str, quote: str) -> bool:
    """Whether the words of `quote` are, in that order and without anything between them, on the page. This is what makes a quotation a proof: a model can invent a
    sentence, it cannot invent that the page says it. A quotation that is too short to prove anything, or too long to be one, is refused."""
    wanted = normalize(quote)
    return QUOTE_MIN <= len(wanted) <= QUOTE_MAX and wanted in normalize(page_text)
