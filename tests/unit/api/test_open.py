"""Unit tests for ``hmp.open``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def test_open_returns_simulation_catalog(tmp_path: Path) -> None:
    """``hmp.open`` returns a SimulationCatalog instance."""
    cat = hmp.open(tmp_path)
    try:
        assert isinstance(cat, hmp.SimulationCatalog)
    finally:
        cat.close()


def test_open_accepts_string_workspace(tmp_path: Path) -> None:
    """``hmp.open`` accepts a string path."""
    cat = hmp.open(str(tmp_path))
    try:
        assert isinstance(cat, hmp.SimulationCatalog)
    finally:
        cat.close()


def test_open_delegates_to_simulation_catalog(monkeypatch, tmp_path: Path) -> None:
    """``hmp.open`` forwards the workspace argument to ``SimulationCatalog``."""
    captured: dict = {}

    class FakeCatalog:
        def __init__(self, workspace_path):
            captured["workspace_path"] = workspace_path

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(
        "hydromodpy.results.catalog.SimulationCatalog",
        FakeCatalog,
    )
    cat = hmp.open(tmp_path)
    assert isinstance(cat, FakeCatalog)
    assert captured["workspace_path"] == tmp_path
