"""A figure title says what a first-time reader needs, in words.

Measured on the example 04 gallery: titles ended with ``@ _catchment``, the id
a run stores its outlet series under; a map of October 2002 was titled with
the stamp that closes it, 2002-11-01; the confusion map carried no date at
all; the section named itself by four projected coordinates; the flux axis
read ``m3/s`` beside ``m³/s`` everywhere else, and each monthly flux was drawn
one month late.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.units.labels import CATCHMENT_OUTLET_STATION, station_label
from hydromodpy.display.figures._instant import instant_label
from hydromodpy.display.figures.cross_section import heading_words, section_words
from hydromodpy.display.figures.duration_curve import DurationCurveFigure
from hydromodpy.display.figures.flux_timeseries import FluxTimeseries
from hydromodpy.display.figures.hydrograph import Hydrograph
from hydromodpy.display.figures.piezometric_map import PiezometricMap
from hydromodpy.display.figures.recession import RecessionCurveFigure
from hydromodpy.display.figures.seepage_network_confusion_map import (
    SeepageNetworkConfusionMap,
)

from ._network_comparison_run import AXIS_COLUMN, cell, comparison_run

MONTHLY = pd.date_range("2000-01-01", "2003-01-01", freq="MS")
DAILY = pd.date_range("2002-10-01", "2002-11-01", freq="D")


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


# --------------------------------------------------------------------------- #
# the station
# --------------------------------------------------------------------------- #


def test_the_outlet_series_is_named_the_catchment_outlet() -> None:
    assert station_label(CATCHMENT_OUTLET_STATION) == "catchment outlet"


def test_a_gauge_keeps_its_own_id() -> None:
    assert station_label("J7000610") == "J7000610"


class _SeriesRun:
    sim_id = "sim-a"
    name = "nancon"

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        index = pd.date_range("2001-01-01", periods=12, freq="D")
        return pd.Series(np.linspace(2.0, 0.5, 12), index=index, name=variable)


@pytest.mark.parametrize(
    "figure", [Hydrograph(), DurationCurveFigure(), RecessionCurveFigure()], ids=type
)
def test_no_title_prints_the_internal_station_id(mpl, figure) -> None:
    fig, ax = mpl.subplots()

    figure.render(_SeriesRun(), ax)

    assert "@ catchment outlet" in ax.get_title()
    assert "_catchment" not in ax.get_title()


# --------------------------------------------------------------------------- #
# the instant
# --------------------------------------------------------------------------- #


def _dated(edges) -> SimpleNamespace:
    return SimpleNamespace(
        periods=SimpleNamespace(edges=None if edges is None else pd.DatetimeIndex(edges))
    )


def test_a_monthly_state_is_titled_by_its_month_not_its_closing_stamp() -> None:
    # Period 33 of a monthly run from January 2000 is October 2002, stamped
    # 2002-11-01 by the solver.
    assert instant_label(_dated(MONTHLY), 33) == "October 2002"


def test_a_negative_index_counts_from_the_end() -> None:
    assert instant_label(_dated(MONTHLY), -1) == "December 2002"


def test_a_daily_state_is_titled_by_its_day() -> None:
    assert instant_label(_dated(DAILY), 14) == "2002-10-15"


def test_a_run_without_dates_or_a_step_it_does_not_hold_has_no_label() -> None:
    assert instant_label(_dated(None), 0) == ""
    assert instant_label(_dated(MONTHLY), 36) == ""


def test_a_run_exposing_only_its_end_stamps_is_still_labelled() -> None:
    run = SimpleNamespace(time_index=MONTHLY[1:])
    assert instant_label(run, 33) == "October 2002"


def test_a_scalar_map_title_names_the_period_it_draws() -> None:
    run = SimpleNamespace(sim_id="sim-a", name="nancon", periods=SimpleNamespace(edges=MONTHLY))

    title = PiezometricMap().title(run, timestep=33)

    assert title.endswith("\nOctober 2002")
    assert "2002-11-01" not in title


def test_the_confusion_map_names_the_state_it_compared(mpl) -> None:
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, 2)])
    run.periods = SimpleNamespace(edges=pd.DatetimeIndex(["2002-10-01", "2002-11-01"]))
    fig, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(run, ax)

    assert ax.get_title().endswith("\nOctober 2002")


# --------------------------------------------------------------------------- #
# the section
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("dx", "dy", "words"),
    [
        (0.0, 10.0, "south to north"),
        (10.0, 0.0, "west to east"),
        (-10.0, 0.0, "east to west"),
        (10.0, 10.0, "southwest to northeast"),
        (0.0, -10.0, "north to south"),
    ],
)
def test_a_section_says_which_way_it_runs(dx, dy, words) -> None:
    assert heading_words(dx, dy) == words


def test_a_section_subtitle_is_a_sentence_before_any_coordinate() -> None:
    transect = SimpleNamespace(
        x=np.array([389_286.0, 389_286.0]),
        y=np.array([6_815_062.0, 6_826_612.0]),
        distance=np.array([0.0, 11_550.0]),
    )

    words = section_words(transect, anchor="through the outlet")

    assert words == "south to north through the outlet, 11.6 km"


# --------------------------------------------------------------------------- #
# the fluxes
# --------------------------------------------------------------------------- #


class _BudgetRun:
    sim_id = "sim-a"
    name = "nancon"
    periods = SimpleNamespace(
        edges=pd.DatetimeIndex(["2002-01-01", "2002-02-01", "2002-03-01", "2002-04-01"])
    )

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge"] * 3 + ["drain"] * 3,
                "timestep": [0, 1, 2] * 2,
                "flux_in": [3.0, 2.0, 1.0, 0.0, 0.0, 0.0],
                "flux_out": [0.0, 0.0, 0.0, 1.0, 1.5, 2.0],
            }
        )


def test_the_flux_axis_reads_the_shared_unit(mpl) -> None:
    fig, ax = mpl.subplots()

    FluxTimeseries().render(_BudgetRun(), ax)

    assert ax.get_ylabel() == "Flux (m³/s)"


def test_a_flux_is_drawn_over_its_own_period(mpl) -> None:
    import matplotlib.dates as mdates

    fig, ax = mpl.subplots()

    FluxTimeseries().render(_BudgetRun(), ax)

    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    starts = mdates.date2num(pd.DatetimeIndex(recharge.get_xdata()).to_pydatetime())
    edges = mdates.date2num(_BudgetRun.periods.edges.to_pydatetime())
    # January is drawn from 1 January to 1 February, not from its closing stamp.
    assert starts.tolist() == pytest.approx(edges.tolist())
    assert recharge.get_ydata().tolist() == [3.0, 2.0, 1.0, 1.0]


class _ZonedBudgetRun:
    """A run whose ``budgets`` table holds both the domain and the catchment."""

    sim_id = "sim-c"
    name = "nancon"
    periods = SimpleNamespace(edges=pd.DatetimeIndex(["2000-01-01", "2000-02-01"]))

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge", "recharge"],
                "zone_id": ["0", "catchment"],
                "timestep": [0, 0],
                "flux_in": [1.093, 0.586],
                "flux_out": [0.0, 0.0],
            }
        )


def test_flux_timeseries_reads_the_catchment_zone_not_the_domain_sum(mpl) -> None:
    # ``budgets`` holds one row for the whole domain (zone_id "0") and one for
    # the delineated catchment, for the same component and timestep. Summing
    # both, as a plain groupby("component", "timestep") does, drew
    # 1.093 + 0.586 m3/s of January recharge; only the catchment row is a
    # gauge-comparable value.
    fig, ax = mpl.subplots()

    FluxTimeseries().render(_ZonedBudgetRun(), ax)

    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    assert recharge.get_ydata().tolist() == pytest.approx([0.586, 0.586])
    assert "frame: the delineated catchment" in ax.get_title()
