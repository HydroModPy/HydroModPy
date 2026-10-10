"""Time steps of a stress period and the automatic engine choice of the Boussinesq solver."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.core.state import BoussinesqState
from hydromodpy.solver.boussinesq.drivers import transient as transient_driver
from hydromodpy.solver.boussinesq.drivers.forcing import ResolvedRuntimeForcing
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.solver_contract import (
    DENSE_ENGINE_MAX_CELLS,
    resolve_runtime_backend_name,
)

DAY_S = 86400.0


def _strip_mesh(nx: int, *, dx: float = 10.0) -> BoussinesqMesh:
    """Return a strip of nx squares cut into right triangles, closed on every side."""
    node_xy = [(ix * dx, iy * dx) for iy in range(2) for ix in range(nx + 1)]
    triangles: list[tuple[int, int, int]] = []
    for ix in range(nx):
        n00, n10 = ix, ix + 1
        n01, n11 = ix + nx + 1, ix + nx + 2
        if ix % 2 == 0:
            triangles += [(n00, n10, n11), (n00, n11, n01)]
        else:
            triangles += [(n00, n10, n01), (n10, n11, n01)]
    xy = np.asarray(node_xy, dtype=float)
    centroids = np.asarray([xy[list(tri)].mean(axis=0) for tri in triangles])
    edge_cells: dict[tuple[int, int], list[int]] = {}
    for cell, tri in enumerate(triangles):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge_cells.setdefault((min(a, b), max(a, b)), []).append(cell)
    keys = list(edge_cells)
    cell_a = np.asarray([edge_cells[key][0] for key in keys], dtype=int)
    cell_b = np.asarray(
        [edge_cells[key][1] if len(edge_cells[key]) > 1 else -1 for key in keys], dtype=int
    )
    node_a = np.asarray([key[0] for key in keys], dtype=int)
    node_b = np.asarray([key[1] for key in keys], dtype=int)
    midpoints = 0.5 * (xy[node_a] + xy[node_b])
    to_a = np.linalg.norm(midpoints - centroids[cell_a], axis=1)
    to_b = np.where(
        cell_b >= 0,
        np.linalg.norm(midpoints - centroids[np.maximum(cell_b, 0)], axis=1),
        0.0,
    )
    distance = np.where(
        cell_b >= 0,
        np.linalg.norm(centroids[cell_a] - centroids[np.maximum(cell_b, 0)], axis=1),
        to_a,
    )
    n_cells = len(triangles)
    return BoussinesqMesh(
        bundle_dir=Path("."),
        cell_ids=np.arange(n_cells),
        node_ids=np.arange(len(node_xy)),
        node_x_m=xy[:, 0],
        node_y_m=xy[:, 1],
        cell_node_ids=tuple(triangles),
        cell_centroid_x_m=centroids[:, 0],
        cell_centroid_y_m=centroids[:, 1],
        cell_area_m2=np.full(n_cells, 0.5 * dx * dx),
        z_top_m=np.full(n_cells, 20.0),
        z_bottom_m=np.zeros(n_cells),
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-4),
        storage_coefficient=np.full(n_cells, 0.1),
        edge_ids=np.arange(len(keys)),
        edge_node_a=node_a,
        edge_node_b=node_b,
        edge_cell_a=cell_a,
        edge_cell_b=cell_b,
        edge_length_m=np.linalg.norm(xy[node_b] - xy[node_a], axis=1),
        edge_distance_m=distance,
        edge_midpoint_distance_to_cell_a_m=to_a,
        edge_midpoint_distance_to_cell_b_m=to_b,
        edge_midpoint_x_m=midpoints[:, 0],
        edge_midpoint_y_m=midpoints[:, 1],
        edge_kind=tuple("internal" if b >= 0 else "boundary" for b in cell_b),
        edge_is_river=np.zeros(len(keys), dtype=bool),
        cell_index_by_id={cell: cell for cell in range(n_cells)},
        node_index_by_id={node: node for node in range(len(node_xy))},
    )


def _no_forcing(solver, *, nper: int) -> ResolvedRuntimeForcing:
    """Return a closed strip without recharge, wells, imposed heads or drains."""
    mesh = solver.mesh
    return ResolvedRuntimeForcing(
        recharge_series_m_s=tuple(0.0 for _ in range(nper)),
        active_recharge=False,
        well_flux_by_period_m3_s=np.zeros((nper, mesh.n_cells)),
        ocean_series_m=None,
        dirichlet_supports_by_period=tuple(() for _ in range(nper)),
        prescribed_heads_by_period=tuple(np.full(mesh.n_cells, np.nan) for _ in range(nper)),
        boundary_heads_by_period=tuple(np.full(mesh.n_edges, np.nan) for _ in range(nper)),
        ocean_supported_cell_masks=tuple(np.zeros(mesh.n_cells, dtype=bool) for _ in range(nper)),
        drainage_conductance_series_m2_s=np.zeros(nper),
    )


def _run_relaxation(
    tmp_path: Path,
    *,
    mesh: BoussinesqMesh,
    runtime_backend: str | None,
    period_lengths_seconds: tuple[float, ...],
    nstp_per_period: int | None,
) -> Boussinesq:
    """Relax a sloping water table on a closed strip and return the solver."""
    flow = SimpleNamespace(
        flow_regime="transient", surface_interaction_model="auto", first_period_steady=False
    )
    if runtime_backend is not None:
        flow.runtime_backend = runtime_backend
    time_grid = SimpleNamespace(period_lengths_seconds=period_lengths_seconds)
    if nstp_per_period is not None:
        time_grid.nstp_per_period = nstp_per_period
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=mesh,
        flow=flow,
        domain=SimpleNamespace(),
        time_grid=time_grid,
        model_folder=tmp_path,
        model_name=f"relax_{runtime_backend}_{len(period_lengths_seconds)}_{nstp_per_period}",
    )
    head = 2.0 + 6.0 * mesh.cell_centroid_x_m / float(np.max(mesh.node_x_m))
    solver.state = BoussinesqState.initial(head_m=head, saturated_thickness_m=head.copy())
    assert solver._run_transient_runtime()
    return solver


@pytest.fixture
def closed_strip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(transient_driver, "resolve_runtime_forcing_by_period", _no_forcing)


@pytest.mark.parametrize("runtime_backend", ["local", "scipy", "scipy_sparse", "petsc"])
def test_sub_steps_of_one_period_equal_as_many_periods_of_one_step(
    tmp_path: Path, closed_strip, runtime_backend: str
) -> None:
    if runtime_backend == "petsc":
        pytest.importorskip("petsc4py")
    mesh = _strip_mesh(5)
    period_s = 2.0 * DAY_S
    n_steps = 4

    sub_stepped = _run_relaxation(
        tmp_path,
        mesh=mesh,
        runtime_backend=runtime_backend,
        period_lengths_seconds=(period_s,),
        nstp_per_period=n_steps,
    )
    short_periods = _run_relaxation(
        tmp_path,
        mesh=mesh,
        runtime_backend=runtime_backend,
        period_lengths_seconds=(period_s / n_steps,) * n_steps,
        nstp_per_period=None,
    )
    one_step = _run_relaxation(
        tmp_path,
        mesh=mesh,
        runtime_backend=runtime_backend,
        period_lengths_seconds=(period_s,),
        nstp_per_period=1,
    )

    assert sub_stepped.runtime_summary["time_steps_per_period"] == n_steps
    assert sub_stepped.state.head_history_m.shape == (2, mesh.n_cells)
    np.testing.assert_allclose(
        sub_stepped.state.head_m, short_periods.state.head_m, rtol=0.0, atol=1.0e-7
    )
    # One backward-Euler step damps the relaxation less: the steps did run.
    assert np.max(np.abs(sub_stepped.state.head_m - one_step.state.head_m)) > 1.0e-2


def test_time_grid_sub_step_count_must_be_a_positive_integer() -> None:
    assert transient_driver._resolve_time_steps_per_period(SimpleNamespace()) == 1
    assert transient_driver._resolve_time_steps_per_period(None) == 1
    assert transient_driver._resolve_time_steps_per_period(SimpleNamespace(nstp_per_period=3)) == 3
    for bad in (0, -2, 1.5, True):
        with pytest.raises(ValueError, match="nstp_per_period"):
            transient_driver._resolve_time_steps_per_period(SimpleNamespace(nstp_per_period=bad))


def test_auto_engine_is_the_flow_default_and_resolves_on_the_mesh_size() -> None:
    assert FlowConfig().runtime_backend == "auto"
    assert resolve_runtime_backend_name("auto", n_cells=DENSE_ENGINE_MAX_CELLS) == "local"
    assert resolve_runtime_backend_name("auto", n_cells=DENSE_ENGINE_MAX_CELLS + 1) == (
        "scipy_sparse"
    )
    assert resolve_runtime_backend_name("auto", n_cells=None) == "local"
    assert resolve_runtime_backend_name("local", n_cells=10_000) == "local"
    assert resolve_runtime_backend_name("petsc", n_cells=10) == "petsc"


def test_default_engine_runs_sparse_on_a_large_mesh_and_logs_it_once(
    tmp_path: Path, closed_strip, caplog: pytest.LogCaptureFixture
) -> None:
    mesh = _strip_mesh(201)
    assert mesh.n_cells > DENSE_ENGINE_MAX_CELLS

    with caplog.at_level(logging.INFO, logger="hydromodpy.solver.boussinesq.boussinesq"):
        auto = _run_relaxation(
            tmp_path,
            mesh=mesh,
            runtime_backend=None,
            period_lengths_seconds=(DAY_S, DAY_S),
            nstp_per_period=None,
        )
        auto._resolve_solver_contract()
    engine_lines = [r.getMessage() for r in caplog.records if "Boussinesq engine" in r.getMessage()]
    explicit = _run_relaxation(
        tmp_path,
        mesh=mesh,
        runtime_backend="scipy_sparse",
        period_lengths_seconds=(DAY_S, DAY_S),
        nstp_per_period=None,
    )

    assert auto.runtime_summary["runtime_backend_requested"] == "auto"
    assert auto.runtime_summary["runtime_backend"] == "scipy_sparse"
    np.testing.assert_array_equal(auto.state.head_m, explicit.state.head_m)
    assert len(engine_lines) == 1
    assert "'scipy_sparse'" in engine_lines[0] and "'auto'" in engine_lines[0]


def test_default_engine_stays_local_on_a_small_mesh(tmp_path: Path, closed_strip) -> None:
    solver = _run_relaxation(
        tmp_path,
        mesh=_strip_mesh(5),
        runtime_backend=None,
        period_lengths_seconds=(DAY_S,),
        nstp_per_period=None,
    )

    assert solver.runtime_summary["runtime_backend_requested"] == "auto"
    assert solver.runtime_summary["runtime_backend"] == "local"


@pytest.mark.parametrize("runtime_backend", ["local", "scipy"])
def test_explicit_dense_engine_on_a_large_mesh_is_refused(
    tmp_path: Path, closed_strip, runtime_backend: str
) -> None:
    with pytest.raises(IncompatibleCapabilitiesError, match="dense Jacobian by design"):
        _run_relaxation(
            tmp_path,
            mesh=_strip_mesh(201),
            runtime_backend=runtime_backend,
            period_lengths_seconds=(DAY_S,),
            nstp_per_period=None,
        )
