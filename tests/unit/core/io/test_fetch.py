"""Unit tests for hydromodpy.core.io.fetch."""

from __future__ import annotations

import hashlib
import io
import threading
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from hydromodpy.core.exceptions import (
    BoundsError,
    CacheCorruptionError,
    DataSourceError,
    NetworkError,
)
from hydromodpy.core.io.fetch import (
    DEFAULT_RETRY_STATUSES,
    Fetched,
    HTTPClient,
    ResolvedUrl,
    _parse_retry_after,
    download,
    fetch_pinned,
    guard_host,
    guard_url,
    open_client,
    resolve_final_url,
    vsicurl_path,
)
from hydromodpy.core.runtime.bounds import Bounds
from tests.unit.core.io._fake_release import digest_of, serve_assets

PAYLOAD = b"the bytes of the release"
REMEDY = "Report it."
ADDRESS = "https://releases.example/asset"


def _fake_client(*answers: object) -> MagicMock:
    """A client stand-in that hands the given responses out in order."""
    fake = MagicMock(spec=HTTPClient)
    queue = list(answers)
    fake.request.side_effect = lambda *a, **k: queue.pop(0)
    return fake


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every name resolves to one public address; a test that needs a private
    one patches ``socket.getaddrinfo`` again inside its own body."""
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )


def _mock_response(
    status: int = 200, json_data: Any = None, content: bytes = b"", headers: dict | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.json = MagicMock(return_value=json_data)
    resp.content = content
    resp.iter_content = MagicMock(return_value=iter([content]) if content else iter([]))
    resp.close = MagicMock()
    return resp


def _answering(monkeypatch: pytest.MonkeyPatch, client: HTTPClient, *answers: Any) -> list[int]:
    queue, calls = list(answers), []

    def fake(*_a: Any, **_k: Any) -> Any:
        calls.append(1)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client._session, "request", fake)
    return calls


# ---------------------------------------------------------------------------
# guard_url tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file.tif",
        "file:///tmp/dem.tif",
        "javascript:alert(1)",
    ],
)
def test_guard_url_refuses_non_http_schemes(url: str) -> None:
    with pytest.raises(BoundsError, match="scheme"):
        guard_url(url, resolve_dns=False)


def test_guard_url_refuses_http_without_pinned_sha() -> None:
    with pytest.raises(BoundsError, match="http without a pinned sha256"):
        guard_url("http://example.com/data.tif", pinned=False, resolve_dns=False)


def test_guard_url_accepts_http_with_pinned_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 80))])
    guard_url("http://example.com/data.tif", pinned=True, resolve_dns=True)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.com/data.tif",
        "https://admin@example.com/data.tif",
    ],
)
def test_guard_url_refuses_credentials(url: str) -> None:
    with pytest.raises(BoundsError, match="credentials"):
        guard_url(url, resolve_dns=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/data.tif?X-Amz-Signature=123",
        "https://example.com/data.tif?signature=abc",
        "https://example.com/data.tif?Token=secret",
        "https://example.com/data.tif?SIG=xyz",
    ],
)
def test_guard_url_refuses_signature_query_parameters(url: str) -> None:
    with pytest.raises(BoundsError, match="signature"):
        guard_url(url, resolve_dns=False)


@pytest.mark.parametrize(
    "ip_str",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "::1",
        "fc00::1",
        "100.64.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_guard_url_refuses_non_global_ips_by_default(
    ip_str: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", (ip_str, 443))])
    with pytest.raises(BoundsError, match="non-public IP address"):
        guard_url("https://intranet.example.com/dem.tif", resolve_dns=True)


def test_guard_url_refuses_hosts_not_in_allowed_hosts() -> None:
    bounds = Bounds(allowed_hosts=frozenset({"example.com"}))
    with pytest.raises(BoundsError, match="not among the hosts"):
        guard_url("https://other.com/dem.tif", bounds=bounds, resolve_dns=False)


def test_guard_url_permits_non_global_ip_when_host_explicitly_in_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = Bounds(allowed_hosts=frozenset({"127.0.0.1"}))
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("127.0.0.1", 443))])
    # Explicitly allowed host can resolve to loopback/private IP
    guard_url("https://127.0.0.1/data.tif", bounds=bounds, resolve_dns=True)


# ---------------------------------------------------------------------------
# guard_host tests
# ---------------------------------------------------------------------------


def test_guard_host_accepts_a_public_host() -> None:
    guard_host("example.com", Bounds(), what="delivery to example.com")


def test_guard_host_refuses_an_unnamed_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("10.0.0.1", 0))])
    with pytest.raises(BoundsError, match="non-public IP address"):
        guard_host("intranet.example.com", Bounds(), what="delivery to intranet.example.com")


def test_guard_host_accepts_a_named_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("127.0.0.1", 0))])
    guard_host(
        "127.0.0.1",
        Bounds(allowed_hosts=frozenset({"127.0.0.1"})),
        what="delivery to 127.0.0.1",
    )


def test_guard_host_refuses_a_host_outside_the_allowed_list() -> None:
    bounds = Bounds(allowed_hosts=frozenset({"example.com"}))
    with pytest.raises(BoundsError, match="not among the hosts"):
        guard_host("other.com", bounds, what="delivery to other.com")


def test_guard_host_refuses_an_empty_host() -> None:
    with pytest.raises(BoundsError, match="names no host"):
        guard_host("", Bounds(), what="delivery to nowhere")


def test_guard_host_skips_resolution_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("guard_host resolved a host it was told not to resolve")

    monkeypatch.setattr("socket.getaddrinfo", refuse)
    guard_host("example.com", Bounds(), what="fetch guard", resolve_dns=False)


# ---------------------------------------------------------------------------
# resolve_final_url and vsicurl_path tests
# ---------------------------------------------------------------------------


def test_resolve_final_url_follows_redirects_manually(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )

    r1 = _mock_response(302, headers={"Location": "https://example.com/step2"})
    r2 = _mock_response(
        200,
        headers={
            "ETag": '"abc"',
            "Last-Modified": "Wed, 21 Oct 2025 07:28:00 GMT",
            "Content-Length": "1024",
        },
    )

    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1, r2)

    resolved = resolve_final_url("https://example.com/start", client=client)
    assert resolved.url == "https://example.com/step2"
    assert resolved.etag == '"abc"'
    assert resolved.last_modified == "Wed, 21 Oct 2025 07:28:00 GMT"
    assert resolved.content_length == 1024


def test_resolve_final_url_refuses_private_ip_at_intermediate_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r1 = _mock_response(302, headers={"Location": "https://intranet.local/data.tif"})

    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1)

    def fake_getaddrinfo(host: str, _port: Any) -> list:
        if host == "example.com":
            return [(2, 1, 6, "", ("93.184.216.34", 443))]
        return [(2, 1, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(BoundsError, match="non-public IP address"):
        resolve_final_url("https://example.com/start", client=client)


def test_resolve_final_url_follows_a_signed_release_target_at_the_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release target the server chose (GitHub, S3) keeps its query string."""
    r1 = _mock_response(
        302,
        headers={"Location": "https://release-assets.example/23.0/linux.zip"},
    )
    signed = _mock_response(
        302,
        headers={"Location": "https://elsewhere.example/23.0?sp=r&sig=beef&jwt=cafe"},
    )
    r2 = _mock_response(200, headers={"Content-Length": "2048"})

    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1, signed, r2)

    resolved = resolve_final_url(
        "https://github.com/MODFLOW-ORG/executables/releases/download/23.0/linux.zip",
        client=client,
    )
    assert "sig=beef" in resolved.url
    assert resolved.content_length == 2048


