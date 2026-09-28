"""The yearly extent masks of a simulated stream network, on the V-valley bench.

The bench has no DEM and no solve: a release field is a drained-area cut on a
checkerboard, and a head of network moving up and down the valley over the
year is a cut that falls in the wet season and rises in the dry one. Every
receiver is known, so every mask can be checked against its definition.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.stream_extent import (
    GEOMETRIC,
    VisibleFlow,
    calendar_years,
    extent_masks,
    extent_step_problems,
    flow_persistence,
    flowing_cells,
    parse_visible_flow,
    quorum_count,
    routed_discharge,
    yearly_flow_counts,
)
from hydromodpy.core.stream_network import build_simulated_network
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

    def test_zero_is_the_geometric_definition(self) -> None:
        assert parse_visible_flow("0 L/s").geometric
        assert GEOMETRIC.geometric

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
    def test_the_geometric_definition_is_the_network_of_the_criterion(self, bench) -> None:
        release = _release(bench, 40.0)
        state = flowing_cells(release, threshold_m3_s=_no_threshold(), metric=bench.metric)
        network = build_simulated_network(
            release, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
        np.testing.assert_array_equal(state.flowing, network.network)
        np.testing.assert_array_equal(state.seepage, network.seepage)

    def test_a_stack_is_read_row_by_row_as_one_state_each(self, bench) -> None:
        stack = _stack(bench, [10.0, 80.0, 400.0])
        state = flowing_cells(stack, threshold_m3_s=_no_threshold(), metric=bench.metric)
        for row in range(3):
            alone = flowing_cells(stack[row], threshold_m3_s=_no_threshold(), metric=bench.metric)
            np.testing.assert_array_equal(state.flowing[row], alone.flowing)

    def test_the_routed_discharge_never_falls_downstream(self, bench) -> None:
        release = _release(bench, 20.0)
        seepage = release > 0.0
        discharge = routed_discharge(bench.metric, release, seepage)
        downstream = bench.metric.graph.downstream
        cells = np.flatnonzero(downstream >= 0)
        assert np.all(discharge[downstream[cells]] >= discharge[cells] - 1e-18)

    def test_a_rising_visible_flow_gives_nested_shrinking_masks(self, bench) -> None:
        release = _release(bench, 5.0)
        masks = [
            flowing_cells(
                release,
                threshold_m3_s=_no_threshold(),
                metric=bench.metric,
                visible_flow=VisibleFlow(discharge_m3_s=value),
            ).flowing
            for value in (0.0, 5 * RELEASE, 50 * RELEASE, 500 * RELEASE)
        ]
        for wider, narrower in zip(masks[:-1], masks[1:], strict=True):
            assert np.all(wider[narrower])
            assert narrower.sum() < wider.sum()
        for mask in masks:
            assert _closed_downstream(bench, mask)

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
            discharge = routed_discharge(bench.metric, stack[row], stack[row] > 0.0)
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

    def test_a_source_under_the_visible_flow_is_no_longer_a_source(self, bench) -> None:
        state = flowing_cells(
            _release(bench, 5.0),
            threshold_m3_s=_no_threshold(),
            metric=bench.metric,
            visible_flow=VisibleFlow(discharge_m3_s=50 * RELEASE),
        )
        assert np.all(state.flowing[state.seepage])


class TestCalendarYears:
    def test_a_daily_run_splits_into_its_calendar_years(self) -> None:
        edges = np.arange(
            np.datetime64("2000-01-01"), np.datetime64("2003-01-02"), np.timedelta64(1, "D")
        )
        years = calendar_years(edges)
        assert years.years == (2000, 2001, 2002)
        assert years.n_steps.tolist() == [366, 365, 365]
        assert years.incomplete == ()

    def test_a_year_the_run_starts_inside_is_left_out(self) -> None:
        edges = np.arange(
            np.datetime64("2000-03-01"), np.datetime64("2002-01-02"), np.timedelta64(1, "D")
        )
        years = calendar_years(edges)
        assert years.years == (2001,)
        assert years.incomplete == (2000,)

    def test_a_monthly_step_falls_in_the_year_of_its_middle(self) -> None:
        # December ends on 1 January: its middle is still in December.
        years = calendar_years(_monthly_edges(2001, 2))
        assert years.years == (2001, 2002)
        assert years.n_steps.tolist() == [12, 12]

    def test_one_period_holds_no_complete_year(self) -> None:
        years = calendar_years(np.array(["2001-03-01", "2001-09-01"], dtype="datetime64[ns]"))
        assert years.years == ()

    def test_bounds_must_increase(self) -> None:
        with pytest.raises(ValueError, match="increase"):
            calendar_years(np.array(["2001-01-01", "2001-01-01"], dtype="datetime64[ns]"))


class TestCounts:
    def test_a_chunked_read_equals_a_whole_read_bit_for_bit(self, bench) -> None:
        stack = _stack(bench, _seasonal_thresholds(2, wet=5.0, dry=600.0))
        years = calendar_years(_monthly_edges(2001, 2))
        whole = yearly_flow_counts(
            stack, years=years, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
        chunked = yearly_flow_counts(
            stack,
            years=years,
            threshold_m3_s=_no_threshold(),
            metric=bench.metric,
            chunk_elements=N_CELLS * 5,
        )
        np.testing.assert_array_equal(whole.flowing, chunked.flowing)
        np.testing.assert_array_equal(whole.seepage, chunked.seepage)

    def test_a_count_is_the_number_of_flowing_timesteps(self, bench) -> None:
        stack = _stack(bench, _seasonal_thresholds(1, wet=5.0, dry=600.0))
        years = calendar_years(_monthly_edges(2001, 1))
        counts = yearly_flow_counts(
            stack, years=years, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
        expected = sum(
            flowing_cells(row, threshold_m3_s=_no_threshold(), metric=bench.metric).flowing.astype(
                int
            )
            for row in stack
        )
        np.testing.assert_array_equal(counts.flowing[0], expected)
        assert np.all(counts.seepage <= counts.flowing)

    def test_a_constant_run_persists_all_or_nothing(self, bench) -> None:
        stack = _stack(bench, [60.0] * 12)
        years = calendar_years(_monthly_edges(2001, 1))
        counts = yearly_flow_counts(
            stack, years=years, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
        assert set(np.unique(flow_persistence(counts)).tolist()) <= {0.0, 1.0}


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

    def test_at_least_n_steps_is_the_n_th_most_extended_state(self, bench, seasonal) -> None:
        # The bench activates its cells in one order, so the cells flowing at
        # least N steps of a year are the network of its N-th widest step.
        stack, counts = seasonal
        for n_max in (1, 3, 6):
            masks = extent_masks(counts, maximal_flowing_steps=n_max, minimal_dry_steps=0)
            year = stack[:12]
            states = flowing_cells(year, threshold_m3_s=_no_threshold(), metric=bench.metric)
            order = np.argsort(-states.flowing.sum(axis=1), kind="stable")
            np.testing.assert_array_equal(masks.yearly_maximal[0], states.flowing[order[n_max - 1]])

    def test_the_minimal_mask_is_the_driest_states_but_n_min(self, bench, seasonal) -> None:
        stack, counts = seasonal
        masks = extent_masks(counts, maximal_flowing_steps=1, minimal_dry_steps=1)
        states = flowing_cells(stack[:12], threshold_m3_s=_no_threshold(), metric=bench.metric)
        sizes = np.sort(states.flowing.sum(axis=1))
        assert int(masks.yearly_minimal[0].sum()) == int(sizes[1])

    def test_the_minimal_mask_sits_inside_the_maximal_one(self, seasonal) -> None:
        _, counts = seasonal
        for n_max, n_min in ((1, 1), (2, 3), (5, 0)):
            masks = extent_masks(counts, maximal_flowing_steps=n_max, minimal_dry_steps=n_min)
            assert np.all(masks.maximal[masks.minimal])
            assert np.all(masks.yearly_maximal[masks.yearly_minimal])
            assert np.all(masks.maximal[masks.maximal_seepage])

    def test_every_mask_is_closed_downstream(self, bench, seasonal) -> None:
        _, counts = seasonal
        masks = extent_masks(counts, year_quorum=0.5)
        for mask in (masks.maximal, masks.minimal, *masks.yearly_maximal, *masks.yearly_minimal):
            assert _closed_downstream(bench, mask)

    def test_the_quorum_picks_the_median_year_of_three(self, seasonal) -> None:
        # The wet year widens every mask, the dry one narrows it: two in three
        # is the middle year.
        _, counts = seasonal
        masks = extent_masks(counts, year_quorum=0.5)
        assert masks.n_years_required == 2
        np.testing.assert_array_equal(masks.maximal, masks.yearly_maximal[1])
        np.testing.assert_array_equal(masks.minimal, masks.yearly_minimal[1])

    def test_a_quorum_of_one_is_the_intersection(self, seasonal) -> None:
        _, counts = seasonal
        masks = extent_masks(counts, year_quorum=1.0)
        np.testing.assert_array_equal(masks.maximal, masks.yearly_maximal.all(axis=0))

    def test_two_years_at_one_half_are_their_union_and_say_so(self, bench, caplog) -> None:
        stack = _stack(bench, _seasonal_thresholds(2, wet=5.0, dry=600.0, shift=[0.5, 2.0]))
        years = calendar_years(_monthly_edges(2001, 2))
        counts = yearly_flow_counts(
            stack, years=years, threshold_m3_s=_no_threshold(), metric=bench.metric
        )
        with caplog.at_level(logging.WARNING):
            masks = extent_masks(counts, year_quorum=0.5)
        np.testing.assert_array_equal(masks.maximal, masks.yearly_maximal.any(axis=0))
        assert "2 complete year(s)" in caplog.text

    def test_a_mask_becomes_the_network_the_criterion_scores(self, seasonal) -> None:
        _, counts = seasonal
        masks = extent_masks(counts)
        network = masks.network("minimal", threshold_m3_s=_no_threshold(), year=2002)
        np.testing.assert_array_equal(network.network, masks.yearly_minimal[1])
        with pytest.raises(ValueError, match="bound"):
            masks.network("median", threshold_m3_s=_no_threshold())  # type: ignore[arg-type]


class TestStepRules:
    def test_rules_that_fit_the_year_pass(self) -> None:
        assert extent_step_problems([12, 12], maximal_flowing_steps=1, minimal_dry_steps=1) == []

    def test_a_maximal_rule_longer_than_the_year_is_refused(self) -> None:
        problems = extent_step_problems([12], maximal_flowing_steps=30, minimal_dry_steps=1)
        assert any("maximal_flowing_steps = 30" in problem for problem in problems)

    def test_a_minimal_rule_looser_than_the_maximal_one_is_refused(self) -> None:
        problems = extent_step_problems([12], maximal_flowing_steps=6, minimal_dry_steps=8)
        assert any("looser than the complete one" in problem for problem in problems)

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
        with pytest.raises(ValueError, match="maximal_flowing_steps"):
            extent_masks(counts, maximal_flowing_steps=13)

    @pytest.mark.parametrize(
        ("n_years", "quorum", "required"), [(1, 0.5, 1), (2, 0.5, 1), (3, 0.5, 2), (4, 0.75, 3)]
    )
    def test_the_quorum_is_a_ceiling(self, n_years, quorum, required) -> None:
        assert quorum_count(n_years, quorum) == required


def test_the_drained_area_the_bench_cuts_on_is_monotone(bench) -> None:
    # The premise of the hierarchy the masks tests rest on.
    area = accumulate_on_downhill_graph(bench.metric.graph, np.ones(N_CELLS))
    downstream = bench.metric.graph.downstream
    cells = np.flatnonzero(downstream >= 0)
    assert np.all(area[downstream[cells]] > area[cells])
