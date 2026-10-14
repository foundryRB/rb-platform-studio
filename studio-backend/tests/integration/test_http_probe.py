"""HttpxProbe tests: the one cache-busted GET, with httpx faked.

The probe is the chain's last link, so its observation must be the app's
own answer (nonce past every cache), taken as the studio (User-Agent),
short-fused (5s), with redirects recorded rather than followed, and it must
answer an error instead of raising.
"""

from __future__ import annotations

import httpx
import pytest

from studio.adapters.outbound.http_probe.httpx_probe import HttpxProbe
from studio.adapters.outbound.http_probe.noop_http_probe import NoopHttpProbe


class _Response:
    def __init__(
        self,
        status_code: int,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self.text = text


def test_probe_busts_caches_and_identifies_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_get(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        follow_redirects: bool | None = None,
    ) -> _Response:
        calls.update(
            url=url, headers=headers, timeout=timeout, follow_redirects=follow_redirects
        )
        return _Response(
            200,
            {
                "Server": "caddy",
                "X-App-Version": "1.2.3",
                "Content-Type": "text/html",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = HttpxProbe().get(url="https://alpha-app.lab.example.dev/")
    url = str(calls["url"])
    assert url.startswith("https://alpha-app.lab.example.dev/?nonce=")
    assert calls["follow_redirects"] is False
    assert calls["timeout"] == 5
    headers = calls["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"].startswith("platform-studio/")
    assert "app-status-probe" in headers["User-Agent"]
    assert result.status_code == 200
    assert result.error == ""
    # Key headers survive (server, anything version-ish); noise does not.
    assert ("server", "caddy") in result.headers
    assert ("x-app-version", "1.2.3") in result.headers
    assert all(key != "content-type" for key, _ in result.headers)


def test_each_probe_uses_a_fresh_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_get(url: str, **kwargs: object) -> _Response:
        seen.append(url)
        return _Response(200)

    monkeypatch.setattr(httpx, "get", fake_get)
    probe = HttpxProbe()
    probe.get(url="https://alpha-app.lab.example.dev/")
    probe.get(url="https://alpha-app.lab.example.dev/")
    assert seen[0] != seen[1]


def test_probe_records_a_redirect_rather_than_following_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> _Response:
        return _Response(302, {"Location": "https://idp.example/auth", "Server": "edge"})

    monkeypatch.setattr(httpx, "get", fake_get)
    result = HttpxProbe().get(url="https://beta-app.lab.example.dev/")
    assert result.status_code == 302
    assert ("location", "https://idp.example/auth") in result.headers


def test_unreachable_host_answers_the_error_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> _Response:
        raise httpx.ConnectTimeout("connection timed out")

    monkeypatch.setattr(httpx, "get", fake_get)
    result = HttpxProbe().get(url="https://alpha-app.lab.example.dev/")
    assert result.status_code is None
    assert "ConnectTimeout" in result.error
    assert "connection timed out" in result.error


def test_noop_probe_answers_unreachable_with_the_reason() -> None:
    result = NoopHttpProbe().get(url="https://alpha-app.lab.example.dev/")
    assert result.status_code is None
    assert "probe disabled" in result.error
