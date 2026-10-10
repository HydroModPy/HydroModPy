"""The Boussinesq drain derives its conductance with solver.drain_bed_thickness_m.

When no drainage conductance is declared, both MODFLOW backends use
``C = K * cell_area / drain_bed_thickness_m``. Boussinesq used ``K * cell_area``,
which agrees only at the default of 1 m. The same file then gave a different
drainage, and a different calibrated K, on Boussinesq.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.state.run_state import RunState
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.adapters import flow as flow_adapter_module
from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.assembly import assemble_transient_residual
from hydromodpy.solver.boussinesq.assembly.fluxes import (
    derived_drain_conductance_m2_s,
    drainage_outflow_from_head,
)
from hydromodpy.solver.boussinesq.jacobian.common import drainage_diagonal_derivative
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.modflow6.builders.boundary_conditions import (
    build_drain_stress_period_data,
)

BED_M = 0.25
K_M_S = np.asarray([1.0e-5, 4.0e-5, 2.0e-4])
AREA_M2 = np.asarray([50.0, 120.0, 300.0])
TOP_M = np.asarray([10.0, 10.5, 11.0])


def _line_mesh(*, drain_bed_thickness_m: float = BED_M) -> BoussinesqMesh:
    """Three cells in a row, of unequal areas and conductivities."""
    return BoussinesqMesh(
        bundle_dir=Path("."),
        cell_ids=np.asarray([0, 1, 2]),
        node_ids=np.asarray([0, 1, 2, 3]),
        node_x_m=np.asarray([0.0, 1.0, 2.0, 3.0]),
        node_y_m=np.zeros(4),
        cell_node_ids=((0, 1, 2), (1, 2, 3), (2, 3, 0)),
        cell_centroid_x_m=np.asarray([0.5, 1.5, 2.5]),
        cell_centroid_y_m=np.zeros(3),
        cell_area_m2=AREA_M2.copy(),
        z_top_m=TOP_M.copy(),
        z_bottom_m=np.zeros(3),
        hydraulic_conductivity_m_s=K_M_S.copy(),
        storage_coefficient=np.full(3, 0.1),
        edge_ids=np.asarray([0, 1]),
        edge_node_a=np.asarray([1, 2]),
        edge_node_b=np.asarray([2, 3]),
        edge_cell_a=np.asarray([0, 1]),
        edge_cell_b=np.asarray([1, 2]),
        edge_length_m=np.asarray([10.0, 10.0]),
        edge_distance_m=np.asarray([10.0, 15.0]),
        edge_midpoint_distance_to_cell_a_m=np.asarray([5.0, 7.0]),
        edge_midpoint_distance_to_cell_b_m=np.asarray([5.0, 8.0]),
        edge_midpoint_x_m=np.asarray([1.0, 2.0]),
        edge_midpoint_y_m=np.zeros(2),
        edge_kind=("internal", "internal"),
        edge_is_river=np.zeros(2, dtype=bool),
        cell_index_by_id={0: 0, 1: 1, 2: 2},
        node_index_by_id={0: 0, 1: 1, 2: 2, 3: 3},
        drain_bed_thickness_m=drain_bed_thickness_m,
    )


def _mf6_fallback_conductance(*, bed_thickness: float) -> np.ndarray:
    """Return the DRN conductance the MF6 builder writes for the same three cells."""
    model = SimpleNamespace(
        dem_mask=np.zeros(3, dtype=bool),
        nper=1,
        ncpl=3,
        hk=K_M_S.reshape(1, 3),
        sink_fill=False,
        sink=None,
        drain_band_depth_m=0.0,
        drain_bed_thickness_m=bed_thickness,
        drain_conductance_floor_m2_s=1e-12,
    )
    spd = build_drain_stress_period_data(
        model,
        solver_mesh=SimpleNamespace(top=TOP_M, cell_areas=lambda: AREA_M2),
        drainage_cond_series=np.asarray([0.0]),
        ocean_support_mask=np.zeros(3, dtype=bool),
        stream_support_mask=np.zeros(3, dtype=bool),
    )
    return np.asarray([row[3] for row in spd[0]])


def test_the_derived_conductance_is_k_area_over_the_bed_as_on_mf6() -> None:
    mesh = _line_mesh()
    derived = derived_drain_conductance_m2_s(mesh)

    np.testing.assert_allclose(derived, K_M_S * AREA_M2 / BED_M, rtol=1e-15)
    np.testing.assert_allclose(derived, [2.0e-3, 1.92e-2, 0.24], rtol=1e-12)
    np.testing.assert_allclose(derived, _mf6_fallback_conductance(bed_thickness=BED_M), rtol=1e-15)


@pytest.mark.parametrize("undeclared", [0.0, -1.0])
def test_an_undeclared_conductance_drains_through_the_bed(undeclared: float) -> None:
    """Zero or negative, the 0.0 a left-out value loads as: C is derived, never closed."""
    mesh = _line_mesh()
    head = TOP_M + np.asarray([-0.5, 0.3, 0.05])

    flux = drainage_outflow_from_head(mesh, head, drainage_conductance_m2_s=undeclared)
    tangent = drainage_diagonal_derivative(mesh, head, drainage_conductance_m2_s=undeclared)

    mf6 = _mf6_fallback_conductance(bed_thickness=BED_M)
    np.testing.assert_allclose(flux, mf6 * np.maximum(head - TOP_M, 0.0), rtol=1e-15)
    np.testing.assert_allclose(tangent, [0.0, mf6[1], mf6[2]], rtol=1e-15)


def test_a_declared_conductance_ignores_the_bed() -> None:
    mesh = _line_mesh()
    head = TOP_M + 0.1
    flux = drainage_outflow_from_head(mesh, head, drainage_conductance_m2_s=5.0e-3)
    np.testing.assert_allclose(flux, np.full(3, 5.0e-4), rtol=1e-12)


def test_the_default_bed_keeps_k_times_area() -> None:
    mesh = _line_mesh(drain_bed_thickness_m=1.0)
    np.testing.assert_allclose(derived_drain_conductance_m2_s(mesh), K_M_S * AREA_M2)
    np.testing.assert_allclose(
        derived_drain_conductance_m2_s(mesh), _mf6_fallback_conductance(bed_thickness=1.0)
    )


@pytest.mark.parametrize("bad", [0.0, -0.25, float("nan")])
def test_the_mesh_refuses_a_bed_that_is_not_positive(bad: float) -> None:
    with pytest.raises(ValueError, match="drain_bed_thickness_m"):
        _line_mesh(drain_bed_thickness_m=bad)


def test_the_jacobian_matches_a_finite_difference_with_the_drain_active() -> None:
    """Semi-analytic base Jacobian against a central difference of the residual.

    Cell 0 sits below its top, cell 1 drains through the derived conductance and
    cell 2 through a declared one. The saturation-excess term is left out on
    both sides: the runtimes differentiate it apart, by finite differences.
    """
    mesh = _line_mesh()
    head_prev = TOP_M - 1.0
    head = TOP_M + np.asarray([-0.5, 0.3, 0.05])
    drainage = np.asarray([0.0, -1.0, 5.0e-3])
    dt_seconds = 86_400.0

    def residual(candidate: np.ndarray) -> np.ndarray:
        assembly = assemble_transient_residual(
            mesh,
            head_m=candidate,
            head_prev_m=head_prev,
            dt_seconds=dt_seconds,
            recharge_rate_m_s=1.0e-8,
            drainage_conductance_m2_s=drainage,
        )
        return assembly.residual_m3_s - mesh.cell_area_m2 * assembly.saturation_excess_rate_m_s

    def analytic_jacobian(conductance: np.ndarray | None) -> np.ndarray:
        data, rows, cols = build_sparse_semianalytic_base_jacobian_triplets(
            mesh,
            head,
            dt_seconds=dt_seconds,
            drainage_conductance_m2_s=conductance,
        )
        dense = np.zeros((3, 3))
        np.add.at(dense, (rows, cols), data)
        return dense

    analytic = analytic_jacobian(drainage)

    step = 1.0e-6
    numeric = np.zeros((3, 3))
    for col in range(3):
        shift = np.zeros(3)
        shift[col] = step
        numeric[:, col] = (residual(head + shift) - residual(head - shift)) / (2.0 * step)

    scale = float(np.max(np.abs(numeric)))
    np.testing.assert_allclose(analytic, numeric, rtol=1e-7, atol=1e-9 * scale)
    # The drain adds K * A / b to the diagonal of cell 1, not K * A.
    drain_part = analytic - analytic_jacobian(None)
    np.testing.assert_allclose(
        np.diag(drain_part), [0.0, K_M_S[1] * AREA_M2[1] / BED_M, 5.0e-3], rtol=1e-12
    )


def test_the_flow_adapter_threads_the_solver_bed_into_the_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, BoussinesqMesh] = {}

    class _Recorder:
        def __init__(self, *, mesh: BoussinesqMesh, **_: object) -> None:
            captured["mesh"] = mesh
            self.full_path = tmp_path

        def pre_processing(self) -> None:
            return None

        def processing(self, **_: object) -> bool:
            return True

    monkeypatch.setattr(
        flow_adapter_module, "resolve_runtime_solver_mesh", lambda _setup: _line_mesh()
    )
    monkeypatch.setattr(flow_adapter_module, "Boussinesq", _Recorder)
    state = RunState(
        setup=SimpleNamespace(
            flow=None,
            domain=None,
            time_grid=None,
            workspace=SimpleNamespace(solver_scratch_folder=tmp_path),
        ),
        cfg=SimpleNamespace(solver=SolverConfig.model_validate({"drain_bed_thickness_m": 0.4})),
    )
    run = ProcessRun(
        id="flow::boussinesq", process_id="flow", process_type="flow", solver="boussinesq"
    )
    ctx = RunContext(
        plan=SimulationPlan(name="demo", description="demo", runs=(run,)),
        run=run,
        state=state,
    )

    BoussinesqFlowAdapter().execute(ctx)

    assert captured["mesh"].drain_bed_thickness_m == pytest.approx(0.4)
    np.testing.assert_allclose(
        derived_drain_conductance_m2_s(captured["mesh"]), K_M_S * AREA_M2 / 0.4
    )
