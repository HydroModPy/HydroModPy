"""Unit tests for ``hmp.open`` (single catalog door + fail-fast)."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def test_open_missing_catalog_raises(tmp_path: Path) -> None:
    """``hmp.open`` on an empty directory fails fast, no phantom catalog."""
    with pytest.raises(FileNotFoundError):
        hmp.open(tmp_path)
    assert not (tmp_path / "catalog.duckdb").exists()


def test_open_create_returns_simulation_catalog(tmp_path: Path) -> None:
    """``create=True`` opens (and initialises) a SimulationCatalog."""
    cat = hmp.open(tmp_path, create=True)
    try:
        assert isinstance(cat, hmp.SimulationCatalog)
    finally:
        cat.close()


def test_open_accepts_string_workspace(tmp_path: Path) -> None:
    """``hmp.open`` accepts a string path."""
    cat = hmp.open(str(tmp_path), create=True)
    try:
        assert isinstance(cat, hmp.SimulationCatalog)
    finally:
        cat.close()


def test_open_existing_catalog_without_create(tmp_path: Path) -> None:
    """Once a catalog exists, ``hmp.open`` works with the default create=False."""
    hmp.open(tmp_path, create=True).close()
    cat = hmp.open(tmp_path)
    try:
        assert isinstance(cat, hmp.SimulationCatalog)
        assert cat.frame.empty
    finally:
        cat.close()