def test_resolve_final_url_refuses_too_many_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    redirect = _mock_response(302, headers={"Location": "https://example.com/loop"})
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, redirect)

    with pytest.raises(NetworkError, match="exceeded 5 hops"):
        resolve_final_url("https://example.com/loop", client=client)


def test_vsicurl_path_returns_final_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    resp = _mock_response(200)
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, resp)

    out = vsicurl_path("https://example.com/raster.tif", client=client)
    assert out == "/vsicurl/https://example.com/raster.tif"


# ---------------------------------------------------------------------------
# HTTPClient redirect tests
# ---------------------------------------------------------------------------


def test_a_request_follows_a_signed_release_target_one_hop_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GitHub release hop carries a signed query string the server chose."""
    r1 = _mock_response(
        302, headers={"Location": "https://release-assets.example/23.0/linux.zip?sp=r&sig=beef"}
    )
    r2 = _mock_response(200, headers={"Content-Length": "2048"})
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1, r2)

    resp = client.get("https://github.com/MODFLOW-ORG/executables/releases/download/23.0/linux.zip")

    assert resp.status_code == 200
    assert resp.headers["Content-Length"] == "2048"


def test_a_request_hop_outside_the_allowed_hosts_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = Bounds(allowed_hosts=frozenset({"example.com"}))
    r1 = _mock_response(302, headers={"Location": "https://other.com/asset"})
    client = HTTPClient(bounds=bounds, max_retries=0)
    _answering(monkeypatch, client, r1)

    with pytest.raises(BoundsError, match="are not among the hosts this call allows"):
        client.get("https://example.com/start")


def test_a_request_hop_to_a_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r1 = _mock_response(302, headers={"Location": "https://intranet.local/asset"})
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1)
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("10.0.0.1", 443))])

    with pytest.raises(BoundsError, match="non-public IP address"):
        client.get("https://example.com/start")


# ---------------------------------------------------------------------------
# download and fetch_pinned tests
# ---------------------------------------------------------------------------


def test_download_exceeding_max_bytes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    client = HTTPClient(max_retries=0)

    # 2048 bytes of data
    large_payload = b"x" * 2048
    head_resp = _mock_response(200)
    get_resp = _mock_response(200, content=large_payload)
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "dem.tif"
    bounds = Bounds(max_download_bytes=1024)

    with pytest.raises(BoundsError, match="exceeded the byte ceiling"):
        download("https://example.com/dem.tif", dest, bounds=bounds, client=client)

    assert not dest.exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_download_reads_the_ceiling_of_the_client_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    client = HTTPClient(bounds=Bounds(max_download_bytes=4), max_retries=0)

    head_resp = _mock_response(200)
    get_resp = _mock_response(200, content=b"12345678")
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "asset.bin"

    with pytest.raises(BoundsError, match="exceeded the byte ceiling"):
        download("https://example.com/asset.bin", dest, client=client)

    assert not dest.exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_download_refuses_a_get_that_answers_a_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server whose GET answers 3xx hands no file, whatever its HEAD said."""
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    client = HTTPClient(max_retries=0)

    head_resp = _mock_response(200, headers={"Content-Length": "2048"})
    get_resp = _mock_response(302, headers={"Location": "https://example.com/asset"})
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "asset.zip"

    with pytest.raises(NetworkError, match="302"):
        download("https://example.com/asset.zip", dest, client=client)

    assert not dest.exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_download_corrupted_digest_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    client = HTTPClient(max_retries=0)

    head_resp = _mock_response(200)
    get_resp = _mock_response(200, content=b"content")
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "dem.tif"
    with pytest.raises(CacheCorruptionError, match="pins sha256"):
        download("https://example.com/dem.tif", dest, sha256="0" * 64, client=client)

    assert not dest.exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_download_successful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    client = HTTPClient(max_retries=0)

    payload = b"verified bytes"
    expected_sha = hashlib.sha256(payload).hexdigest()
    head_resp = _mock_response(200, headers={"ETag": '"etag1"'})
    get_resp = _mock_response(200, content=payload, headers={"ETag": '"etag1"'})
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "dem.tif"
    res = download("https://example.com/dem.tif", dest, sha256=expected_sha, client=client)

    assert res.path == dest
    assert res.sha256 == expected_sha
    assert res.size == len(payload)
    assert res.etag == '"etag1"'
    assert dest.read_bytes() == payload
    assert not list(tmp_path.glob("**/*.part"))


