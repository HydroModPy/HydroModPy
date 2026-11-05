"""Unit tests for the unified HTTPClient."""

from __future__ import annotations

import io
import threading
from unittest.mock import MagicMock, patch

import pytest

from hydromodpy.core.exceptions import DataSourceError, NetworkError
from hydromodpy.core.io.http_client import (
    DEFAULT_RETRY_STATUSES,
    HTTPClient,
    _parse_retry_after,
)


def _mock_response(status=200, json_data=None, content=b"", headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.json = MagicMock(return_value=json_data)
    resp.content = content
    resp.iter_content = MagicMock(return_value=iter([content]) if content else iter([]))
    resp.close = MagicMock()
    return resp


def test_get_json_returns_payload():
    client = HTTPClient(max_retries=0)
    with patch.object(client._session, "request") as req:
        req.return_value = _mock_response(200, json_data={"ok": True})
        out = client.get_json("https://x.example/api")
    assert out == {"ok": True}


def test_get_json_retries_on_503(monkeypatch):
    client = HTTPClient(max_retries=2, backoff_base=0.0, backoff_cap=0.0)
    calls = []

    def fake(*args, **kw):
        calls.append(1)
        if len(calls) < 3:
            return _mock_response(503, headers={"Retry-After": "0"})
        return _mock_response(200, json_data={"ok": 1})

    monkeypatch.setattr(client._session, "request", fake)
    out = client.get_json("https://x.example/api")
    assert out == {"ok": 1}
    assert len(calls) == 3


def test_request_raises_after_all_retries():
    client = HTTPClient(max_retries=1, backoff_base=0.0, backoff_cap=0.0)
    with patch.object(client._session, "request") as req:
        req.return_value = _mock_response(503)
        with pytest.raises(NetworkError):
            client.get_json("https://x.example/api")


def test_get_json_invalid_json_raises_datasource():
    client = HTTPClient(max_retries=0)
    resp = _mock_response(200)
    resp.json.side_effect = ValueError("bad json")
    with patch.object(client._session, "request", return_value=resp):
        with pytest.raises(DataSourceError):
            client.get_json("https://x.example/api")


def test_stream_computes_sha256(tmp_path):
    client = HTTPClient(max_retries=0)
    payload = b"hello world"
    resp = _mock_response(200, content=payload)
    resp.iter_content = MagicMock(return_value=iter([payload[:5], payload[5:]]))
    dest = tmp_path / "out.bin"
    with patch.object(client._session, "request", return_value=resp):
        result = client.stream("https://x.example/data", dest)
    assert dest.read_bytes() == payload
    assert result.size == len(payload)
    # sha256("hello world") = b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9
    assert result.sha256 == ("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")


def test_stream_accepts_buffer():
    client = HTTPClient(max_retries=0)
    buf = io.BytesIO()
    resp = _mock_response(200, content=b"abc")
    resp.iter_content = MagicMock(return_value=iter([b"abc"]))
    with patch.object(client._session, "request", return_value=resp):
        res = client.stream("https://x.example/data", buf)
    assert buf.getvalue() == b"abc"
    assert res.size == 3


def test_parse_retry_after_numeric():
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after("0") == 0.0


def test_parse_retry_after_invalid():
    assert _parse_retry_after("") is None
    assert _parse_retry_after("not a date") is None


def test_default_retry_statuses_contain_429():
    assert 429 in DEFAULT_RETRY_STATUSES
    assert 503 in DEFAULT_RETRY_STATUSES


def test_per_host_concurrency_limits():
    client = HTTPClient(per_host_concurrency=2)
    bucket = client._bucket_for("https://host.example/a")
    assert bucket is client._bucket_for("https://host.example/b")
    other = client._bucket_for("https://other.example/")
    assert other is not bucket


# ---- more situations: transport failures, hooks, errors, backoff -----------

import hashlib  # noqa: E402
from datetime import UTC, datetime, timedelta, timezone  # noqa: E402
from email.utils import format_datetime  # noqa: E402

import requests  # noqa: E402

from hydromodpy.core.io import http_client as http_module  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(http_module.time, "sleep", lambda _s: None)


def _client(**kw) -> HTTPClient:
    return HTTPClient(**{"max_retries": 2, "backoff_base": 0.0, "backoff_cap": 0.0, **kw})


def test_a_dropped_connection_is_retried_then_reported_with_its_cause(monkeypatch):
    client = _client(max_retries=1)
    calls = []

    def fake(*_a, **_k):
        calls.append(1)
        raise requests.ConnectionError("reset by peer")

    monkeypatch.setattr(client._session, "request", fake)

    with pytest.raises(NetworkError, match="failed after 1 retries"):
        client.get("https://x.example/a")

    assert len(calls) == 2


def test_a_connection_that_comes_back_gives_the_answer(monkeypatch):
    client = _client()
    answers = [requests.Timeout("slow"), _mock_response(200, json_data={"v": 1})]

    def fake(*_a, **_k):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client._session, "request", fake)

    assert client.get_json("https://x.example/a") == {"v": 1}


def test_the_hooks_see_each_attempt_and_each_outcome(monkeypatch):
    seen_before, seen_after = [], []
    client = _client(
        pre_request=lambda url, info: seen_before.append((url, info["attempt"])),
        post_response=lambda url, resp, exc: seen_after.append(
            (
                url,
                resp.status_code if resp is not None else None,
                type(exc).__name__ if exc else None,
            )
        ),
    )
    answers = [requests.ConnectionError("x"), _mock_response(503), _mock_response(200, json_data=1)]

    def fake(*_a, **_k):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client._session, "request", fake)

    client.get_json("https://x.example/a")

    assert seen_before == [("https://x.example/a", n) for n in range(3)]
    assert seen_after == [
        ("https://x.example/a", None, "ConnectionError"),
        ("https://x.example/a", 503, None),
        ("https://x.example/a", 200, None),
    ]


