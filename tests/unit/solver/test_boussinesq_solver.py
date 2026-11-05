from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.initial_conditions import (
    FlowICCustom,
    FlowICSteadyState,
    FlowInitialConditions,
)
from hydromodpy.results.storage.run_store import SOLVER_DIAGNOSTICS_DIRNAME
from hydromodpy.solver.boussinesq.adapters import flow as flow_adapter
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.drivers.transient import (
    _resolve_period_lengths_seconds,
)
from hydromodpy.solver.boussinesq.export_payload import build_state_history_export_payload
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver
from hydromodpy.solver.boussinesq.jacobian.common import (
    drainage_diagonal_derivative,
)
from hydromodpy.solver.boussinesq.runtimes.vi_bounds import variable_bounds
from hydromodpy.solver.steady_initial_conditions import steady_flow_copy_for_initialization
from tests._helpers.boussinesq_mesh_doubles import _MiniMesh

# Boussinesq lumped budget: always written, MODFLOW in/out orientation.


class _RecordingStore:
    """Minimal store capturing the lumped budget rows."""

    def __init__(self) -> None:
        self.budgets: list[dict] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets = records


def _components() -> dict[str, np.ndarray]:
    return {
        "recharge": np.array([[1.0, 2.0]]),
        "drain": np.array([[-0.5, 0.0]]),
        "well": np.array([[-0.25, 0.75]]),
        "surface_excess": np.array([[0.0, -0.125]]),
        "constant_head": np.array([[3.0, -4.0]]),
    }


def _by_component(records: list[dict]) -> dict[str, dict]:
    return {record["component"]: record for record in records}


def test_budget_components_convert_rates_to_fluxes() -> None:
    payload = {
        "recharge_rate_history_m_s": np.array([[1e-8, 2e-8]]),
        "saturation_excess_history_m_s": np.array([[0.0, 3e-8]]),
        "drainage_flux_history_m3_s": np.array([[0.5, 0.0]]),
    }
    components = BoussinesqOutputAdapter._budget_components(
        payload,
        n_timesteps=1,
        n_cells=2,
        cell_area_m2=np.array([10.0, 20.0]),
    )

    assert set(components) == {"recharge", "drain", "surface_excess"}
    assert components["recharge"] == pytest.approx(np.array([[1e-7, 4e-7]]))
    assert components["surface_excess"] == pytest.approx(np.array([[0.0, -6e-7]]))
    assert components["drain"] == pytest.approx(np.array([[-0.5, 0.0]]))


def test_what_leaves_the_aquifer_lands_in_flux_out() -> None:
    store = _RecordingStore()

    BoussinesqOutputAdapter._write_budget_table("sim", store, _components(), n_timesteps=1)

    rows = _by_component(store.budgets)
    # Drain and surface excess only ever leave the aquifer.
    assert rows["drain"]["flux_in"] == pytest.approx(0.0)
    assert rows["drain"]["flux_out"] == pytest.approx(0.5)
    assert rows["surface_excess"]["flux_out"] == pytest.approx(0.125)
    # A prescribed-head cell that feeds the aquifer carries a positive flux.
    assert rows["constant_head"]["flux_in"] == pytest.approx(3.0)
    assert rows["constant_head"]["flux_out"] == pytest.approx(4.0)


def test_source_components_keep_the_modflow_orientation() -> None:
    store = _RecordingStore()

    BoussinesqOutputAdapter._write_budget_table("sim", store, _components(), n_timesteps=1)

    rows = _by_component(store.budgets)
    assert rows["recharge"]["flux_in"] == pytest.approx(3.0)
    assert rows["recharge"]["flux_out"] == pytest.approx(0.0)
    # Well flux is signed: injection enters, pumping leaves.
    assert rows["well"]["flux_in"] == pytest.approx(0.75)
    assert rows["well"]["flux_out"] == pytest.approx(0.25)
    assert all(record["unit"] == "m3 s-1" for record in store.budgets)


def test_every_timestep_gets_one_row_per_component() -> None:
    store = _RecordingStore()
    components = {"drain": np.array([[-1.0], [-2.0], [-3.0]])}

    BoussinesqOutputAdapter._write_budget_table("sim", store, components, n_timesteps=3)

    assert [record["timestep"] for record in store.budgets] == [0, 1, 2]
    assert [record["flux_out"] for record in store.budgets] == pytest.approx([1.0, 2.0, 3.0])