def test_fetch_pinned_serves_from_cache(tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(PAYLOAD)
    assert (
        fetch_pinned(
            "https://releases.example/asset", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY
        )
        == dest
    )


def test_fetch_pinned_corruption_removes_old(tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(b"corrupt")
    with pytest.raises(CacheCorruptionError) as exc:
        fetch_pinned(
            "https://releases.example/asset", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY
        )
    assert REMEDY in str(exc.value)
    assert not dest.exists()


# ---------------------------------------------------------------------------
# HTTPClient tests (retained from test_http_client.py)
# ---------------------------------------------------------------------------


def test_get_json_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    with patch.object(client._session, "request") as req:
        req.return_value = _mock_response(200, json_data={"ok": True})
        out = client.get_json("https://x.example/api")
    assert out == {"ok": True}


def test_get_json_retries_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=2, backoff_base=0.0, backoff_cap=0.0)
    unavailable = _mock_response(503, headers={"Retry-After": "0"})
    success = _mock_response(200, json_data={"ok": True})
    calls = _answering(monkeypatch, client, unavailable, success)
    assert client.get_json("https://x.example/api") == {"ok": True}
    assert len(calls) == 2


def test_get_json_honors_retry_after_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=1, backoff_cap=0.1)
    unavailable = _mock_response(503, headers={"Retry-After": "0.05"})
    success = _mock_response(200, json_data={"ok": True})
    calls = _answering(monkeypatch, client, unavailable, success)
    assert client.get_json("https://x.example/api") == {"ok": True}
    assert len(calls) == 2


