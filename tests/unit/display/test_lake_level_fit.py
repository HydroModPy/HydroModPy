"""Fit of a simulated lake level to its observed record, daily stage in m.

The fit reports NSE, RMSE (m), bias (m) and the sample count on the stamps the
two series share. A lake level is the state at its stamp, so the simulation is
stamped at the instants of the record.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.lake_level_fit import (
    lake_level_fit_metrics,
    plot_lake_level_fit,
)


def daily(values: list[float], start: str = "2019-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=index, dtype="float64")


def simulated(obs: pd.Series, offset: float = 0.0) -> pd.Series:
    """The run that matches ``obs`` up to ``offset``, on the same stamps."""
    return pd.Series(obs.to_numpy() + offset, index=obs.index, dtype="float64")


def test_perfect_fit() -> None:
    obs = daily([10.0, 11.0, 12.0, 13.0])

    m = lake_level_fit_metrics(obs, simulated(obs))

    assert m["nse"] == pytest.approx(1.0)
    assert m["rmse"] == pytest.approx(0.0)
    assert m["bias"] == pytest.approx(0.0)
    assert m["n"] == 4.0


def test_offset_fit() -> None:
    obs = daily([10.0, 11.0, 12.0, 13.0])

    m = lake_level_fit_metrics(obs, simulated(obs, 0.5))

    assert m["rmse"] == pytest.approx(0.5)
    assert m["bias"] == pytest.approx(0.5)


def test_no_overlap_returns_empty() -> None:
    obs = daily([1.0, 2.0], start="2019-01-01")
    sim = daily([1.0, 2.0], start="2021-01-01")

    assert lake_level_fit_metrics(obs, sim) == {}


def test_writes_png_and_returns_metrics(tmp_path: Path) -> None:
    obs = daily(list(np.linspace(80.0, 90.0, 30)))
    out = tmp_path / "fit.png"

    metrics = plot_lake_level_fit(obs, simulated(obs, 0.3), out_path=out, lake_id="lac0")

    assert out.exists() and out.stat().st_size > 0
    assert metrics["bias"] == pytest.approx(0.3)
    assert metrics["nse"] > 0.9


def test_renders_without_observed_overlap(tmp_path: Path) -> None:
    obs = daily([1.0, 2.0], start="2021-01-01")
    sim = daily([80.0, 81.0, 82.0], start="2019-01-01")
    out = tmp_path / "fit.png"

    metrics = plot_lake_level_fit(obs, sim, out_path=out, lake_id="lac0")

    assert out.exists()
    assert metrics == {}  # no overlap, but the figure still renders


def test_empty_simulated_series_is_refused(tmp_path: Path) -> None:
    obs = daily([1.0, 2.0, 3.0])
    sim = pd.Series([], dtype="float64")

    with pytest.raises(ValueError, match="simulated series is empty"):
        plot_lake_level_fit(obs, sim, out_path=tmp_path / "x.png")
