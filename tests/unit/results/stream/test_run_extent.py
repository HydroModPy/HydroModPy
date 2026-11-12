"""Extents of the observed stream network read from a monthly run.

The run is the monthly V-valley of ``tests._helpers.transient_network_run``. The
outlet flows every month, the two upper axis cells five months of twelve, and the
run covers 2001 and 2002 whole and 2003 up to March. Every count is written from
that description, not read back from the code under test.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from hydromodpy.catchment.stream_network.geometry import scored_cells
from hydromodpy.results.derive.stream_network import run_extent
from hydromodpy.results.derive.stream_network.run_extent import (
    network_extents_from_run,
    run_step_edges,
    unavailable_reason_for_extents,
    unavailable_reason_for_flow,
)
from tests._helpers.transient_network_run import HEAD, MIDDLE, OUTLET, transient_run


def cells_of(mask: np.ndarray) -> list[int]:
    return sorted(int(index) for index in np.flatnonzero(mask))


def test_a_zoned_start_keeps_its_wall_clock() -> None:
    # Converted to UTC, a start west of Greenwich would cut the first year.
    run = transient_run()
    run._load_row = lambda: {"period_start": pd.Timestamp("2001-01-01", tz="America/Cayenne")}

    edges = run_step_edges(run)

    assert edges[0] == np.datetime64("2001-01-01")
    assert network_extents_from_run(run).years.years == (2001, 2002)


def test_without_a_recorded_start_the_first_period_is_as_long_as_the_second() -> None:
    edges = run_step_edges(transient_run(with_period_start=False))

    assert edges[1] - edges[0] == edges[2] - edges[1]


def test_a_run_without_a_time_axis_has_no_bounds() -> None:
    assert run_step_edges(transient_run(with_time=False)) is None


def test_the_maximal_map_is_the_union_of_the_two_maps() -> None:
    extents = network_extents_from_run(transient_run())

    assert cells_of(extents.observed("maximal")) == [OUTLET, MIDDLE, HEAD]
    assert cells_of(extents.observed("minimal")) == [OUTLET, MIDDLE]
    assert extents.frac_minimal_outside_maximal == pytest.approx(0.0)


def test_a_water_body_leaves_the_share_outside_as_it_leaves_the_counts(monkeypatch) -> None:
    # A lake on the middle cell, which the maximal map misses. The minimal map holds
    # the outlet and the middle cell. The lake takes the middle cell out of every
    # scored quantity, so the one minimal cell left, the outlet, is covered by the
    # maximal map.
    build = run_extent.flow_geometry_from_run

    def with_lake(sim, *, role, **kwargs):
        geometry = build(sim, role=role, **kwargs)
        if role != run_extent.MAXIMAL_ROLE:
            return geometry
        lake = np.zeros_like(geometry.catchment, dtype=bool)
        lake[MIDDLE] = True
        observed = np.zeros_like(lake)
        observed[[OUTLET, HEAD]] = True
        return dataclasses.replace(geometry, observed=observed, excluded=lake)

    monkeypatch.setattr(run_extent, "flow_geometry_from_run", with_lake)
    extents = network_extents_from_run(transient_run())

    assert not scored_cells(extents.geometry)[MIDDLE]
    assert extents.frac_minimal_outside_maximal == pytest.approx(0.0)
    assert np.array_equal(extents.supports("minimal").keep, scored_cells(extents.geometry))
    assert extents.supports("minimal").counts["n_missing"] == 0.0


def test_a_run_with_one_map_has_no_minimal_map() -> None:
    extents = network_extents_from_run(transient_run(with_minimal=False))

    assert extents.minimal_observed is None
    assert np.isnan(extents.frac_minimal_outside_maximal)
    with pytest.raises(ValueError, match="no minimal map"):
        extents.observed("minimal")


UNAVAILABLE = [
    pytest.param(
        unavailable_reason_for_flow, {"roles": ()}, "'reference'", id="no network on the run"
    ),
    pytest.param(unavailable_reason_for_extents, {"n_steps": 1}, "steady", id="steady run"),
    pytest.param(
        unavailable_reason_for_extents,
        {"with_minimal": False},
        "reference_permanent",
        id="no minimal map",
    ),
    pytest.param(
        unavailable_reason_for_extents,
        {"n_steps": 6},
        "no complete calendar year",
        id="shorter than a year",
    ),
]


@pytest.mark.parametrize(("reason_of", "run_kwargs", "fragment"), UNAVAILABLE)
def test_unavailable_reasons(reason_of, run_kwargs, fragment) -> None:
    reason = reason_of(transient_run(**run_kwargs))

    assert reason is not None
    assert fragment in reason


def test_a_window_holding_no_complete_year_is_refused_by_name() -> None:
    window = (pd.Timestamp("2001-03-01"), pd.Timestamp("2002-06-30"))

    reason = unavailable_reason_for_extents(transient_run(), window=window)

    assert reason is not None
    assert "leaves out 2001, 2002" in reason
    with pytest.raises(ValueError, match="scoring window holds no complete"):
        network_extents_from_run(transient_run(), window=window)


def test_a_rule_the_years_cannot_hold_is_refused() -> None:
    with pytest.raises(ValueError, match="maximal rule of 13 timestep"):
        network_extents_from_run(transient_run(), maximal_flowing_duration="13 months")
