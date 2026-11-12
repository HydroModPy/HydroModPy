"""Pinned, bounded downloads: URL and host guards, redirects hop by hop, retries, byte ceiling."""

from __future__ import annotations

import hashlib
import io
import threading
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
    HTTPClient,
    _parse_retry_after,
    download,
    fetch_pinned,
    guard_host,
    guard_url,
    resolve_final_url,
)
from hydromodpy.core.runtime.bounds import Bounds
from tests.unit.core.io._fake_release import digest_of

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


GUARD_REFUSALS = [
    pytest.param("ftp://example.com/file.tif", "scheme", id="ftp"),
    pytest.param("file:///tmp/dem.tif", "scheme", id="file"),
    pytest.param("javascript:alert(1)", "scheme", id="javascript"),
    pytest.param("https://user:pass@example.com/data.tif", "credentials", id="user and password"),
    pytest.param("https://admin@example.com/data.tif", "credentials", id="user only"),
    pytest.param("https://example.com/data.tif?X-Amz-Signature=123", "signature", id="amz"),
    pytest.param("https://example.com/data.tif?signature=abc", "signature", id="signature"),
    pytest.param("https://example.com/data.tif?Token=secret", "signature", id="token"),
    pytest.param("https://example.com/data.tif?SIG=xyz", "signature", id="sig"),
]


@pytest.mark.parametrize(("url", "message"), GUARD_REFUSALS)
def test_guard_url_refusals(url: str, message: str) -> None:
    with pytest.raises(BoundsError, match=message):
        guard_url(url, resolve_dns=False)


def test_guard_url_http_needs_sha() -> None:
    with pytest.raises(BoundsError, match="http without a pinned sha256"):
        guard_url("http://example.com/data.tif", pinned=False, resolve_dns=False)


def test_guard_host_empty() -> None:
    with pytest.raises(BoundsError, match="names no host"):
        guard_host("", Bounds(), what="delivery to nowhere")


def test_resolve_refuses_private_hop(
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


def test_resolve_keeps_signed_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A release target the server chose (GitHub, S3) keeps its query string.
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


def test_resolve_refuses_redirect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    redirect = _mock_response(302, headers={"Location": "https://example.com/loop"})
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, redirect)

    with pytest.raises(NetworkError, match="exceeded 5 hops"):
        resolve_final_url("https://example.com/loop", client=client)


def test_get_follows_signed_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r1 = _mock_response(
        302, headers={"Location": "https://release-assets.example/23.0/linux.zip?sp=r&sig=beef"}
    )
    r2 = _mock_response(200, headers={"Content-Length": "2048"})
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1, r2)

    resp = client.get("https://github.com/MODFLOW-ORG/executables/releases/download/23.0/linux.zip")

    assert resp.status_code == 200
    assert resp.headers["Content-Length"] == "2048"


def test_hop_outside_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = Bounds(allowed_hosts=frozenset({"example.com"}))
    r1 = _mock_response(302, headers={"Location": "https://other.com/asset"})
    client = HTTPClient(bounds=bounds, max_retries=0)
    _answering(monkeypatch, client, r1)

    with pytest.raises(BoundsError, match="are not among the hosts this call allows"):
        client.get("https://example.com/start")


def test_hop_to_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r1 = _mock_response(302, headers={"Location": "https://intranet.local/asset"})
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, r1)
    monkeypatch.setattr("socket.getaddrinfo", lambda _h, _p: [(2, 1, 6, "", ("10.0.0.1", 443))])

    with pytest.raises(BoundsError, match="non-public IP address"):
        client.get("https://example.com/start")


def test_download_over_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_download_uses_client_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(bounds=Bounds(max_download_bytes=4), max_retries=0)

    head_resp = _mock_response(200)
    get_resp = _mock_response(200, content=b"12345678")
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "asset.bin"

    with pytest.raises(BoundsError, match="exceeded the byte ceiling"):
        download("https://example.com/asset.bin", dest, client=client)

    assert not dest.exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_download_refuses_redirect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A server whose GET answers 3xx hands no file, whatever its HEAD said.
    client = HTTPClient(max_retries=0)

    head_resp = _mock_response(200, headers={"Content-Length": "2048"})
    get_resp = _mock_response(302, headers={"Location": "https://example.com/asset"})
    _answering(monkeypatch, client, head_resp, get_resp)

    dest = tmp_path / "cache" / "asset.zip"

    with pytest.raises(NetworkError, match="302"):
        download("https://example.com/asset.zip", dest, client=client)

    assert not dest.exists()
    assert not list(tmp_path.glob("**/*.part"))


