"""Time steps of a stress period (s) and the automatic engine choice of the Boussinesq solver.

A closed strip of triangles relaxes a sloping water table with no forcing. The engine is
sparse above DENSE_ENGINE_MAX_CELLS cells and a dense engine is refused there.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.drivers import transient as transient_driver
from hydromodpy.solver.boussinesq.drivers.forcing import ResolvedRuntimeForcing
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.boussinesq.solver_contract import DENSE_ENGINE_MAX_CELLS
from hydromodpy.solver.boussinesq.state import BoussinesqState
from tests._helpers.boussinesq_cell_meshes import placeholder_cell_mesh
from tests._helpers.model_factory import make_model

from ._row_runs import row_mesh

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
        cell_mesh=placeholder_cell_mesh(n_cells),
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
    runtime = (
        BoussinesqOptions()
        if runtime_backend is None
        else BoussinesqOptions(backend=runtime_backend)
    )
    time_grid = SimpleNamespace(period_lengths_seconds=period_lengths_seconds)
    if nstp_per_period is not None:
        time_grid.nstp_per_period = nstp_per_period
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=mesh,
        model=make_model(
            time=ModelTime(grid=time_grid, regime="transient", first_period_steady=False)
        ),
        runtime=runtime,
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
def test_sub_steps_equal_short_periods(tmp_path: Path, closed_strip, runtime_backend: str) -> None:
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


def test_sub_step_count_is_a_positive_integer() -> None:
    assert transient_driver._resolve_time_steps_per_period(SimpleNamespace()) == 1
    assert transient_driver._resolve_time_steps_per_period(None) == 1
    assert transient_driver._resolve_time_steps_per_period(SimpleNamespace(nstp_per_period=3)) == 3
    for bad in (0, -2, 1.5, True):
        with pytest.raises(ValueError, match="nstp_per_period"):
            transient_driver._resolve_time_steps_per_period(SimpleNamespace(nstp_per_period=bad))


def test_auto_engine_is_sparse_on_a_large_mesh(
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


@pytest.mark.parametrize("runtime_backend", ["local", "scipy"])
def test_dense_engine_on_a_large_mesh_is_refused(
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


DURATIONS = [
    pytest.param(pd.Timedelta(hours=1), 3600.0, id="pandas timedelta"),
    pytest.param(np.timedelta64(90, "m"), 5400.0, id="numpy timedelta"),
    pytest.param(7200, 7200.0, id="seconds"),
]


@pytest.mark.parametrize(("value", "seconds"), DURATIONS)
def test_duration_in_seconds(value: object, seconds: float) -> None:
    assert transient_driver._duration_seconds(value) == seconds


DAY = np.timedelta64(1, "D")
T0 = np.datetime64("2020-01-01")

BOUNDARIES = [
    pytest.param(None, (), id="no boundaries"),
    pytest.param((T0,), (), id="one boundary"),
    pytest.param((T0, T0 + DAY, T0 + 3 * DAY), (DAY_S, 2 * DAY_S), id="two periods"),
    pytest.param((T0, T0 + DAY, T0 + DAY), (), id="empty period"),
]


@pytest.mark.parametrize(("boundaries", "lengths_s"), BOUNDARIES)
def test_period_lengths_from_boundaries(boundaries: object, lengths_s: tuple[float, ...]) -> None:
    assert transient_driver._period_lengths_from_boundaries(boundaries) == lengths_s


def test_grid_without_periods_has_no_lengths() -> None:
    assert transient_driver._resolve_period_lengths_seconds(SimpleNamespace()) == ()


RECORDS = [
    pytest.param(None, 0, [], id="not a list"),
    pytest.param([{"iteration": 4}, "skipped", 3], None, [{"iteration": 4}], id="no step index"),
    pytest.param([{"iteration": 4}], 2, [{"iteration": 4, "time_step_index": 2}], id="step index"),
]


@pytest.mark.parametrize(("raw", "index", "tagged"), RECORDS)
def test_tagged_details(raw: object, index: int | None, tagged: list[dict]) -> None:
    assert transient_driver._tagged_details(raw, time_step_index=index) == tagged


class _TaggedBackend:
    """The real engine, its steps carrying diagnostics and a chosen convergence flag."""

    def __init__(self, backend, diagnostics: dict | None, *, converged: bool) -> None:
        self._backend = backend
        self._changes = {"diagnostics": diagnostics, "converged": converged}

    def solve_transient_step(self, inputs):
        return replace(self._backend.solve_transient_step(inputs), **self._changes)


def _period_inputs(tmp_path: Path):
    """The local engine and the forcing of one period on a row of 6 cells, 20 m held at cell 0."""
    mesh = row_mesh()
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=mesh,
        model=make_model(
            time=ModelTime(grid=SimpleNamespace(), regime="transient", first_period_steady=False)
        ),
        runtime=BoussinesqOptions(backend="local"),
        model_folder=tmp_path,
        model_name="advance",
    )
    held = np.full(mesh.n_cells, np.nan)
    held[0] = 20.0
    step_kwargs = {
        "mesh": mesh,
        "recharge_rate_m_s": 0.0,
        "well_flux_m3_s": np.zeros(mesh.n_cells),
        "prescribed_head_m_by_cell": held,
        "drainage_conductance_m2_s": np.zeros(mesh.n_cells),
        "options": solver._runtime_options(),
    }
    backend = solver._resolve_solver_contract().runtime_backend
    return backend, np.full(mesh.n_cells, 30.0), step_kwargs


TAGGED_STEPS = {"vi_substep_details": [{"substep": 1}], "ts_vi_step_details": [{"step": 7}]}

ADVANCES = [
    pytest.param(1, True, 1, None, id="one step is not tagged"),
    pytest.param(3, True, 3, 2, id="steps are tagged by index"),
    pytest.param(3, False, 1, 0, id="stops at the first failure"),
]


@pytest.mark.parametrize(("n_steps", "converged", "n_run", "last_tag"), ADVANCES)
def test_advance_period_records(
    tmp_path: Path, n_steps: int, converged: bool, n_run: int, last_tag: int | None
) -> None:
    backend, head_m, step_kwargs = _period_inputs(tmp_path)
    tagged = _TaggedBackend(backend, TAGGED_STEPS, converged=converged)

    advance = transient_driver._advance_period(
        tagged, head_start_m=head_m, period_seconds=DAY_S, n_steps=n_steps, step_kwargs=step_kwargs
    )

    assert advance.converged is converged
    assert len(advance.substep_details) == len(advance.ts_step_details) == n_run
    last = {} if last_tag is None else {"time_step_index": last_tag}
    assert advance.substep_details[-1] == {"substep": 1} | last
    assert advance.ts_step_details[-1] == {"step": 7} | last


def test_ts_vi_steady_period_uses_vi_obstacle() -> None:
    contract = SimpleNamespace(
        runtime_backend=SimpleNamespace(name="petsc"),
        surface_interaction_model_resolved="ts_vi_obstacle",
    )

    stationary = transient_driver.stationary_backend(contract)

    assert stationary.name == "petsc"
    assert stationary.method.id == "head_only_vi_obstacle"
