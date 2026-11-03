"""A series figure shades the period that precedes ``[metrics] window``.

The spin-up is the part of a run before the window it is scored on. Each figure
that draws a time series of one run reads that window from the run (the score
it sealed, else the ``[metrics]`` window of its config) and shades what comes
before it. No figure option names it, and a run without a window shades nothing.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.flux_timeseries import FluxTimeseries
from hydromodpy.display.figures.hydrograph import Hydrograph
from hydromodpy.display.figures.hydrograph_sim_obs import HydrographSimObs
from hydromodpy.display.figures.lake_level_sim_obs import LakeStageSimObs
from hydromodpy.display.figures.piezo_timeseries_sim_obs import PiezoTimeseriesSimObs
from hydromodpy.display.figures.residuals import Residuals
from hydromodpy.display.figures.sfr_reach_timeseries import SfrReachTimeseries

STAMPS = pd.date_range("2011-01-01", periods=10, freq="D")
WINDOW_START = datetime.date(2011, 1, 5)
LABEL = "before the scoring window"


@pytest.fixture(autouse=True)
def mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


class _Run:
    """A run holding the series of every figure under test."""

    sim_id = "sim-spinup"
    name = "spinup"
    periods = SimpleNamespace(edges=pd.date_range("2010-12-31", periods=11, freq="D"))

    def __init__(self, *, sealed=None, snapshot=None) -> None:
        if sealed is not None:
            self.metrics = pd.DataFrame(
                [
                    {
                        "station": "J1",
                        "variable": "discharge",
                        "metric": "nse",
                        "value": 0.5,
                        "window_start": sealed[0],
                        "window_end": sealed[1],
                        "n_samples": 3,
                        "metric_rule_version": "1",
                    }
                ]
            )
        self.config_snapshot = snapshot

    def has_table(self, table: str) -> bool:
        return True

    def has_field(self, variable: str, **_) -> bool:
        return True

    def stations(self, variable: str) -> list[str]:
        return ["_catchment", "sfr:net:1"]

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        return pd.Series(np.linspace(1.0, 2.0, len(STAMPS)), index=STAMPS)

    def observed(self, variable: str, station: str | None = None, period=None) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "station_id": ["J1"] * len(STAMPS),
                "datetime": STAMPS.shift(-1, freq="D"),
                "value": np.linspace(1.1, 2.1, len(STAMPS)) + 0.05 * (np.arange(len(STAMPS)) % 3),
            }
        )

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge"] * 10,
                "timestep": list(range(10)),
                "flux_in": [1.0] * 10,
                "flux_out": [0.0] * 10,
            }
        )


def _residuals(run):
    return Residuals().plot(run, observed_station="J1").axes[0]


def _drawn(figure_name, run, monkeypatch=None):
    import matplotlib.pyplot as plt

    if figure_name == "residuals":
        return _residuals(run)
    fig, ax = plt.subplots()
    figure = {
        "hydrograph": Hydrograph,
        "hydrograph_sim_obs": HydrographSimObs,
        "piezo": PiezoTimeseriesSimObs,
        "sfr": SfrReachTimeseries,
        "flux": FluxTimeseries,
        "lake_stage": LakeStageSimObs,
    }[figure_name]()
    options = {"piezo": {"station": "obs:P1"}, "sfr": {"variable": "stage"}}.get(figure_name, {})
    if figure_name == "lake_stage":
        from hydromodpy.display.figures import lake_level_sim_obs

        monkeypatch.setattr(lake_level_sim_obs, "_default_lake", lambda sim: "L1")
    figure.render(run, ax, **options)
    return ax


FIGURES = ["hydrograph", "hydrograph_sim_obs", "piezo", "sfr", "flux", "lake_stage", "residuals"]


def _shades(ax):
    return [patch for patch in ax.patches if patch.get_label() == LABEL]


@pytest.mark.parametrize("figure", FIGURES)
def test_a_series_figure_shades_up_to_the_sealed_window_start(figure, monkeypatch) -> None:
    run = _Run(sealed=(WINDOW_START, datetime.date(2011, 1, 8)))

    ax = _drawn(figure, run, monkeypatch)

    (shade,) = _shades(ax)
    assert shade.get_x() + shade.get_width() == pytest.approx(
        mdates.date2num(datetime.datetime(2011, 1, 5))
    )
    assert shade.get_x() == pytest.approx(ax.get_xlim()[0])


@pytest.mark.parametrize("figure", FIGURES)
def test_a_run_without_a_window_shades_nothing(figure, monkeypatch) -> None:
    ax = _drawn(figure, _Run(), monkeypatch)

    assert _shades(ax) == []


def test_the_window_of_the_config_serves_a_run_that_sealed_no_score() -> None:
    snapshot = {"metrics": {"window": {"start": "2011-01-04", "end": "2011-01-09"}}}

    ax = _drawn("hydrograph", _Run(snapshot=snapshot))

    (shade,) = _shades(ax)
    assert shade.get_x() + shade.get_width() == pytest.approx(
        mdates.date2num(datetime.datetime(2011, 1, 4))
    )


def test_a_window_that_starts_with_the_run_shades_nothing() -> None:
    run = _Run(sealed=(datetime.date(2010, 12, 1), datetime.date(2011, 1, 8)))

    assert _shades(_drawn("hydrograph", run)) == []


def test_the_shade_says_what_it_is_in_the_legend() -> None:
    ax = _drawn("hydrograph", _Run(sealed=(WINDOW_START, datetime.date(2011, 1, 8))))

    assert LABEL in [text.get_text() for text in ax.get_legend().get_texts()]
