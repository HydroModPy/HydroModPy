"""Unit tests for HMAC-signed pickle helpers."""

from __future__ import annotations

import pickle
import secrets
from pathlib import Path

import pytest

from hydromodpy.core.io.signed_pickle import (
    SignatureError,
    dumps_signed,
    load_or_create_key,
    loads_signed,
)


def test_round_trip_preserves_object() -> None:
    key = secrets.token_bytes(32)
    obj = {"a": 1, "b": [2, 3], "c": ("x", None)}
    blob = dumps_signed(obj, key)
    assert loads_signed(blob, key) == obj


def test_loads_signed_rejects_wrong_key() -> None:
    blob = dumps_signed({"x": 1}, secrets.token_bytes(32))
    with pytest.raises(SignatureError):
        loads_signed(blob, secrets.token_bytes(32))


def test_loads_signed_rejects_tampered_blob() -> None:
    key = secrets.token_bytes(32)
    blob = bytearray(dumps_signed({"x": 1}, key))
    blob[-1] ^= 0xFF
    with pytest.raises(SignatureError):
        loads_signed(bytes(blob), key)


def test_loads_signed_rejects_short_blob() -> None:
    with pytest.raises(SignatureError):
        loads_signed(b"\x00" * 4, secrets.token_bytes(32))


def test_loads_signed_rejects_unsigned_pickle() -> None:
    """A raw pickle blob (no HMAC prefix) must fail verification."""
    key = secrets.token_bytes(32)
    raw = pickle.dumps({"x": 1})
    with pytest.raises(SignatureError):
        loads_signed(raw, key)


def test_dumps_signed_rejects_short_key() -> None:
    with pytest.raises(ValueError):
        dumps_signed({"x": 1}, b"too-short")


def test_load_or_create_key_creates_then_reuses(tmp_path: Path) -> None:
    key_path = tmp_path / ".hmp" / "checkpoints" / ".signing_key"
    first = load_or_create_key(key_path)
    assert key_path.exists()
    assert len(first) == 32
    second = load_or_create_key(key_path)
    assert first == second


def test_load_or_create_key_rejects_truncated_file(tmp_path: Path) -> None:
    key_path = tmp_path / ".signing_key"
    key_path.write_bytes(b"short")
    with pytest.raises(SignatureError):
        load_or_create_key(key_path)
