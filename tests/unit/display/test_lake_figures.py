"""The lake figures: abacus comparison and level fit."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.lake_abacus_comparison import (
    lake_abacus_fit_metrics,
    plot_lake_abacus_comparison,
)
from hydromodpy.display.figures.lake_level_fit import (
    lake_level_fit_metrics,
    plot_lake_level_fit,
)

# Lake abacus comparison figure: arrays in, PNG out, storage metrics returned.


def test_metrics_perfect_match_is_nse_one():
    real = [0.0, 100.0, 400.0, 900.0]
    metrics = lake_abacus_fit_metrics(real, real)
    assert metrics["nse"] == 1.0
    assert metrics["rmse"] == 0.0
    assert metrics["max_abs_error"] == 0.0


def test_plot_writes_png_and_returns_metrics(tmp_path):
    stage = [20.0, 30.0, 40.0, 50.0]
    real_vol = [0.0, 1000.0, 4000.0, 9000.0]
    sim_vol = [0.0, 1010.0, 3980.0, 9050.0]
    real_area = [0.0, 100.0, 200.0, 300.0]
    sim_area = [0.0, 100.0, 200.0, 300.0]
    out = tmp_path / "abacus.png"
    metrics = plot_lake_abacus_comparison(
        stage, real_vol, real_area, sim_vol, sim_area, out_path=out, lake_id="lac0"
    )
    assert out.exists()
    assert out.stat().st_size > 0
    assert metrics["nse"] > 0.999


class _FakeRun:
    name = "fake"
    sim_id = "0000"


def test_registered_figure_renders_from_run(monkeypatch):
    import hydromodpy.results.run.lake_abacus_view as view
    from hydromodpy.display.figure import new_subplots
    from hydromodpy.display.figure_registry import get

    monkeypatch.setattr(
        view,
        "run_lake_abacus",
        lambda run, lake_id=None: {
            "stage": [20.0, 30.0, 40.0],
            "real_volume": [0.0, 1000.0, 4000.0],
            "sim_volume": [0.0, 1010.0, 3980.0],
            "real_sarea": [0.0, 100.0, 200.0],
            "sim_sarea": [0.0, 100.0, 200.0],
            "stage_unit": "m",
            "volume_unit": "m3",
        },
    )

    fig_obj = get("lake_abacus_comparison")
    assert fig_obj.spec.name == "lake_abacus_comparison"
    fig, ax = new_subplots()
    fig_obj.render(_FakeRun(), ax)
    # Two curves drawn (reference + simulated).
    assert len(ax.get_lines()) == 2


# Tests for the reusable lake-level fit figure.


def _series(values: list[float], start: str = "2019-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


def _simulated(obs: pd.Series, offset: float = 0.0) -> pd.Series:
    """The run that matches ``obs`` up to ``offset``.

    A lake level is the state AT its stamp, not the mean of the period the
    stamp closes, so the run is stamped at the very instants the record was
    read. Shifting it by a day, as a discharge is, would score each stage
    against the reading of the day before.
    """
    return pd.Series(obs.to_numpy() + offset, index=obs.index, dtype="float64")


class TestMetrics:
    def test_perfect_fit(self):
        obs = _series([10.0, 11.0, 12.0, 13.0])
        m = lake_level_fit_metrics(obs, _simulated(obs))
        assert m["nse"] == pytest.approx(1.0)
        assert m["rmse"] == pytest.approx(0.0)
        assert m["bias"] == pytest.approx(0.0)
        assert m["n"] == 4.0

    def test_offset_fit(self):
        obs = _series([10.0, 11.0, 12.0, 13.0])
        sim = _simulated(obs, 0.5)
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
        sim = _simulated(obs, 0.3)
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
