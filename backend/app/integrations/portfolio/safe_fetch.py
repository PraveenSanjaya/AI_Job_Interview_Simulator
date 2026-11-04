"""SSRF-hardened fetching of candidate-supplied public web pages.

Threat: a user submits a URL that makes the server call something internal (localhost,
private networks, cloud metadata services) and reads the result back. Controls:

* Only ``http``/``https`` on ports 80/443, no credentials in the URL, no IP literals or
  numeric host spellings that are not public, no single-label or internal-looking names.
* The hostname is resolved by us and **every** returned address must be a public,
  globally routable address. One private address among several rejects the host.
* The request is sent to the **validated IP address itself** (the original hostname is
  sent as the ``Host`` header and as the TLS SNI name, so certificates are still checked
  against it). The name is never resolved a second time, which defeats DNS rebinding.
* Redirects are followed manually (at most 3); every hop goes through the full
  validation above, and https -> http downgrades are refused.
* Strict per-request timeout, response-size cap (counted after decompression),
  content-type allow-list; proxy environment variables are ignored; no cookies are
  stored and no JavaScript is ever executed.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit

import httpx

from app.integrations.errors import PortfolioFetchError, PortfolioUrlRejectedError

ALLOWED_PORTS = {"http": 80, "https": 443}
MAX_URL_LENGTH = 2000
MAX_REDIRECTS = 3
MAX_ADDRESSES = 10
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
USER_AGENT = (
    "AIJobInterviewSimulatorBot/0.1 (fetching a page the candidate asked us to analyse; "
    "single page loads, no JavaScript)"
)

_BLOCKED_SUFFIXES = (
    ".local",
    ".localhost",
    ".localdomain",
    ".internal",
    ".intranet",
    ".lan",
    ".home",
    ".corp",
    ".private",
    ".home.arpa",
)
# Labels like "2130706433", "0x7f", "0177" are legacy spellings of IP address parts.
_NUMERIC_LABEL = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BLOCKED_V6_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",  # NAT64 (embeds an IPv4 address)
        "64:ff9b:1::/48",
        "2002::/16",  # 6to4
        "2001::/32",  # Teredo
        "::/96",  # IPv4-compatible
    )
]

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    """Resolve ``host`` with the OS resolver; returns unique IP address strings."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise PortfolioFetchError(
            "The portfolio host could not be found", code="portfolio_unreachable"
        ) from None
    seen: dict[str, None] = {}
    for info in infos:
        seen.setdefault(str(info[4][0]).split("%")[0], None)
    return list(seen)[:MAX_ADDRESSES]