# The VI diagnostics of a Boussinesq run land in ``<run>/exports/solver_diagnostics/``.
#
# They used to be written beside the solver files, in the scratch the seal of a
# completed run removes. They now go to the run directory; a run without a store
# writes none.


def _model(tmp_path: Path) -> SimpleNamespace:
    solver_dir = tmp_path / "scratch" / "solver"
    solver_dir.mkdir(parents=True)
    (solver_dir / "_boussinesq_summary.json").write_text(
        json.dumps({"runtime_engine": "petsc"}), encoding="utf-8"
    )
    return SimpleNamespace(full_path=str(solver_dir))


def test_the_diagnostics_are_written_into_the_exports_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []
    monkeypatch.setattr(
        flow_adapter, "write_vi_obstacle_diagnostic_files", lambda d, s: written.append(d)
    )
    monkeypatch.setattr(
        flow_adapter, "write_ts_vi_obstacle_diagnostic_files", lambda d, s: written.append(d)
    )
    run_dir = tmp_path / "runs" / "nancon"
    store = SimpleNamespace(solver_diagnostics_dir=run_dir / "exports" / SOLVER_DIAGNOSTICS_DIRNAME)

    flow_adapter.BoussinesqFlowAdapter._persist_obstacle_diagnostics(
        SimpleNamespace(store=store), _model(tmp_path)
    )

    assert written == [run_dir / "exports" / "solver_diagnostics"] * 2


def test_a_run_without_a_store_writes_no_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []
    monkeypatch.setattr(
        flow_adapter, "write_vi_obstacle_diagnostic_files", lambda d, s: written.append(d)
    )

    flow_adapter.BoussinesqFlowAdapter._persist_obstacle_diagnostics(
        SimpleNamespace(store=None), _model(tmp_path)
    )

    assert written == []
    assert not (tmp_path / "scratch" / "solver" / "solver_diagnostics").exists()


def test_the_store_names_the_folder_under_the_exports_of_the_run(tmp_path: Path) -> None:
    from hydromodpy.results.storage.run_store import RunStore

    store = RunStore.__new__(RunStore)
    store._run_dir = tmp_path / "runs" / "nancon"  # noqa: SLF001 - path only, no facts needed

    assert store.solver_diagnostics_dir == tmp_path / "runs" / "nancon" / "exports" / (
        "solver_diagnostics"
    )


def test_drainage_derivative_is_active_at_top_contact() -> None:
    mesh = _MiniMesh(
        z_top_m=np.asarray([2.0, 2.0, 2.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0, 1.0, 1.0], dtype=float),
        cell_area_m2=np.asarray([10.0, 10.0, 10.0], dtype=float),
    )

    derivative = drainage_diagonal_derivative(
        mesh,
        head_m=np.asarray([1.99, 2.0, 2.01], dtype=float),
        drainage_conductance_m2_s=0.2,
    )

    np.testing.assert_allclose(derivative, np.asarray([0.0, 0.2, 0.2]))


def test_state_history_export_payload_includes_solver_residual_history() -> None:
    state = BoussinesqState.from_runtime(
        head_m=np.asarray([10.0]),
        saturated_thickness_m=np.asarray([1.0]),
        residual_history_m3_s=np.asarray([[0.0], [0.12]]),
    )

    payload = build_state_history_export_payload(state)

    np.testing.assert_allclose(payload["residual_history_m3_s"], [[0.0], [0.12]])


def test_boussinesq_steady_state_initial_condition_uses_top_as_initial_guess() -> None:
    mesh = SimpleNamespace(
        n_cells=3,
        z_top_m=np.asarray([10.0, 11.0, 12.0], dtype=float),
        z_bottom_m=np.asarray([1.0, 1.0, 1.0], dtype=float),
    )
    flow = SimpleNamespace(initial_conditions=FlowInitialConditions(h=FlowICSteadyState(id="h")))
    resolver = BoussinesqForcingResolver(mesh=mesh, flow=flow, time_grid=None)

    head = resolver.resolve_initial_head_field()

    np.testing.assert_allclose(head, mesh.z_top_m)


def test_boussinesq_initial_state_records_head_bounds_summary(tmp_path) -> None:
    mesh = SimpleNamespace(
        n_cells=3,
        z_top_m=np.asarray([5.0, 5.0, 5.0], dtype=float),
        z_bottom_m=np.asarray([1.0, 1.0, 1.0], dtype=float),
    )
    flow = SimpleNamespace(
        initial_conditions=FlowInitialConditions(h=FlowICCustom(id="h", value=6.0, units="m"))
    )
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=mesh,
        flow=flow,
        domain=SimpleNamespace(),
        time_grid=None,
        model_folder=tmp_path,
        model_name="bounds_summary",
    )

    state = solver._build_initial_state()

    np.testing.assert_allclose(state.head_m, np.full(3, 6.0))
    bounds = solver.runtime_summary["initial_head_bounds"]
    assert bounds["above_top_count"] == 3
    assert bounds["below_bottom_count"] == 0
    assert bounds["max_above_top_m"] == 1.0
    assert bounds["within_bounds"] is False


