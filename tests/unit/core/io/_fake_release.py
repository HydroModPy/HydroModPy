"""Serve release assets from memory, so a download test reaches no network."""

from __future__ import annotations

import hashlib
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

_HEAD = "HEAD"
_GET = "GET"


class _FakeResponse:
    """The parts of a response that download() and resolve_final_url() read."""

    status_code = 200

    def __init__(self, payload: bytes) -> None:
        self.headers = {"ETag": hashlib.sha256(payload).hexdigest()}
        self._payload = payload

    def iter_content(self, chunk_size: int | None = None) -> Iterator[bytes]:
        yield self._payload

    def close(self) -> None:
        return None


def serve_assets(monkeypatch: pytest.MonkeyPatch, assets: dict[str, bytes]) -> list[str]:
    """Answer each pinned download from *assets*, addressed by the last URL part.

    The fake hangs on the one seam every download passes through, the client
    that :func:`hydromodpy.io.fetch.open_client` opens for its call. It
    records every GET address asked and returns the addresses, in order.
    """
    asked: list[str] = []

    class FakeClient:
        def request(self, method: str, url: str, **kw: Any) -> _FakeResponse:
            if method == _GET:
                asked.append(url)
            return _FakeResponse(assets[url.rsplit("/", 1)[-1]])

        def close(self) -> None:
            return None

    @contextmanager
    def fake_open_client(bounds: Any = None, **kw: Any) -> Iterator[FakeClient]:
        yield FakeClient()

    monkeypatch.setattr("hydromodpy.core.io.fetch.open_client", fake_open_client)
    # The stub serves from memory, so the host guard must not resolve DNS.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    return asked


def digest_of(payload: bytes) -> str:
    """Return the sha256 digest that pins this payload."""
    return hashlib.sha256(payload).hexdigest()