def test_get_json_honors_retry_after_http_date(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=1, backoff_cap=0.1)
    future = datetime.now(UTC) + timedelta(seconds=0.05)
    unavailable = _mock_response(503, headers={"Retry-After": format_datetime(future)})
    success = _mock_response(200, json_data={"ok": True})
    calls = _answering(monkeypatch, client, unavailable, success)
    assert client.get_json("https://x.example/api") == {"ok": True}
    assert len(calls) == 2


def test_get_json_raises_network_error_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=2, backoff_base=0.0, backoff_cap=0.0)
    unavailable = _mock_response(503)
    calls = _answering(monkeypatch, client, unavailable)
    with pytest.raises(NetworkError) as caught:
        client.get_json("https://x.example/api")
    assert len(calls) == 3
    assert caught.value.context.get("status_code") == 503 or "503" in str(caught.value)


def test_get_json_raises_data_source_error_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    resp = _mock_response(200)
    resp.json.side_effect = ValueError("invalid json")
    _answering(monkeypatch, client, resp)
    with pytest.raises(DataSourceError):
        client.get_json("https://x.example/api")


def test_stream_hashes_content_and_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = HTTPClient(max_retries=0)
    payload = b"abc" * 1024
    expected = hashlib.sha256(payload).hexdigest()
    _answering(
        monkeypatch,
        client,
        _mock_response(200, content=payload, headers={"Content-Type": "text/plain"}),
    )
    dest = tmp_path / "out.bin"
    res = client.stream("https://x.example/blob", dest)
    assert res.sha256 == expected
    assert res.size == len(payload)
    assert dest.read_bytes() == payload


def test_iter_bytes_yields_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(200, content=b"chunk1chunk2"))
    chunks = list(client.iter_bytes("https://x.example/blob"))
    assert b"".join(chunks) == b"chunk1chunk2"


def test_parse_retry_after() -> None:
    assert _parse_retry_after("") is None
    assert _parse_retry_after("invalid") is None
    assert _parse_retry_after("5") == 5.0
    future = datetime.now(UTC) + timedelta(seconds=10)
    parsed = _parse_retry_after(format_datetime(future))
    assert parsed is not None
    assert 8.0 <= parsed <= 12.0


def test_per_host_concurrency_limits() -> None:
    client = HTTPClient()
    url_a, url_b = "https://a.example/f", "https://b.example/f"
    bucket_a = client._bucket_for(url_a)
    assert bucket_a is client._bucket_for(url_a + "?x=1")
    assert client._bucket_for(url_b) is not bucket_a


def test_a_dropped_connection_is_retried_then_reported_with_its_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HTTPClient(max_retries=1, backoff_base=0.0, backoff_cap=0.0)
    calls = _answering(monkeypatch, client, requests.ConnectionError("reset by peer"))
    with pytest.raises(NetworkError, match="after 2 attempts") as caught:
        client.get_json("https://x.example/api")
    assert len(calls) == 2
    assert "reset by peer" in str(caught.value)


