"""SSRF protection for portfolio fetching. No real DNS or network is used."""

import gzip
from collections import defaultdict
from typing import Any

import httpx
import pytest

from app.integrations.errors import PortfolioFetchError, PortfolioUrlRejectedError
from app.integrations.portfolio.safe_fetch import (
    SafeFetcher,
    is_public_ip,
    parse_public_url,
)

pytestmark = pytest.mark.anyio

PUBLIC = "93.184.216.34"


class FakeDNS:
    """Scripted resolver; remembers every lookup."""

    def __init__(self, table: dict[str, list[str]] | None = None) -> None:
        self.table = table or {}
        self.lookups: list[str] = []
        self.answers: dict[str, list[list[str]]] = defaultdict(list)

    async def __call__(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        if self.answers.get(host):
            return self.answers[host].pop(0)
        return self.table.get(host, [PUBLIC])


def fetcher(
    handler: Any = None, dns: FakeDNS | None = None, **kwargs: Any
) -> tuple[SafeFetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def default(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html>ok</html>", headers={"content-type": "text/html"})

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return (handler or default)(request)

    return (
        SafeFetcher(resolver=dns or FakeDNS(), transport=httpx.MockTransport(recording), **kwargs),
        seen,
    )


# ------------------------------------------------------------------ IP classification


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1.2.3",
        "0.0.0.0",  # noqa: S104
        "10.0.0.1",
        "172.16.5.4",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "169.254.0.1",
        "100.64.0.1",  # carrier-grade NAT
        "100.100.100.200",  # Alibaba metadata
        "192.0.0.1",
        "198.18.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd00:ec2::254",  # AWS IPv6 metadata
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.5",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64 wrapping 127.0.0.1
        "2002:7f00:1::1",  # 6to4 wrapping 127.0.0.1
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
        "not-an-ip",
        "",
    ],
)
def test_non_public_addresses_are_blocked(address: str) -> None:
    assert is_public_ip(address) is False


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946"]
)
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public_ip(address) is True


# ------------------------------------------------------------------ URL syntax


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "javascript:alert(1)",
        "data:text/html,hi",
        "//example.com/",
        "example.com",
        "http://",
        "http://user:pass@example.com/",
        "http://user@example.com/",
        "http://example.com:8080/",
        "https://example.com:22/",
        "http://example.com:0/",
        "http://localhost/",
        "http://LOCALHOST/",
        "http://localhost./",
        "http://intranet/",
        "http://metadata/",
        "http://server.local/",
        "http://printer.internal/",
        "http://x.localhost/",
        "http://127.0.0.1/",
        "http://127.1/",
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f000001/",  # hex
        "http://0177.0.0.1/",  # octal
        "http://0x7f.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fe80::1%25eth0]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://192.168.0.1/",
        "http://example.com\n.evil.com/",
        "http://exa mple.com/",
        "http://example.com/\x00",
        "https://" + "a" * 300 + ".com/",
        "http://" + "a" * 2100 + ".com/",
        "http://-bad-.com/",
        "http://exa_mple.com/",
    ],
)
def test_unsafe_or_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(PortfolioUrlRejectedError):
        parse_public_url(url)


@pytest.mark.parametrize(
    ("url", "host", "scheme"),
    [
        ("https://example.com", "example.com", "https"),
        ("http://Example.COM/Path?q=1#frag", "example.com", "http"),
        ("https://example.com:443/x", "example.com", "https"),
        ("http://example.com:80/", "example.com", "http"),
        ("https://sub.domain.example.co.uk/a/b", "sub.domain.example.co.uk", "https"),
        ("https://example.com./", "example.com", "https"),
        ("https://münchen.example/", "xn--mnchen-3ya.example", "https"),
        ("https://93.184.216.34/", "93.184.216.34", "https"),
        (
            "https://[2606:2800:220:1:248:1893:25c8:1946]/",
            "2606:2800:220:1:248:1893:25c8:1946",
            "https",
        ),
    ],
)
def test_ordinary_public_urls_are_accepted(url: str, host: str, scheme: str) -> None:
    parsed = parse_public_url(url)
    assert (parsed.host, parsed.scheme) == (host, scheme)


def test_fragment_is_dropped_and_query_kept() -> None:
    assert parse_public_url("https://example.com/a?b=1#c").path_and_query == "/a?b=1"


# ------------------------------------------------------------------ DNS validation


async def test_host_resolving_to_a_private_address_is_refused_before_any_request() -> None:
    dns = FakeDNS({"evil.example": ["10.0.0.7"]})
    fetch, seen = fetcher(dns=dns)
    with pytest.raises(PortfolioUrlRejectedError):
        await fetch.fetch("https://evil.example/")
    assert seen == [] and dns.lookups == ["evil.example"]