def test_a_failing_pre_request_hook_does_not_stop_the_request(monkeypatch):
    def hook(*_a):
        raise RuntimeError("hook bug")

    client = _client(pre_request=hook)
    monkeypatch.setattr(
        client._session, "request", lambda *_a, **_k: _mock_response(200, json_data=2)
    )

    assert client.get_json("https://x.example/a") == 2


def test_a_user_agent_is_sent_with_every_request():
    client = HTTPClient(user_agent="HydroModPy/test")

    assert client._session.headers["User-Agent"] == "HydroModPy/test"


def test_a_client_used_as_context_manager_closes_its_session(monkeypatch):
    closed = []
    with HTTPClient() as client:
        monkeypatch.setattr(client._session, "close", lambda: closed.append(1))

    assert closed == [1]


def test_a_client_error_status_is_a_network_error_carrying_the_status(monkeypatch):
    client = _client()
    monkeypatch.setattr(client._session, "request", lambda *_a, **_k: _mock_response(404))

    with pytest.raises(NetworkError, match="404") as caught:
        client.get_json("https://x.example/missing")

    assert "x.example/missing" in str(caught.value)


class _Schema:
    def __init__(self, payload):
        if "id" not in payload:
            raise KeyError("id")
        self.id = payload["id"]


class _PydanticLike:
    @classmethod
    def model_validate(cls, payload):
        return ("validated", payload)


def test_a_payload_is_handed_to_the_model_that_validates_it(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client._session, "request", lambda *_a, **_k: _mock_response(200, json_data={"id": 7})
    )

    assert client.get_json("https://x.example/a", model=_Schema).id == 7
    assert client.get_json("https://x.example/a", model=_PydanticLike) == ("validated", {"id": 7})


def test_a_payload_the_model_refuses_is_a_data_source_error(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client._session, "request", lambda *_a, **_k: _mock_response(200, json_data={})
    )

    with pytest.raises(DataSourceError, match="failed validation"):
        client.get_json("https://x.example/a", model=_Schema)


def test_a_stream_error_status_is_refused_before_anything_is_written(monkeypatch, tmp_path):
    client = _client()
    monkeypatch.setattr(client._session, "request", lambda *_a, **_k: _mock_response(400))
    target = tmp_path / "out.bin"

    with pytest.raises(NetworkError, match="400"):
        client.stream("https://x.example/f", target)

    assert not target.exists()


def test_iter_bytes_yields_the_chunks_in_order_and_skips_empty_ones(monkeypatch):
    client = _client()
    resp = _mock_response(200)
    resp.iter_content = MagicMock(return_value=iter([b"ab", b"", b"cd"]))
    monkeypatch.setattr(client._session, "request", lambda *_a, **_k: resp)

    assert b"".join(client.iter_bytes("https://x.example/f")) == b"abcd"
    resp.close.assert_called()


def test_iter_bytes_refuses_an_error_status(monkeypatch):
    client = _client()
    monkeypatch.setattr(client._session, "request", lambda *_a, **_k: _mock_response(403))

    with pytest.raises(NetworkError, match="403"):
        list(client.iter_bytes("https://x.example/f"))


def test_stream_digest_matches_the_bytes_written(monkeypatch, tmp_path):
    client = _client()
    resp = _mock_response(200, content=b"hydro")
    monkeypatch.setattr(client._session, "request", lambda *_a, **_k: resp)

    result = client.stream("https://x.example/f", tmp_path / "f.bin")

    assert (tmp_path / "f.bin").read_bytes() == b"hydro"
    assert result.sha256 == hashlib.sha256(b"hydro").hexdigest()
    assert result.size == 5


def test_a_retry_after_header_sets_the_wait_but_never_above_the_cap():
    client = HTTPClient(backoff_cap=10.0)

    assert client._compute_backoff(0, "3") == 3.0
    assert client._compute_backoff(0, "3600") == 10.0


def test_without_a_usable_retry_after_the_wait_doubles_with_the_attempt_up_to_the_cap():
    client = HTTPClient(backoff_base=1.0, backoff_cap=8.0)

    waits = [client._compute_backoff(n, "garbage") for n in range(5)]

    for attempt, wait in enumerate(waits):
        base = min(8.0, 2.0**attempt)
        assert base <= wait <= base * 1.25


@pytest.mark.parametrize("value", ["", "   ", "not a date", "-5"])
def test_an_unreadable_retry_after_is_ignored(value):
    assert _parse_retry_after(value) is None


def test_a_retry_after_given_as_a_date_is_the_time_left_until_then():
    in_a_minute = datetime.now(UTC) + timedelta(seconds=60)
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)

    assert 50 < _parse_retry_after(format_datetime(in_a_minute, usegmt=True)) <= 60
    assert _parse_retry_after(format_datetime(long_ago, usegmt=True)) == 0.0


def test_the_default_client_is_one_shared_instance(monkeypatch):
    monkeypatch.setattr(http_module, "_DEFAULT_CLIENT", None)

    first = http_module.get_default_client()

    assert http_module.get_default_client() is first
