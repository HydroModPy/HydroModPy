"""The yearly extent masks of a simulated stream network, on the V-valley bench.

The bench has no DEM and no solve: a release field is a drained-area cut on a
checkerboard, and a head of network moving up and down the valley over the
year is a cut that falls in the wet season and rises in the dry one. Every
receiver is known, so every mask can be checked against its definition. The
two-bound scoring window cuts the calendar years of a run to the years it holds
whole: a spin-up year leaves the score unless the window keeps it.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from hydromodpy.catchment.drainage.routing import route_release_to_discharge
from hydromodpy.catchment.stream_network.extent import (
    calendar_years,
    extent_masks,
    extent_step_problems,
    flowing_cells,
    flowing_steps,
    quorum_count,
    yearly_flow_counts,
)
from hydromodpy.core.scoring.stream_defaults import VisibleFlow, parse_visible_flow
from tests._helpers.v_valley import N_CELLS, build_bench, simulated_network

RELEASE = 1.0e-6
"""m3/s released by a seeping cell of the bench."""


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _release(bench, threshold: float) -> np.ndarray:
    return np.where(simulated_network(bench, threshold), RELEASE, 0.0)


def _stack(bench, thresholds) -> np.ndarray:
    return np.vstack([_release(bench, float(value)) for value in thresholds])


def _no_threshold() -> np.ndarray:
    return np.zeros(N_CELLS)


def _monthly_edges(first_year: int, n_years: int) -> np.ndarray:
    months = np.arange(
        np.datetime64(f"{first_year}-01"),
        np.datetime64(f"{first_year + n_years}-02"),
        np.timedelta64(1, "M"),
    )
    return months.astype("datetime64[ns]")


def _seasonal_thresholds(n_years: int, *, wet: float, dry: float, shift=None) -> np.ndarray:
    """A drained-area cut per month: lowest in February, highest in August."""
    month = np.arange(12)
    season = 0.5 * (1.0 + np.cos(2.0 * np.pi * (month - 1) / 12.0))
    rows = []
    for year in range(n_years):
        scale = 1.0 if shift is None else shift[year]
        rows.append(scale * np.exp(np.log(dry) + season * (np.log(wet) - np.log(dry))))
    return np.concatenate(rows)


VISIBLE_FLOWS = [
    pytest.param("1 L/s", 1.0e-3, 0.0, id="litres per second"),
    pytest.param("0.002 m3/s", 2.0e-3, 0.0, id="cubic metres per second"),
    pytest.param("1%", 0.0, 0.01, id="percent"),
    pytest.param("0.5 %", 0.0, 0.005, id="percent with a space"),
    pytest.param("0 L/s", 0.0, 0.0, id="zero discharge"),
]


@pytest.mark.parametrize(("text", "discharge", "share"), VISIBLE_FLOWS)
def test_visible_flow_is_read(text, discharge, share) -> None:
    visible = parse_visible_flow(text)
    assert visible.discharge_m3_s == pytest.approx(discharge)
    assert visible.outlet_share == pytest.approx(share)


def test_a_share_reads_the_outlet_at_the_same_timestep(bench) -> None:
    stack = _stack(bench, [5.0, 200.0])
    state = flowing_cells(
        stack,
        threshold_m3_s=_no_threshold(),
        metric=bench.metric,
        visible_flow=VisibleFlow(outlet_share=0.05),
        outlet=bench.outlet,
    )
    for row in range(2):
        discharge = route_release_to_discharge(
            np.where(stack[row] > 0.0, stack[row], 0.0),
            bench.metric.graph,
            catchment_mask=bench.metric.graph.active,
        )
        required = 0.05 * discharge[bench.outlet]
        expected = np.nan_to_num(discharge) >= required
        np.testing.assert_array_equal(state.flowing[row], expected & (discharge > 0.0))


def test_a_mask_becomes_the_network_the_criterion_scores(bench) -> None:
    thresholds = _seasonal_thresholds(3, wet=5.0, dry=600.0, shift=[0.5, 1.0, 2.0])
    counts = yearly_flow_counts(
        _stack(bench, thresholds),
        years=calendar_years(_monthly_edges(2001, 3)),
        threshold_m3_s=_no_threshold(),
        metric=bench.metric,
    )
    masks = extent_masks(counts)
    network = masks.network("minimal", threshold_m3_s=_no_threshold(), year=2002)
    np.testing.assert_array_equal(network.network, masks.yearly_minimal[1])
    with pytest.raises(ValueError, match="bound"):
        masks.network("median", threshold_m3_s=_no_threshold())  # type: ignore[arg-type]


def _daily_edges(first: str, last: str) -> np.ndarray:
    return np.arange(np.datetime64(first), np.datetime64(last), np.timedelta64(1, "D"))


DAILY = _daily_edges("2000-01-01", "2003-01-02")
"""1096 daily steps, 2000 to 2002, as example 04 runs."""


PARSE_REFUSALS = [
    pytest.param("1", "no unit", id="bare number"),
    pytest.param("150%", None, id="share above 100 %"),
    pytest.param("-1 L/s", None, id="negative discharge"),
    pytest.param("1 m", None, id="a length"),
    pytest.param("fast", None, id="not a number"),
]


@pytest.mark.parametrize(("text", "match"), PARSE_REFUSALS)
def test_visible_flow_refusals(text, match) -> None:
    with pytest.raises(ValueError, match=match):
        parse_visible_flow(text)


def test_threshold_is_a_discharge_or_a_share() -> None:
    with pytest.raises(ValueError, match="not both"):
        VisibleFlow(discharge_m3_s=1e-3, outlet_share=0.01)


def test_share_needs_the_outlet(bench) -> None:
    with pytest.raises(ValueError, match="outlet"):
        flowing_cells(
            _release(bench, 5.0),
            threshold_m3_s=_no_threshold(),
            metric=bench.metric,
            visible_flow=VisibleFlow(outlet_share=0.01),
        )


CALENDAR_REFUSALS = [
    pytest.param(
        np.array(["2001-01-01", "2001-01-01"], dtype="datetime64[ns]"),
        None,
        "increase",
        id="bounds do not increase",
    ),
    pytest.param(DAILY, ("2002-01-01", "2001-01-01"), "after its end", id="reversed window"),
    pytest.param(DAILY, ("spring", None), "not a date", id="bound is no date"),
]


@pytest.mark.parametrize(("edges", "window", "match"), CALENDAR_REFUSALS)
def test_calendar_refusals(edges, window, match) -> None:
    with pytest.raises(ValueError, match=match):
        calendar_years(edges, window=window)


def test_no_complete_year_is_refused() -> None:
    assert extent_step_problems([], maximal_flowing_steps=1, minimal_dry_steps=1)


def test_masks_refuse_the_same_step_rules(bench) -> None:
    counts = yearly_flow_counts(
        _stack(bench, [10.0] * 12),
        years=calendar_years(_monthly_edges(2001, 1)),
        threshold_m3_s=_no_threshold(),
        metric=bench.metric,
    )
    with pytest.raises(ValueError, match="maximal rule of 13 timestep"):
        extent_masks(counts, maximal_flowing_steps=13)


def test_flowing_cells_refuses_a_wrong_size(bench) -> None:
    with pytest.raises(ValueError, match=f"release_flux must hold {N_CELLS} cells, got shape"):
        flowing_cells(np.zeros(N_CELLS - 1), threshold_m3_s=_no_threshold(), metric=bench.metric)
    with pytest.raises(ValueError, match=f"the threshold holds 3 cells, the mesh holds {N_CELLS}"):
        flowing_cells(_release(bench, 5.0), threshold_m3_s=np.zeros(3), metric=bench.metric)


def test_a_run_of_one_edge_holds_no_year() -> None:
    years = calendar_years(np.array(["2001-01-01"], dtype="datetime64[ns]"))

    assert years.years == ()
    assert years.steps == ()


def test_yearly_counts_refuse_a_wrong_stack(bench) -> None:
    years = calendar_years(_monthly_edges(2001, 1))

    with pytest.raises(ValueError, match="must be .n_times, n_cells., got shape"):
        yearly_flow_counts(
            _release(bench, 5.0), years=years, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
    # Twelve monthly steps in the calendar, six rows in the stack.
    with pytest.raises(ValueError, match="names timestep 11 and the release stack holds 6"):
        yearly_flow_counts(
            _stack(bench, [10.0] * 6),
            years=years,
            threshold_m3_s=_no_threshold(),
            metric=bench.metric,
        )


STEP_RULES = [
    pytest.param(0, 0, "below one timestep", id="no flowing step asked"),
    pytest.param(2, -1, "dry timestep.s. is negative", id="negative dry rule"),
]


@pytest.mark.parametrize(("n_max", "n_min", "match"), STEP_RULES)
def test_step_rules_that_cannot_be_read(n_max, n_min, match) -> None:
    problems = extent_step_problems([12, 12], maximal_flowing_steps=n_max, minimal_dry_steps=n_min)

    assert any(re.search(match, text) for text in problems)


def test_quorum_refusals() -> None:
    with pytest.raises(ValueError, match="year_quorum must lie in"):
        quorum_count(5, 0.0)
    with pytest.raises(ValueError, match="at least one scored year"):
        quorum_count(0, 0.5)


def test_a_zero_timestep_is_refused() -> None:
    with pytest.raises(ValueError, match="timestep must be positive, got 0.0 days"):
        flowing_steps(30.0, 0.0)