@pytest.mark.parametrize(
    "answers",
    [
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["::ffff:127.0.0.1"],
        [PUBLIC, "10.0.0.1"],  # one bad address poisons the answer
        ["10.0.0.1", PUBLIC],
        [PUBLIC, "fd00:ec2::254"],
    ],
)
async def test_any_non_public_address_in_the_answer_rejects_the_host(answers: list[str]) -> None:
    fetch, seen = fetcher(dns=FakeDNS({"mixed.example": answers}))
    with pytest.raises(PortfolioUrlRejectedError):
        await fetch.fetch("https://mixed.example/")
    assert seen == []


async def test_unresolvable_or_empty_answers_are_reported_cleanly() -> None:
    fetch, seen = fetcher(dns=FakeDNS({"nxdomain.example": []}))
    with pytest.raises(PortfolioFetchError) as error:
        await fetch.fetch("https://nxdomain.example/")
    assert error.value.code == "portfolio_unreachable" and seen == []


async def test_ip_literal_urls_to_public_hosts_skip_dns() -> None:
    dns = FakeDNS()
    fetch, seen = fetcher(dns=dns)
    await fetch.fetch("https://93.184.216.34/")
    assert dns.lookups == [] and len(seen) == 1


# ------------------------------------------------------------------ DNS rebinding


async def test_connection_is_pinned_to_the_validated_ip_not_resolved_again() -> None:
    dns = FakeDNS()
    # First answer is public; a naive client that resolves again would get 127.0.0.1.
    dns.answers["rebind.example"] = [[PUBLIC], ["127.0.0.1"]]
    fetch, seen = fetcher(dns=dns)
    result = await fetch.fetch("https://rebind.example/page")
    assert result.status == 200
    assert dns.lookups == ["rebind.example"]  # exactly one lookup
    request = seen[0]
    assert request.url.host == PUBLIC  # connected to the checked IP
    assert request.headers["host"] == "rebind.example"
    assert request.extensions["sni_hostname"] == "rebind.example"  # TLS checked against the name
    assert str(request.url.path) == "/page"


async def test_ipv6_addresses_are_pinned_with_brackets() -> None:
    v6 = "2606:2800:220:1:248:1893:25c8:1946"
    fetch, seen = fetcher(dns=FakeDNS({"v6.example": [v6]}))
    await fetch.fetch("http://v6.example/")
    assert seen[0].url.host == v6 and seen[0].headers["host"] == "v6.example"


async def test_a_flip_to_private_on_the_redirect_hop_is_caught() -> None:
    dns = FakeDNS()
    dns.answers["start.example"] = [[PUBLIC]]
    dns.answers["next.example"] = [["10.0.0.9"]]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://next.example/"})

    fetch, seen = fetcher(handler, dns)
    with pytest.raises(PortfolioUrlRejectedError):
        await fetch.fetch("https://start.example/")
    assert len(seen) == 1  # the second hop never connected


async def test_system_resolver_failure_is_a_clean_error() -> None:
    from app.integrations.portfolio.safe_fetch import system_resolver

    with pytest.raises(PortfolioFetchError) as error:
        await system_resolver("this-host-does-not-exist.invalid", 443)
    assert error.value.code == "portfolio_unreachable"


# ------------------------------------------------------------------ redirects


async def test_redirect_to_internal_targets_is_blocked() -> None:
    targets = [
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://2130706433/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "http://printer.internal/",
        "//169.254.169.254/",
        "/\\169.254.169.254/",
    ]
    for target in targets:

        def handler(request: httpx.Request, target: str = target) -> httpx.Response:
            return httpx.Response(302, headers={"location": target})

        fetch, seen = fetcher(handler)
        with pytest.raises(PortfolioUrlRejectedError):
            await fetch.fetch("https://start.example/")
        assert len(seen) == 1, target  # only the first request was ever made


async def test_redirect_to_a_hostname_that_resolves_internally_is_blocked() -> None:
    dns = FakeDNS({"sneaky.example": ["192.168.1.10"]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "https://sneaky.example/"})

    fetch, seen = fetcher(handler, dns)
    with pytest.raises(PortfolioUrlRejectedError):
        await fetch.fetch("https://start.example/")
    assert len(seen) == 1