def test_fetch_pinned_from_cache(tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(PAYLOAD)
    assert (
        fetch_pinned(
            "https://releases.example/asset", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY
        )
        == dest
    )


def test_fetch_pinned_corruption(tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(b"corrupt")
    with pytest.raises(CacheCorruptionError) as exc:
        fetch_pinned(
            "https://releases.example/asset", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY
        )
    assert REMEDY in str(exc.value)
    assert not dest.exists()


def test_get_json_retries_503(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=2, backoff_base=0.0, backoff_cap=0.0)
    unavailable = _mock_response(503, headers={"Retry-After": "0"})
    success = _mock_response(200, json_data={"ok": True})
    calls = _answering(monkeypatch, client, unavailable, success)
    assert client.get_json("https://x.example/api") == {"ok": True}
    assert len(calls) == 2


def test_get_json_retry_after_date(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=1, backoff_cap=0.1)
    future = datetime.now(UTC) + timedelta(seconds=0.05)
    unavailable = _mock_response(503, headers={"Retry-After": format_datetime(future)})
    success = _mock_response(200, json_data={"ok": True})
    calls = _answering(monkeypatch, client, unavailable, success)
    assert client.get_json("https://x.example/api") == {"ok": True}
    assert len(calls) == 2


def test_get_json_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    resp = _mock_response(200)
    resp.json.side_effect = ValueError("invalid json")
    _answering(monkeypatch, client, resp)
    with pytest.raises(DataSourceError):
        client.get_json("https://x.example/api")


def test_stream_hashes_and_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_iter_bytes_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_dropped_connection_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HTTPClient(max_retries=1, backoff_base=0.0, backoff_cap=0.0)
    calls = _answering(monkeypatch, client, requests.ConnectionError("reset by peer"))
    with pytest.raises(NetworkError, match="after 2 attempts") as caught:
        client.get_json("https://x.example/api")
    assert len(calls) == 2
    assert "reset by peer" in str(caught.value)


def test_connection_comes_back(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=2, backoff_base=0.0, backoff_cap=0.0)
    _answering(
        monkeypatch, client, requests.Timeout("slow"), _mock_response(200, json_data={"v": 1})
    )
    assert client.get_json("https://x.example/api") == {"v": 1}


def test_user_agent_on_session() -> None:
    client = HTTPClient(user_agent="HydroModPy/test")
    assert client._session.headers["User-Agent"] == "HydroModPy/test"


def test_session_ignores_environment() -> None:
    # Proxies, netrc credentials and CA overrides never reach the client.
    with HTTPClient() as client:
        assert client._session.trust_env is False


def test_context_manager_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []
    with HTTPClient() as client:
        monkeypatch.setattr(client._session, "close", lambda: closed.append(1))
    assert closed == [1]


class _Schema:
    def __init__(self, payload: dict[str, Any]) -> None:
        if "id" not in payload:
            raise KeyError("id")
        self.id = payload["id"]


def test_payload_goes_to_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(200, json_data={"id": 7}))
    assert client.get_json("https://x.example/a", model=_Schema).id == 7


def test_model_refusal_is_source_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(200, json_data={}))
    with pytest.raises(DataSourceError, match="failed validation"):
        client.get_json("https://x.example/a", model=_Schema)


def test_stream_error_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(400))
    target = tmp_path / "out.bin"
    with pytest.raises(NetworkError, match="400"):
        client.stream("https://x.example/f", target)
    assert not target.exists()


def test_iter_bytes_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    _answering(monkeypatch, client, _mock_response(403))
    with pytest.raises(NetworkError, match="403"):
        list(client.iter_bytes("https://x.example/f"))


def test_stream_to_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HTTPClient(max_retries=0)
    payload = b"abc"
    _answering(monkeypatch, client, _mock_response(200, content=payload))
    buffer = io.BytesIO()
    res = client.stream("https://x.example/f", buffer)
    assert buffer.getvalue() == payload
    assert res.size == 3


def test_connection_lost_in_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_default_retry_statuses() -> None:
    assert 429 in DEFAULT_RETRY_STATUSES
    assert 503 in DEFAULT_RETRY_STATUSES
