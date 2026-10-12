"""The gate of the network criterion asks the source the computation reads.

The criterion cuts the network at ``tau * R * A`` and reads the mean recharge R
from the station forcing the run stores, and from the budget only when it stores
none. The gate used to ask the budget alone, so a run forced by stations and
holding no ``budget/recharge`` was refused for a term the computation never
read. Both now ask one predicate, ``has_recharge_source``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.results.derive.stream_extent import unavailable_reason_for_flow
from hydromodpy.results.derive.stream_network import (
    has_recharge_source,
    network_comparison_from_run,
)
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    NX,
    NY,
    cell,
    comparison_run,
)

FORCING_MM_D = pd.Series(
    [2.0, 1.0, 0.5], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
)
EDGES = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
MEAN_M_S = float(FORCING_MM_D.mean()) * factor_to_m_per_s("mm/day")


def _run(tmp_path, *, budget_recharge: bool, forcing: bool, dates: bool = True, policy=None):
    """A run with or without a recharge budget and with or without a station forcing.

    ``policy`` is what the ``budget/`` group of the store declares it kept,
    None for a group with no attributes.
    """
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    fields = {name: run.field(name) for name in ("release_flux", "topography", "recharge")}
    if not budget_recharge:
        del fields["recharge"]
    run.has_field = lambda variable, **_: variable in fields
    run.field = lambda variable, **_: fields[variable]
    run.periods = SimpleNamespace(edges=EDGES if dates else None)
    run.time_index = None
    if not (forcing or policy is not None):
        # A stand-in whose catalog opens no store: the budget is read step by step.
        return run
    path = tmp_path / "fields.zarr"
    SimulationZarr.create(path, n_cells=0, n_layers=1).close()
    writer = SimulationZarr(path)
    if forcing:
        writer.write_forcing_timeseries(
            "recharge", "STATION", FORCING_MM_D.index.values, FORCING_MM_D.to_numpy(), unit="mm/day"
        )
    if policy is not None:
        budget = writer.root.require_group("budget")
        budget.attrs.update({"policy": policy[0], "kept_terms": list(policy[1])})
    writer.close()
    run._catalog.open_zarr = lambda sim_id: SimulationZarr(path)
    return run


def test_a_station_forced_run_without_a_recharge_budget_passes_the_gate(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=True)

    assert has_recharge_source(run)
    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) is None


def test_a_station_forced_run_without_a_recharge_budget_computes_the_criterion(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=True)

    comparison = network_comparison_from_run(run, tau_specific_ratio=1e-4)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(MEAN_M_S, rel=1e-9)
    assert comparison.simulated.any()


def test_a_run_with_the_recharge_budget_passes_the_gate(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=True, forcing=False)

    assert has_recharge_source(run)
    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) is None
    assert network_comparison_from_run(run, tau_specific_ratio=1e-4).simulated.any()


def test_a_grid_forced_run_without_a_recharge_budget_is_refused(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=False)

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert not has_recharge_source(run)
    assert reason is not None
    assert "tau = 0.0001" in reason
    assert "persisted no recharge budget and no dated station recharge forcing" in reason
    with pytest.raises(ValueError, match="persisted no recharge budget"):
        network_comparison_from_run(run, tau_specific_ratio=1e-4)


def test_a_forcing_with_no_dates_to_place_it_on_is_not_a_source(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=True, dates=False)

    assert not has_recharge_source(run)
    assert unavailable_reason_for_flow(run, tau_specific_ratio=1e-4) is not None


def test_a_zero_ratio_asks_for_no_recharge(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=False)

    assert unavailable_reason_for_flow(run, tau_specific_ratio=0.0) is None
    comparison = network_comparison_from_run(run, tau_specific_ratio=0.0)
    assert comparison.geometry.mean_recharge_m_s == 0.0


def test_the_refusal_names_the_terms_a_consumers_run_left_out(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=False, policy=("consumers", ("drain",)))

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert "kept only the per-cell budget terms its consumers read (drain)" in reason
    assert "recharge" in reason.split("also needs")[1]
    assert "keep_per_cell_budget" in reason


def test_a_run_that_kept_the_whole_budget_gets_no_option_it_cannot_use(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=False, forcing=False, policy=("all", ("drain",)))

    reason = unavailable_reason_for_flow(run, tau_specific_ratio=1e-4)

    assert reason is not None
    assert "keep_per_cell_budget" not in reason


def test_a_run_without_release_flux_is_refused_without_the_retired_key(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=True, forcing=False, policy=("consumers", ("recharge",)))
    run.has_field = lambda variable, **_: variable in {"recharge", "topography"}

    reason = unavailable_reason_for_flow(run)

    assert reason.startswith("run has no per-cell release_flux")
    assert "[simulation.results.derived]" not in reason
    assert "keep_per_cell_budget" in reason


def test_the_budget_recharge_is_the_cell_rate_over_the_cell_area(tmp_path) -> None:
    run = _run(tmp_path, budget_recharge=True, forcing=False)
    area = float(run.mesh.vertices[:, 0].max() / NX) ** 2

    comparison = network_comparison_from_run(run, tau_specific_ratio=1e-4)

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(
        run.field("recharge")[0] / area, rel=1e-9
    )
