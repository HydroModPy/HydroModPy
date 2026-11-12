"""Boundary fluxes of the water budget (m3/s), one curve per component over its own period.

The storage family is left out unless asked for. A budget that holds a domain
row and a catchment row is read on the catchment only, the one that compares
with a gauge.
"""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib.dates as mdates
import pandas as pd
import pytest

from hydromodpy.display.figures.flux_timeseries import FluxTimeseries

COMPONENTS = ("recharge", "drain", "storage", "storage_ss", "storage_sy", "river")


def undated_run() -> SimpleNamespace:
    """A run without dates whose budget holds every component above, two steps."""
    rows = [
        {"component": c, "timestep": t, "flux_in": 1.0 + t, "flux_out": 0.5}
        for c in COMPONENTS
        for t in range(2)
    ]
    return SimpleNamespace(sim_id="sim-flux", budget=lambda: pd.DataFrame(rows))


class BudgetRun:
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


class ZonedBudgetRun:
    """A run whose budget table holds both the domain and the catchment."""

    sim_id = "sim-c"
    name = "nancon"
    periods = SimpleNamespace(edges=pd.DatetimeIndex(["2000-01-01", "2000-02-01"]))

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge", "recharge"],
                "zone_id": ["domain", "catchment"],
                "timestep": [0, 0],
                "flux_in": [1.093, 0.586],
                "flux_out": [0.0, 0.0],
            }
        )


STORAGE_CASES = [
    pytest.param(False, {"recharge", "drain", "river"}, id="storage left out"),
    pytest.param(
        True,
        {"recharge", "drain", "river", "storage", "storage ss", "storage sy"},
        id="storage drawn",
    ),
]


@pytest.mark.parametrize(("include_storage", "drawn"), STORAGE_CASES)
def test_storage_family_is_drawn_only_on_request(mpl, include_storage, drawn) -> None:
    fig, ax = mpl.subplots()

    FluxTimeseries().render(undated_run(), ax, include_storage=include_storage)

    labels = {line.get_label() for line in ax.get_lines() if not line.get_label().startswith("_")}
    assert labels == drawn


def test_flux_axis_reads_the_shared_unit(mpl) -> None:
    fig, ax = mpl.subplots()

    FluxTimeseries().render(BudgetRun(), ax)

    assert ax.get_ylabel() == "Flux (m³/s)"


def test_flux_is_drawn_over_its_own_period(mpl) -> None:
    fig, ax = mpl.subplots()

    FluxTimeseries().render(BudgetRun(), ax)

    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    starts = mdates.date2num(pd.DatetimeIndex(recharge.get_xdata()).to_pydatetime())
    edges = mdates.date2num(BudgetRun.periods.edges.to_pydatetime())
    # January is drawn from 1 January to 1 February, not from its closing stamp.
    assert starts.tolist() == pytest.approx(edges.tolist())
    assert recharge.get_ydata().tolist() == [3.0, 2.0, 1.0, 1.0]


def test_catchment_zone_is_read_not_the_domain_sum(mpl) -> None:
    # Summing the domain row and the catchment row drew 1.093 + 0.586 m3/s of
    # January recharge. Only the catchment row is gauge-comparable.
    fig, ax = mpl.subplots()

    FluxTimeseries().render(ZonedBudgetRun(), ax)

    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    assert recharge.get_ydata().tolist() == pytest.approx([0.586, 0.586])
    assert "frame: the delineated catchment" in ax.get_title()