def test_a_connection_that_comes_back_gives_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=2, backoff_base=0.0, backoff_cap=0.0)
    _answering(
        monkeypatch, client, requests.Timeout("slow"), _mock_response(200, json_data={"v": 1})
    )
    assert client.get_json("https://x.example/api") == {"v": 1}


def test_a_user_agent_is_set_on_the_session() -> None:
    client = HTTPClient(user_agent="HydroModPy/test")
    assert client._session.headers["User-Agent"] == "HydroModPy/test"


def test_the_session_does_not_read_the_environment() -> None:
    # Proxies, netrc credentials and CA overrides never reach the client.
    with HTTPClient() as client:
        assert client._session.trust_env is False


def test_a_client_used_as_context_manager_closes_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []
    with HTTPClient() as client:
        monkeypatch.setattr(client._session, "close", lambda: closed.append(1))
    assert closed == [1]


def test_a_client_error_status_carries_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(404))
    with pytest.raises(NetworkError) as caught:
        client.get_json("https://x.example/api")
    assert caught.value.context.get("status_code") == 404


class _Schema:
    def __init__(self, payload: dict[str, Any]) -> None:
        if "id" not in payload:
            raise KeyError("id")
        self.id = payload["id"]


def test_a_payload_is_handed_to_the_model_that_validates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(200, json_data={"id": 7}))
    assert client.get_json("https://x.example/a", model=_Schema).id == 7


def test_a_payload_the_model_refuses_is_a_data_source_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(200, json_data={}))
    with pytest.raises(DataSourceError, match="failed validation"):
        client.get_json("https://x.example/a", model=_Schema)


def test_a_stream_error_status_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(400))
    target = tmp_path / "out.bin"
    with pytest.raises(NetworkError, match="400"):
        client.stream("https://x.example/f", target)
    assert not target.exists()


def test_iter_bytes_refuses_an_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(403))
    with pytest.raises(NetworkError, match="403"):
        list(client.iter_bytes("https://x.example/f"))


def test_the_backoff_never_grows_past_its_cap() -> None:
    client = HTTPClient(backoff_base=1.0, backoff_cap=8.0)
    waits = [client._compute_backoff(attempt, None) for attempt in range(6)]
    # The cap holds the flat part of the wait; the jitter may add a quarter.
    assert waits[-1] <= 10.0
    assert waits[3] > waits[0]


def test_stream_accepts_a_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    payload = b"abc"
    _answering(monkeypatch, client, _mock_response(200, content=payload))
    buffer = io.BytesIO()
    res = client.stream("https://x.example/f", buffer)
    assert buffer.getvalue() == payload
    assert res.size == 3


def test_force_keeps_the_old_file_until_the_new_bytes_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With force the old file stays until the new bytes hash to the pin."""
    dest = tmp_path / "asset"
    dest.write_bytes(b"the old release")
    serve_assets(monkeypatch, {"asset": b"what the old release held"})

    with pytest.raises(CacheCorruptionError):
        fetch_pinned(ADDRESS, dest, sha256=digest_of(PAYLOAD), remedy=REMEDY, force=True)
    assert dest.read_bytes() == b"the old release"

    serve_assets(monkeypatch, {"asset": PAYLOAD})
    assert fetch_pinned(ADDRESS, dest, sha256=digest_of(PAYLOAD), remedy=REMEDY, force=True)
    assert dest.read_bytes() == PAYLOAD


def test_a_connection_lost_in_the_body_is_a_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A body that breaks mid-read is a NetworkError naming its cause.

    The streamed GET of the same shape alongside it: nothing is left behind.
    """
    broken = _mock_response(200, content=b"half of it")
    broken.iter_content = MagicMock(
        side_effect=requests.exceptions.ChunkedEncodingError("Connection broken")
    )
    fake = _fake_client(_mock_response(200), broken)

    with pytest.raises(NetworkError, match="Connection lost") as caught:
        download("https://releases.example/asset", tmp_path / "asset", client=fake)

    assert "Connection broken" in str(caught.value)
    assert not (tmp_path / "asset").exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_the_default_retry_statuses_hold_the_retryable_codes() -> None:
    assert 429 in DEFAULT_RETRY_STATUSES
    assert 503 in DEFAULT_RETRY_STATUSES
