"""Unit tests for ``hmp.index``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.core.state.global_index import GlobalIndex

pytestmark = pytest.mark.fast


def test_index_returns_global_index(tmp_path: Path) -> None:
    """``hmp.index`` returns a GlobalIndex instance."""
    db_path = tmp_path / "index.duckdb"
    idx = hmp.index(db_path)
    try:
        assert isinstance(idx, GlobalIndex)
    finally:
        idx.close()


def test_index_read_only_flag_propagates(tmp_path: Path) -> None:
    """``read_only=True`` returns a read-only GlobalIndex."""
    db_path = tmp_path / "index.duckdb"
    idx = hmp.index(db_path, read_only=True)
    try:
        assert idx.read_only is True
    finally:
        idx.close()


def test_index_default_path_when_none(monkeypatch, tmp_path: Path) -> None:
    """``hmp.index(None)`` delegates to GlobalIndex without explicit path."""
    captured: dict = {}

    class FakeIndex:
        def __init__(self, db_path, *, read_only=False):
            captured["db_path"] = db_path
            captured["read_only"] = read_only

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(
        "hydromodpy.core.state.global_index.GlobalIndex",
        FakeIndex,
    )
    idx = hmp.index()
    assert isinstance(idx, FakeIndex)
    assert captured["db_path"] is None
    assert captured["read_only"] is False


def test_index_resolves_path(monkeypatch, tmp_path: Path) -> None:
    """``hmp.index`` expands and resolves the provided path."""
    captured: dict = {}

    class FakeIndex:
        def __init__(self, db_path, *, read_only=False):
            captured["db_path"] = db_path
            captured["read_only"] = read_only

        def close(self):
            pass

    monkeypatch.setattr(
        "hydromodpy.core.state.global_index.GlobalIndex",
        FakeIndex,
    )
    db_path = tmp_path / "idx.duckdb"
    hmp.index(db_path, read_only=True)
    assert captured["db_path"] == db_path.expanduser().resolve()
    assert captured["read_only"] is True
