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