def is_public_ip(address: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(str(ip.ipv4_mapped))
        if any(ip in network for network in _BLOCKED_V6_NETWORKS):
            return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


@dataclass(frozen=True)
class ParsedUrl:
    scheme: str
    host: str  # lower-case, IDNA-encoded
    port: int
    path_and_query: str


def _reject(message: str) -> PortfolioUrlRejectedError:
    return PortfolioUrlRejectedError(message)


def parse_public_url(raw: str) -> ParsedUrl:
    """Syntax-level validation (no DNS). Raises ``PortfolioUrlRejectedError``."""
    text = (raw or "").strip()
    if not text or len(text) > MAX_URL_LENGTH or any(ord(c) < 33 or ord(c) == 127 for c in text):
        raise _reject("Enter a valid web address (http:// or https://)")
    try:
        parts: SplitResult = urlsplit(text)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise _reject("Enter a valid web address (http:// or https://)") from None

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise _reject("Only http:// and https:// addresses are allowed")
    if parts.username is not None or parts.password is not None:
        raise _reject("Web addresses with embedded credentials are not allowed")
    if not hostname:
        raise _reject("The web address has no host")
    if port is not None and port != ALLOWED_PORTS[scheme]:
        raise _reject("Only the standard web ports (80 and 443) are allowed")
    if "%" in hostname:
        raise _reject("The host name is not allowed")

    host = _normalise_host(hostname)
    return ParsedUrl(
        scheme=scheme,
        host=host,
        port=ALLOWED_PORTS[scheme],
        path_and_query=(parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
    )


def _normalise_host(hostname: str) -> str:
    host = hostname.rstrip(".").lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not is_public_ip(str(ip)):
            raise _reject("That address is not a public web address")
        return str(ip)

    labels = host.split(".")
    if all(_NUMERIC_LABEL.match(label) for label in labels):
        raise _reject("Numeric host names are not allowed")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise _reject("The host name is not valid") from None
    if (
        "." not in host
        or host == "localhost"
        or host.endswith(_BLOCKED_SUFFIXES)
        or len(host) > 253
        or not all(_DNS_LABEL.fullmatch(label) for label in host.split("."))
    ):
        raise _reject("That address is not a public web address")
    return host


@dataclass(frozen=True)
class FetchResult:
    url: str  # final URL after redirects, using the original host name
    status: int
    content_type: str
    body: bytes


class SafeFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
        max_bytes: int = 1_000_000,
    ) -> None:
        self._resolver = resolver
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        # trust_env=False: ignore HTTP(S)_PROXY and netrc so nothing bypasses the IP checks.
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(),
            follow_redirects=False,
            trust_env=False,
            timeout=timeout_seconds,
            cookies=None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        current = parse_public_url(url)
        for hop in range(MAX_REDIRECTS + 1):
            try:
                async with asyncio.timeout(self._timeout * 2):
                    response, body = await self._get_once(current)
            except (TimeoutError, httpx.TimeoutException):
                raise PortfolioFetchError(
                    "The portfolio site took too long to respond", code="portfolio_timeout"
                ) from None

            if response.status_code in (301, 302, 303, 307, 308):
                if hop == MAX_REDIRECTS:
                    raise PortfolioFetchError(
                        "The portfolio redirected too many times", code="portfolio_redirects"
                    )
                current = self._next_hop(current, response.headers.get("location"))
                continue
            if response.status_code != 200:
                raise PortfolioFetchError(
                    f"The portfolio site answered with HTTP {response.status_code}",
                    code="portfolio_http_error",
                )
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            return FetchResult(
                url=_display_url(current),
                status=response.status_code,
                content_type=content_type,
                body=body,
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _next_hop(self, current: ParsedUrl, location: str | None) -> ParsedUrl:
        if not location:
            raise PortfolioFetchError(
                "The portfolio redirect was invalid", code="portfolio_http_error"
            )
        if "\\" in location:
            # Browsers read "/\host" as "//host"; refuse the ambiguity outright.
            raise PortfolioUrlRejectedError("The portfolio redirect target is not allowed")
        target = parse_public_url(urljoin(_display_url(current), location))
        if current.scheme == "https" and target.scheme == "http":
            raise PortfolioUrlRejectedError("The portfolio redirected from https to http")
        return target

    async def _resolve_public(self, parsed: ParsedUrl) -> list[str]:
        try:
            ipaddress.ip_address(parsed.host)
            addresses = [parsed.host]
        except ValueError:
            addresses = await asyncio.wait_for(
                self._resolver(parsed.host, parsed.port), timeout=self._timeout
            )
        if not addresses:
            raise PortfolioFetchError(
                "The portfolio host could not be found", code="portfolio_unreachable"
            )
        if not all(is_public_ip(a) for a in addresses):
            # One internal address is enough to refuse (mixed answers are a rebinding trick).
            raise PortfolioUrlRejectedError("That address is not a public web address")
        return addresses

    async def _get_once(self, parsed: ParsedUrl) -> tuple[httpx.Response, bytes]:
        addresses = await self._resolve_public(parsed)
        last_error: Exception | None = None
        for address in addresses[:3]:
            ip_host = f"[{address}]" if ":" in address else address
            request = self._client.build_request(
                "GET",
                f"{parsed.scheme}://{ip_host}:{parsed.port}{parsed.path_and_query}",
                headers={
                    "Host": parsed.host,
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                    "Accept-Language": "en",
                },
                extensions={"sni_hostname": parsed.host},
            )
            try:
                response = await self._client.send(request, stream=True)
            except httpx.TimeoutException:
                raise
            except httpx.HTTPError as error:
                last_error = error
                continue
            try:
                return response, await self._read(response)
            finally:
                await response.aclose()
        raise PortfolioFetchError(
            "The portfolio site could not be reached", code="portfolio_unreachable"
        ) from last_error

    async def _read(self, response: httpx.Response) -> bytes:
        if response.status_code != 200:
            return b""  # redirects and errors: the body is never read
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise PortfolioFetchError(
                "The portfolio page is not an HTML or text page",
                code="portfolio_unsupported_content_type",
            )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise PortfolioFetchError("The portfolio page is too large", code="portfolio_too_large")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():  # decoded bytes: decompression bombs count
            total += len(chunk)
            if total > self._max_bytes:
                raise PortfolioFetchError(
                    "The portfolio page is too large", code="portfolio_too_large"
                )
            chunks.append(chunk)
        return b"".join(chunks)


def _display_url(parsed: ParsedUrl) -> str:
    netloc = f"[{parsed.host}]" if ":" in parsed.host else parsed.host
    return f"{parsed.scheme}://{netloc}{parsed.path_and_query}"
