"""Unit tests for ``hmp.compare_pair``."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def test_compare_pair_delegates_to_pairwise(monkeypatch, tmp_path: Path) -> None:
    """``hmp.compare_pair`` forwards arguments to the pairwise comparator."""
    captured: dict = {}

    def fake_compare(sim_a, sim_b, *, workspace=None):
        captured["sim_a"] = sim_a
        captured["sim_b"] = sim_b
        captured["workspace"] = workspace
        return pd.DataFrame({"metric": ["nse"], "A": [0.5], "B": [0.6]})

    monkeypatch.setattr("hydromodpy.analysis.comparison.pairwise.compare_pair", fake_compare)

    result = hmp.compare_pair("ab12cd34", "ef56gh78", workspace=tmp_path)
    assert isinstance(result, pd.DataFrame)
    assert captured["sim_a"] == "ab12cd34"
    assert captured["sim_b"] == "ef56gh78"
    assert captured["workspace"] == tmp_path


def test_compare_pair_default_workspace(monkeypatch) -> None:
    """``workspace`` defaults to None when not provided."""
    captured: dict = {}

    def fake_compare(sim_a, sim_b, *, workspace=None):
        captured["workspace"] = workspace
        return pd.DataFrame()

    monkeypatch.setattr("hydromodpy.analysis.comparison.pairwise.compare_pair", fake_compare)

    hmp.compare_pair("a", "b")
    assert captured["workspace"] is None


def test_compare_pair_propagates_errors(monkeypatch) -> None:
    """Errors raised by the backend are propagated."""

    def fake_compare(sim_a, sim_b, *, workspace=None):
        raise FileNotFoundError("no catalog")

    monkeypatch.setattr("hydromodpy.analysis.comparison.pairwise.compare_pair", fake_compare)

    with pytest.raises(FileNotFoundError, match="no catalog"):
        hmp.compare_pair("a", "b")