async def test_valid_redirects_are_followed_and_revalidated() -> None:
    dns = FakeDNS({"example.com": [PUBLIC], "www.example.com": ["93.184.216.35"]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "example.com":
            return httpx.Response(301, headers={"location": "https://www.example.com/home"})
        return httpx.Response(200, html="<p>home</p>", headers={"content-type": "text/html"})

    fetch, seen = fetcher(handler, dns)
    result = await fetch.fetch("https://example.com/")
    assert result.url == "https://www.example.com/home"
    assert dns.lookups == ["example.com", "www.example.com"]  # every hop re-resolved & checked
    assert [r.url.host for r in seen] == [PUBLIC, "93.184.216.35"]


async def test_relative_redirects_stay_on_the_validated_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return httpx.Response(200, html="ok", headers={"content-type": "text/html"})

    fetch, _seen = fetcher(handler)
    result = await fetch.fetch("https://example.com/old")
    assert result.url == "https://example.com/new"


async def test_redirect_loops_and_chains_are_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/again"})

    fetch, seen = fetcher(handler)
    with pytest.raises(PortfolioFetchError) as error:
        await fetch.fetch("https://example.com/")
    assert error.value.code == "portfolio_redirects" and len(seen) == 4


async def test_https_to_http_downgrade_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://example.com/"})

    fetch, _ = fetcher(handler)
    with pytest.raises(PortfolioUrlRejectedError, match="https to http"):
        await fetch.fetch("https://example.com/")


async def test_redirect_without_location_is_an_error() -> None:
    fetch, _ = fetcher(lambda r: httpx.Response(302))
    with pytest.raises(PortfolioFetchError):
        await fetch.fetch("https://example.com/")


# ------------------------------------------------------------------ limits & content


async def test_unsupported_content_types_are_rejected() -> None:
    for content_type in (
        "application/json",
        "application/pdf",
        "application/javascript",
        "image/png",
        "application/octet-stream",
        "",
    ):
        fetch, _ = fetcher(
            lambda r, c=content_type: httpx.Response(200, content=b"x", headers={"content-type": c})
        )
        with pytest.raises(PortfolioFetchError) as error:
            await fetch.fetch("https://example.com/")
        assert error.value.code == "portfolio_unsupported_content_type"


async def test_html_text_and_xhtml_are_accepted() -> None:
    for content_type in ("text/html; charset=utf-8", "TEXT/PLAIN", "application/xhtml+xml"):
        fetch, _ = fetcher(
            lambda r, c=content_type: httpx.Response(
                200, content=b"hello", headers={"content-type": c}
            )
        )
        assert (await fetch.fetch("https://example.com/")).body == b"hello"


async def test_oversized_responses_are_rejected_by_header_and_by_streaming() -> None:
    headers = {"content-type": "text/html"}
    declared = httpx.Response(
        200, content=b"x" * 10, headers={**headers, "content-length": "999999"}
    )
    fetch, _ = fetcher(lambda r: declared, max_bytes=1000)
    with pytest.raises(PortfolioFetchError) as error:
        await fetch.fetch("https://example.com/")
    assert error.value.code == "portfolio_too_large"

    # No honest Content-Length: the byte counter must catch it.
    streamed = httpx.Response(200, content=b"x" * 5000, headers=headers)
    streamed.headers.pop("content-length", None)
    fetch, _ = fetcher(lambda r: streamed, max_bytes=1000)
    with pytest.raises(PortfolioFetchError, match="too large"):
        await fetch.fetch("https://example.com/")


async def test_decompression_bombs_are_counted_after_decoding() -> None:
    bomb = gzip.compress(b"A" * 5_000_000)
    assert len(bomb) < 20_000  # tiny on the wire
    response = httpx.Response(
        200, content=bomb, headers={"content-type": "text/html", "content-encoding": "gzip"}
    )
    fetch, _ = fetcher(lambda r: response, max_bytes=100_000)
    with pytest.raises(PortfolioFetchError) as error:
        await fetch.fetch("https://example.com/")
    assert error.value.code == "portfolio_too_large"


async def test_timeouts_become_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fetch, _ = fetcher(handler)
    with pytest.raises(PortfolioFetchError) as error:
        await fetch.fetch("https://example.com/")
    assert error.value.code == "portfolio_timeout"


async def test_http_errors_and_connection_failures_are_clean() -> None:
    for status in (403, 404, 500, 503):
        fetch, _ = fetcher(lambda r, s=status: httpx.Response(s))
        with pytest.raises(PortfolioFetchError) as error:
            await fetch.fetch("https://example.com/")
        assert error.value.code == "portfolio_http_error"

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    fetch, seen = fetcher(refused, FakeDNS({"two.example": [PUBLIC, "93.184.216.35"]}))
    with pytest.raises(PortfolioFetchError) as unreachable:
        await fetch.fetch("https://two.example/")
    assert unreachable.value.code == "portfolio_unreachable"
    assert len(seen) == 2  # tried both validated addresses


async def test_second_validated_address_is_used_when_the_first_fails() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, html="ok", headers={"content-type": "text/html"})

    fetch, seen = fetcher(handler, FakeDNS({"two.example": [PUBLIC, "93.184.216.35"]}))
    assert (await fetch.fetch("https://two.example/")).status == 200
    assert [r.url.host for r in seen] == [PUBLIC, "93.184.216.35"]


# ------------------------------------------------------------------ hardening details


async def test_proxy_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    fetch, _ = fetcher()
    assert fetch._client.trust_env is False
    assert fetch._client.follow_redirects is False


async def test_requests_identify_themselves_and_carry_no_cookies_or_credentials() -> None:
    fetch, seen = fetcher()
    await fetch.fetch("https://example.com/")
    headers = seen[0].headers
    assert "AIJobInterviewSimulatorBot" in headers["user-agent"]
    for forbidden in ("cookie", "authorization", "referer"):
        assert forbidden not in headers
    assert seen[0].method == "GET"