def test_petsc_ts_vi_initialization_uses_regularized_steady_solve() -> None:
    flow = SimpleNamespace(
        flow_regime="transient",
        runtime_backend="petsc",
        surface_interaction_model="ts_vi_obstacle",
        initial_conditions=FlowInitialConditions(h=FlowICSteadyState(id="h")),
        sinks_sources={},
    )

    steady_flow = steady_flow_copy_for_initialization(flow)

    assert steady_flow.flow_regime == "steady"
    assert steady_flow.runtime_backend == "petsc"
    assert steady_flow.surface_interaction_model == "regularized_partition"
    assert steady_flow.initial_conditions.h.kind == "top"


def test_petsc_ts_vi_initialization_reads_surface_model_from_config() -> None:
    flow = SimpleNamespace(
        flow_regime="transient",
        runtime_backend="petsc",
        config=FlowConfig(
            flow_regime="transient",
            runtime={"backend": "petsc", "surface_interaction_model": "ts_vi_obstacle"},
        ),
        initial_conditions=FlowInitialConditions(h=FlowICSteadyState(id="h")),
        sinks_sources={},
    )

    steady_flow = steady_flow_copy_for_initialization(flow)

    assert steady_flow.surface_interaction_model == "regularized_partition"
    assert steady_flow.config.runtime.surface_interaction_model == "regularized_partition"
    assert steady_flow.config.ic.h.kind == "top"


def test_resolve_period_lengths_seconds_uses_positive_grid_lengths() -> None:
    grid = SimpleNamespace(period_lengths_seconds=(10.0, 20.0), boundaries=())

    assert _resolve_period_lengths_seconds(grid) == (10.0, 20.0)


def test_resolve_period_lengths_seconds_falls_back_to_boundaries_for_zero_lengths() -> None:
    start = datetime(2020, 1, 1)
    grid = SimpleNamespace(
        period_lengths_seconds=(0.0, 0.0),
        boundaries=(start, start + timedelta(days=1), start + timedelta(days=3)),
    )

    assert _resolve_period_lengths_seconds(grid) == (86400.0, 172800.0)


def test_resolve_period_lengths_seconds_rejects_zero_lengths_without_boundaries() -> None:
    grid = SimpleNamespace(period_lengths_seconds=(0.0,), boundaries=())

    with pytest.raises(ValueError, match="non-positive period lengths"):
        _resolve_period_lengths_seconds(grid)


def test_vi_bounds_relax_upper_obstacle_for_explicit_cauchy_drainage() -> None:
    mesh = _MiniMesh(
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 3.0], dtype=float),
    )

    _, upper_without_drainage, _ = variable_bounds(mesh, None)
    _, upper_with_drainage, _ = variable_bounds(
        mesh,
        None,
        drainage_conductance_m2_s=0.2,
    )

    np.testing.assert_allclose(upper_without_drainage, mesh.z_top_m)
    assert np.all(upper_with_drainage > 1.0e20)


def test_vi_bounds_keep_upper_obstacle_when_drainage_conductance_is_zero() -> None:
    mesh = _MiniMesh(
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 3.0], dtype=float),
    )

    _, upper_with_zero_drainage, _ = variable_bounds(
        mesh,
        None,
        drainage_conductance_m2_s=0.0,
    )

    np.testing.assert_allclose(upper_with_zero_drainage, mesh.z_top_m)


def test_vi_bounds_keep_prescribed_heads_fixed_with_relaxed_drainage() -> None:
    mesh = _MiniMesh(
        z_bottom_m=np.asarray([0.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 3.0], dtype=float),
    )

    lower, upper, mask = variable_bounds(
        mesh,
        np.asarray([np.nan, 2.5], dtype=float),
        drainage_conductance_m2_s=0.2,
    )

    np.testing.assert_allclose(lower, np.asarray([0.0, 2.5]))
    assert upper[0] > 1.0e20
    assert upper[1] == pytest.approx(2.5)
    np.testing.assert_array_equal(mask, np.asarray([False, True]))
