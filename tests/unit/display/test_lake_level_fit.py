"""Tests for the reusable lake-level fit figure."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.lake_level_fit import (
    lake_level_fit_metrics,
    plot_lake_level_fit,
)


def _series(values: list[float], start: str = "2019-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


class TestMetrics:
    def test_perfect_fit(self):
        obs = _series([10.0, 11.0, 12.0, 13.0])
        m = lake_level_fit_metrics(obs, obs.copy())
        assert m["nse"] == pytest.approx(1.0)
        assert m["rmse"] == pytest.approx(0.0)
        assert m["bias"] == pytest.approx(0.0)
        assert m["n"] == 4.0

    def test_offset_fit(self):
        obs = _series([10.0, 11.0, 12.0, 13.0])
        sim = obs + 0.5
        m = lake_level_fit_metrics(obs, sim)
        assert m["rmse"] == pytest.approx(0.5)
        assert m["bias"] == pytest.approx(0.5)

    def test_no_overlap_returns_empty(self):
        obs = _series([1.0, 2.0], start="2019-01-01")
        sim = _series([1.0, 2.0], start="2021-01-01")
        assert lake_level_fit_metrics(obs, sim) == {}


class TestFigure:
    def test_writes_png_and_returns_metrics(self, tmp_path: Path):
        obs = _series(list(np.linspace(80.0, 90.0, 30)))
        sim = obs + 0.3
        out = tmp_path / "fit.png"
        metrics = plot_lake_level_fit(obs, sim, out_path=out, lake_id="lac0")
        assert out.exists() and out.stat().st_size > 0
        assert metrics["bias"] == pytest.approx(0.3)
        assert metrics["nse"] > 0.9

    def test_empty_simulated_raises(self, tmp_path: Path):
        obs = _series([1.0, 2.0, 3.0])
        sim = pd.Series([], dtype="float64")
        with pytest.raises(ValueError, match="simulated series is empty"):
            plot_lake_level_fit(obs, sim, out_path=tmp_path / "x.png")

    def test_renders_without_observed_overlap(self, tmp_path: Path):
        obs = _series([1.0, 2.0], start="2021-01-01")
        sim = _series([80.0, 81.0, 82.0], start="2019-01-01")
        out = tmp_path / "fit.png"
        metrics = plot_lake_level_fit(obs, sim, out_path=out, lake_id="lac0")
        assert out.exists()
        assert metrics == {}  # no overlap, but the figure still renders
