"""A stored transient run gives back the extents the network criterion scores.

The run is the monthly V-valley of :mod:`tests.unit.results._transient_network_run`:
the outlet flows every month, the two upper axis cells five months of twelve,
and the run covers 2001 and 2002 whole and 2003 up to March. Every count below
is written from that description, not read back from the code under test.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.stream_extent import parse_visible_flow
from hydromodpy.results.derive import stream_extent
from hydromodpy.results.derive.stream_extent import (
    block_flow_counts,
    flow_geometry_from_run,
    graph_role,
    network_extents_from_run,
    run_step_edges,
    scored_cells,
    unavailable_reason_for_extents,
    unavailable_reason_for_flow,
)
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from tests.unit.results._transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    N_STEPS,
    OUTLET,
    transient_run,
)


def _cells(mask: np.ndarray) -> list[int]:
    return sorted(int(index) for index in np.flatnonzero(mask))


class TestTheTimeAxis:
    def test_the_first_bound_is_the_start_the_catalog_recorded(self) -> None:
        edges = run_step_edges(transient_run())

        assert edges.size == N_STEPS + 1
        assert edges[0] == np.datetime64("2001-01-01")
        assert edges[1] == np.datetime64("2001-01-31")

    def test_a_zoned_start_keeps_its_wall_clock(self) -> None:
        """Converted to UTC, a start west of Greenwich would cut the first year."""
        run = transient_run()
        run._load_row = lambda: {"period_start": pd.Timestamp("2001-01-01", tz="America/Cayenne")}

        edges = run_step_edges(run)

        assert edges[0] == np.datetime64("2001-01-01")
        assert network_extents_from_run(run).years.years == (2001, 2002)

    def test_without_a_recorded_start_the_first_period_is_as_long_as_the_second(self) -> None:
        edges = run_step_edges(transient_run(with_period_start=False))

        assert edges[1] - edges[0] == edges[2] - edges[1]

    def test_a_run_without_a_time_axis_has_no_bounds(self) -> None:
        assert run_step_edges(transient_run(with_time=False)) is None


class TestTheExtents:
    def test_the_complete_years_are_scored_and_the_cut_one_left_out(self) -> None:
        extents = network_extents_from_run(transient_run())

        assert extents.years.years == (2001, 2002)
        assert extents.years.incomplete == (2003,)
        assert extents.counts.n_steps.tolist() == [12, 12]

    def test_a_scoring_window_leaves_the_spin_up_year_out(self) -> None:
        extents = network_extents_from_run(
            transient_run(), scoring_window=(pd.Timestamp("2002-01-01"), None)
        )

        assert extents.years.years == (2002,)
        assert extents.years.outside_window == (2001,)
        assert extents.counts.n_steps.tolist() == [12]
        assert extents.masks.n_years_required == 1

    def test_a_window_holding_no_complete_year_is_refused_by_name(self) -> None:
        window = (pd.Timestamp("2001-03-01"), pd.Timestamp("2002-06-30"))

        reason = unavailable_reason_for_extents(transient_run(), scoring_window=window)

        assert reason is not None
        assert "leaves out 2001, 2002" in reason
        with pytest.raises(ValueError, match="scoring window holds no complete"):
            network_extents_from_run(transient_run(), scoring_window=window)

    def test_each_cell_flows_the_timesteps_its_releases_reach_it(self) -> None:
        counts = network_extents_from_run(transient_run()).counts.flowing

        assert counts[:, [OUTLET, MIDDLE, HEAD, HILLSLOPE]].tolist() == [[12, 5, 5, 0]] * 2

    def test_the_maximal_extent_holds_every_flowing_cell_the_minimal_the_perennial_one(
        self,
    ) -> None:
        extents = network_extents_from_run(transient_run())

        assert _cells(extents.simulated("maximal")) == [OUTLET, MIDDLE, HEAD]
        assert _cells(extents.simulated("minimal")) == [OUTLET]
        assert _cells(extents.simulated("minimal", year=2002)) == [OUTLET]

    def test_the_rules_are_counted_in_timesteps(self) -> None:
        """Five flowing steps of twelve pass a maximal rule of five, not one of six."""
        five = network_extents_from_run(transient_run(), maximal_flowing_steps=5)
        six = network_extents_from_run(transient_run(), maximal_flowing_steps=6)

        assert _cells(five.simulated("maximal")) == [OUTLET, MIDDLE, HEAD]
        assert _cells(six.simulated("maximal")) == [OUTLET]

    def test_the_maximal_map_is_the_union_of_the_two_maps(self) -> None:
        extents = network_extents_from_run(transient_run())

        assert _cells(extents.observed("maximal")) == [OUTLET, MIDDLE, HEAD]
        assert _cells(extents.observed("minimal")) == [OUTLET, MIDDLE]
        assert extents.frac_minimal_outside_maximal == pytest.approx(0.0)

    def test_each_bound_is_partitioned_against_its_own_map(self) -> None:
        extents = network_extents_from_run(transient_run())

        assert extents.supports("minimal").counts == {
            "n_valid": 1.0,
            "n_excess": 0.0,
            "n_missing": 1.0,
        }
        assert extents.supports("maximal").counts == {
            "n_valid": 3.0,
            "n_excess": 0.0,
            "n_missing": 0.0,
        }

    def test_a_visible_flow_above_the_summer_release_dries_the_outlet_in_summer(self) -> None:
        """Two litres per second pass one litre per second, not five."""
        default = network_extents_from_run(transient_run())
        strict = network_extents_from_run(transient_run(), visible_flow="5 L/s")

        assert default.counts.flowing[0, OUTLET] == 12
        assert strict.counts.flowing[0, OUTLET] == 5
        assert _cells(strict.simulated("minimal")) == []

    def test_a_water_body_leaves_the_share_outside_as_it_leaves_the_counts(
        self, monkeypatch
    ) -> None:
        """A lake on the middle cell, which the maximal map misses.

        The minimal map holds the outlet and the middle cell. The lake takes
        the middle cell out of every scored quantity, so the one minimal cell
        left, the outlet, is covered by the maximal map.
        """
        build = stream_extent.flow_geometry_from_run

        def with_lake(sim, *, role, **kwargs):
            geometry = build(sim, role=role, **kwargs)
            if role != stream_extent.MAXIMAL_ROLE:
                return geometry
            lake = np.zeros_like(geometry.catchment, dtype=bool)
            lake[MIDDLE] = True
            observed = np.zeros_like(lake)
            observed[[OUTLET, HEAD]] = True
            return dataclasses.replace(geometry, observed=observed, excluded=lake)

        monkeypatch.setattr(stream_extent, "flow_geometry_from_run", with_lake)
        extents = network_extents_from_run(transient_run())

        assert not scored_cells(extents.geometry)[MIDDLE]
        assert extents.frac_minimal_outside_maximal == pytest.approx(0.0)
        assert np.array_equal(extents.supports("minimal").keep, scored_cells(extents.geometry))
        assert extents.supports("minimal").counts["n_missing"] == 0.0

    def test_a_run_with_one_map_has_no_minimal_map(self) -> None:
        extents = network_extents_from_run(transient_run(with_minimal=False))

        assert extents.minimal_observed is None
        assert np.isnan(extents.frac_minimal_outside_maximal)
        with pytest.raises(ValueError, match="no minimal map"):
            extents.observed("minimal")

    def test_rules_the_years_cannot_hold_are_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="maximal_flowing_steps = 13"):
            network_extents_from_run(transient_run(), maximal_flowing_steps=13)


class TestOneDefinitionOfFlowing:
    def test_the_counts_are_the_network_the_criterion_draws_at_each_step(self) -> None:
        """With no visible flow, flowing is the simulated network of the comparison."""
        run = transient_run()
        geometry = flow_geometry_from_run(run)
        for step in (0, 5):
            counts = block_flow_counts(
                run, geometry, [np.asarray([step])], visible_flow="0 L/s"
            ).flowing[0]
            comparison = network_comparison_from_run(run, timestep=step)
            network = comparison.simulated
            assert _cells(counts.astype(bool) & comparison.supports.keep) == _cells(network)

    def test_a_small_chunk_counts_the_same(self) -> None:
        run = transient_run()
        geometry = flow_geometry_from_run(run)
        blocks = [np.arange(12), np.arange(12, 24)]
        whole = block_flow_counts(run, geometry, blocks)
        chunked = block_flow_counts(run, geometry, blocks, chunk_elements=1)

        np.testing.assert_array_equal(whole.flowing, chunked.flowing)
        assert whole.visible_flow == parse_visible_flow("1 L/s")

    def test_the_seepage_threshold_of_the_criterion_applies(self) -> None:
        """A threshold of 0.1 m3/s silences the summer release and keeps the winter one."""
        run = transient_run()
        geometry = flow_geometry_from_run(run, tau_specific_ratio=1.0e3)
        counts = block_flow_counts(run, geometry, [np.arange(12)]).flowing[0]

        assert counts[OUTLET] == 5


class TestRefusals:
    def test_a_run_with_only_a_generated_network_still_counts(self) -> None:
        run = transient_run(roles=("generated",))

        assert graph_role(run) == "generated"
        assert unavailable_reason_for_flow(run) is None

    def test_a_run_with_no_network_is_told_why(self) -> None:
        reason = unavailable_reason_for_flow(transient_run(roles=()))

        assert reason is not None
        assert "'reference'" in reason

    def test_a_steady_run_has_no_extents(self) -> None:
        reason = unavailable_reason_for_extents(transient_run(n_steps=1))

        assert reason is not None
        assert "steady" in reason

    def test_a_run_with_one_map_is_told_it_lacks_the_minimal_one(self) -> None:
        reason = unavailable_reason_for_extents(transient_run(with_minimal=False))

        assert reason is not None
        assert "reference_permanent" in reason

    def test_a_run_shorter_than_a_calendar_year_is_told_so(self) -> None:
        reason = unavailable_reason_for_extents(transient_run(n_steps=6))

        assert reason is not None
        assert "no complete calendar year" in reason
