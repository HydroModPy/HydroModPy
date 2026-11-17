"""Extents of the observed stream network read from a monthly run.

The run is the monthly V-valley of ``tests._helpers.transient_network_run``. The
outlet flows every month, the two upper axis cells five months of twelve, and the
run covers 2001 and 2002 whole and 2003 up to March. Every count is written from
that description, not read back from the code under test.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.catchment.stream_network.geometry import scored_cells
from hydromodpy.results.derive.stream_network import run_extent
from hydromodpy.results.derive.stream_network.comparison import (
    no_recharge_reason,
    no_release_flux_reason,
)
from hydromodpy.results.derive.stream_network.run_extent import (
    _release_rows,
    flow_geometry_from_run,
    flowing_share,
    network_extents_from_run,
    run_step_days,
    run_step_edges,
    unavailable_reason_for_extents,
    unavailable_reason_for_flow,
)
from tests._helpers.transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    N_STEPS,
    OUTLET,
    WINTER_MONTHS,
    transient_run,
)


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


def _without_recharge(run):
    """Return ``run`` whose descent kept no mean recharge."""
    kept = run.descent
    run.descent = SimpleNamespace(open_water=kept.open_water, criterion_recharge=lambda: None)
    return run


def test_a_seepage_threshold_needs_the_recharge_the_run_kept() -> None:
    run = _without_recharge(transient_run())

    assert unavailable_reason_for_flow(run, tau_specific_ratio=0.5) == no_recharge_reason()
    assert unavailable_reason_for_flow(run, tau_specific_ratio=0.0) is None


def test_a_run_without_release_flux_gives_the_flux_reason() -> None:
    run = transient_run()
    run.has_field = lambda variable, **_: False

    assert unavailable_reason_for_flow(run) == no_release_flux_reason(run)


def test_extents_refuse_a_run_without_the_maximal_map() -> None:
    run = transient_run(roles=("generated",))

    reason = unavailable_reason_for_extents(run, require_minimal=False)

    assert reason is not None
    assert "no 'reference' hydrographic network" in reason


def test_extents_pass_on_the_reason_the_flow_cannot_be_rebuilt() -> None:
    run = _without_recharge(transient_run())

    reason = unavailable_reason_for_extents(run, tau_specific_ratio=0.5)

    assert reason == no_recharge_reason()


def test_extents_refuse_a_run_without_a_time_axis_by_name() -> None:
    run = transient_run(with_time=False)

    assert "no time axis" in unavailable_reason_for_extents(run)
    with pytest.raises(ValueError, match="carries no time axis"):
        network_extents_from_run(run)


def test_extents_refuse_a_run_that_sealed_no_timestep() -> None:
    run = transient_run()
    run.config_snapshot = {}

    assert "sealed no timestep" in unavailable_reason_for_extents(run)
    with pytest.raises(ValueError, match="sealed no timestep"):
        network_extents_from_run(run)


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {"simulation": None},
        {"simulation": {"time": None}},
        {"simulation": {"time": {"step_value": None}}},
        {"simulation": {"time": {"step_value": "soon", "step_unit": "fortnight"}}},
    ],
)
def test_a_step_that_cannot_be_read_gives_no_duration(snapshot) -> None:
    run = transient_run()
    run.config_snapshot = snapshot

    assert run_step_days(run) is None


def test_the_step_of_a_month_is_its_nominal_length() -> None:
    assert run_step_days(transient_run()) == pytest.approx(30.4375)


def test_a_run_without_timesteps_has_no_bounds() -> None:
    assert run_step_edges(transient_run(n_steps=0)) is None


def test_a_time_axis_shorter_than_the_run_has_no_bounds() -> None:
    run = transient_run()
    run.n_timesteps = N_STEPS + 5

    assert run_step_edges(run) is None


def test_a_zone_aware_axis_is_read_on_its_wall_clock() -> None:
    run = transient_run()
    run.index = run.index.tz_localize("Europe/Paris")

    assert run_step_edges(run)[0] == np.datetime64("2001-01-01")


def test_a_single_step_without_a_start_has_no_bounds() -> None:
    assert run_step_edges(transient_run(n_steps=1, with_period_start=False)) is None


def test_a_run_without_a_row_loader_takes_the_period_of_its_first_steps() -> None:
    run = transient_run()
    del run._load_row

    edges = run_step_edges(run)

    assert edges[1] - edges[0] == edges[2] - edges[1]


def test_a_graph_cannot_be_rebuilt_on_a_run_without_a_network() -> None:
    run = transient_run(roles=())

    with pytest.raises(ValueError, match="flowing cells unavailable.*neither"):
        flow_geometry_from_run(run)


def test_the_flowing_share_is_the_fraction_of_timesteps_each_cell_flows() -> None:
    run = transient_run()
    geometry = flow_geometry_from_run(run, role="reference")

    share = flowing_share(run, geometry)

    winter = sum(1 for m in range(N_STEPS) if ((m % 12) + 1) in WINTER_MONTHS)
    assert share[OUTLET] == pytest.approx(1.0)
    assert share[HEAD] == pytest.approx(winter / N_STEPS)
    assert share[HILLSLOPE] == 0.0


def test_no_timestep_reads_an_empty_release_stack() -> None:
    rows = _release_rows(transient_run(), np.array([], dtype=int), 15)

    assert rows.shape == (0, 15)


def test_a_release_written_for_another_mesh_is_refused() -> None:
    with pytest.raises(ValueError, match="holds 15 cells at timestep 0 and the mesh holds 7"):
        _release_rows(transient_run(), np.array([0]), 7)


def test_a_year_of_the_extents_gives_the_simulated_cells_of_that_year() -> None:
    extents = network_extents_from_run(transient_run())

    year_cells = cells_of(extents.simulated("maximal", year=2001))

    assert year_cells == [OUTLET, MIDDLE, HEAD]


def test_flow_passes_on_the_reason_the_comparison_cannot_be_rebuilt() -> None:
    run = transient_run()
    run.mesh.crs = None

    assert "no projected CRS" in unavailable_reason_for_flow(run)
