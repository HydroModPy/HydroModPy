"""Serve release assets from memory, so a download test needs no network."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def serve_assets(monkeypatch: pytest.MonkeyPatch, assets: dict[str, bytes]) -> list[str]:
    """Answer each download by the last part of its address; return the addresses asked."""
    asked: list[str] = []

    class Client:
        def stream(self, url: str, dest: Path) -> SimpleNamespace:
            asked.append(url)
            payload = assets[url.rsplit("/", 1)[-1]]
            Path(dest).write_bytes(payload)
            return SimpleNamespace(sha256=hashlib.sha256(payload).hexdigest())

    monkeypatch.setattr("hydromodpy.core.io.pinned_download.get_default_client", Client)
    return asked


def digest_of(payload: bytes) -> str:
    """Return the sha256 a pin writes for *payload*."""
    return hashlib.sha256(payload).hexdigest()
