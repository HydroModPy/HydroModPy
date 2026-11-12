"""The yearly extent masks of a simulated stream network, on the V-valley bench.

The bench has no DEM and no solve: a release field is a drained-area cut on a
checkerboard, and a head of network moving up and down the valley over the
year is a cut that falls in the wet season and rises in the dry one. Every
receiver is known, so every mask can be checked against its definition. The
two-bound scoring window cuts the calendar years of a run to the years it holds
whole: a spin-up year leaves the score unless the window keeps it.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.drainage.routing import route_release_to_discharge
from hydromodpy.catchment.stream_network.extent import (
    calendar_years,
    extent_masks,
    extent_step_problems,
    flowing_cells,
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


def _closed_downstream(bench, mask: np.ndarray) -> bool:
    downstream = bench.metric.graph.downstream
    cells = np.flatnonzero(mask)
    receivers = downstream[cells]
    return bool(np.all(mask[receivers[receivers >= 0]]))


class TestVisibleFlow:
    @pytest.mark.parametrize(
        ("text", "discharge", "share"),
        [
            ("1 L/s", 1.0e-3, 0.0),
            ("0.002 m3/s", 2.0e-3, 0.0),
            ("1%", 0.0, 0.01),
            ("0.5 %", 0.0, 0.005),
            ("0 L/s", 0.0, 0.0),
        ],
    )
    def test_a_discharge_or_a_share_is_read(self, text, discharge, share) -> None:
        visible = parse_visible_flow(text)
        assert visible.discharge_m3_s == pytest.approx(discharge)
        assert visible.outlet_share == pytest.approx(share)

    def test_a_bare_number_is_refused_for_its_missing_unit(self) -> None:
        with pytest.raises(ValueError, match="no unit"):
            parse_visible_flow("1")

    @pytest.mark.parametrize("text", ["150%", "-1 L/s", "1 m", "fast"])
    def test_a_threshold_that_is_no_flow_is_refused(self, text) -> None:
        with pytest.raises(ValueError):
            parse_visible_flow(text)

    def test_a_threshold_is_either_a_discharge_or_a_share(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            VisibleFlow(discharge_m3_s=1e-3, outlet_share=0.01)


class TestFlowing:
    def test_a_share_reads_the_outlet_at_the_same_timestep(self, bench) -> None:
        stack = _stack(bench, [5.0, 200.0])
        share = VisibleFlow(outlet_share=0.05)
        state = flowing_cells(
            stack,
            threshold_m3_s=_no_threshold(),
            metric=bench.metric,
            visible_flow=share,
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

    def test_a_share_needs_the_outlet(self, bench) -> None:
        with pytest.raises(ValueError, match="outlet"):
            flowing_cells(
                _release(bench, 5.0),
                threshold_m3_s=_no_threshold(),
                metric=bench.metric,
                visible_flow=VisibleFlow(outlet_share=0.01),
            )


class TestCalendarYears:
    def test_bounds_must_increase(self) -> None:
        with pytest.raises(ValueError, match="increase"):
            calendar_years(np.array(["2001-01-01", "2001-01-01"], dtype="datetime64[ns]"))


class TestMasks:
    @pytest.fixture
    def seasonal(self, bench):
        thresholds = _seasonal_thresholds(3, wet=5.0, dry=600.0, shift=[0.5, 1.0, 2.0])
        stack = _stack(bench, thresholds)
        years = calendar_years(_monthly_edges(2001, 3))
        counts = yearly_flow_counts(
            stack, years=years, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
        return stack, counts

    def test_a_mask_becomes_the_network_the_criterion_scores(self, seasonal) -> None:
        _, counts = seasonal
        masks = extent_masks(counts)
        network = masks.network("minimal", threshold_m3_s=_no_threshold(), year=2002)
        np.testing.assert_array_equal(network.network, masks.yearly_minimal[1])
        with pytest.raises(ValueError, match="bound"):
            masks.network("median", threshold_m3_s=_no_threshold())  # type: ignore[arg-type]


class TestStepRules:
    def test_no_complete_year_is_refused(self) -> None:
        assert extent_step_problems([], maximal_flowing_steps=1, minimal_dry_steps=1)

    def test_extent_masks_refuses_the_same_rules(self, bench) -> None:
        stack = _stack(bench, [10.0] * 12)
        counts = yearly_flow_counts(
            stack,
            years=calendar_years(_monthly_edges(2001, 1)),
            threshold_m3_s=_no_threshold(),
            metric=bench.metric,
        )
        with pytest.raises(ValueError, match="maximal rule of 13 timestep"):
            extent_masks(counts, maximal_flowing_steps=13)


def _daily_edges(first: str, last: str) -> np.ndarray:
    return np.arange(np.datetime64(first), np.datetime64(last), np.timedelta64(1, "D"))


DAILY = _daily_edges("2000-01-01", "2003-01-02")
"""1096 daily steps, 2000 to 2002, as example 04 runs."""


def test_a_reversed_window_is_refused() -> None:
    with pytest.raises(ValueError, match="after its end"):
        calendar_years(DAILY, window=("2002-01-01", "2001-01-01"))


def test_a_bound_that_is_no_date_is_refused() -> None:
    with pytest.raises(ValueError, match="not a date"):
        calendar_years(DAILY, window=("spring", None))
