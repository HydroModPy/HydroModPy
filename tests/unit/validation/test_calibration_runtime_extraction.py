"""Tests for the head-at-point cell-index resolution in the twin runtime.

Covers the lightweight v1 path where ``setup.cell_mesh`` is ``None``: the
runtime helper must resolve the structured cell from the solver model
registered in ``execution.solver_runs`` instead of relying on a
pre-existing cell mesh.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from validation_cases.calibration.shared.runtime import (
    _extract_outlet_discharge_from_run,
    _extract_outputs_from_trial_ctx,
    _model_cell_centroids,
    _resolve_cell_index_from_cell_mesh,
    _resolve_cell_index_from_model,
)


def _make_structured_centroids(nrow: int, ncol: int, dx: float = 10.0, dy: float = 5.0):
    """Build flat ``(n_cells, 2)`` centroids for a structured ``nrow x ncol`` grid."""
    coords = np.empty((nrow * ncol, 2), dtype=float)
    for r in range(nrow):
        for c in range(ncol):
            coords[r * ncol + c, 0] = (c + 0.5) * dx
            coords[r * ncol + c, 1] = (r + 0.5) * dy
    return coords


class TestModelCellCentroids:
    def test_reads_from_solver_mesh_callable(self):
        centroids = _make_structured_centroids(2, 3)
        model = SimpleNamespace(
            solver_mesh=SimpleNamespace(cell_centers=lambda: centroids),
            nrow=2,
            ncol=3,
        )
        out = _model_cell_centroids(model)
        assert out is not None
        np.testing.assert_array_equal(out, centroids)

    def test_falls_back_to_the_cell_mesh_of_the_model(self):
        centroids = _make_structured_centroids(1, 4)
        model = SimpleNamespace(
            solver_mesh=None,
            cell_mesh=SimpleNamespace(centers=centroids),
        )
        out = _model_cell_centroids(model)
        assert out is not None
        np.testing.assert_array_equal(out, centroids)

    def test_returns_none_when_model_exposes_nothing(self):
        model = SimpleNamespace()
        assert _model_cell_centroids(model) is None


class TestResolveCellIndexFromModel:
    def test_picks_nearest_cell_on_structured_grid(self):
        nrow, ncol = 2, 3
        centroids = _make_structured_centroids(nrow, ncol, dx=10.0, dy=5.0)
        model = SimpleNamespace(
            solver_mesh=SimpleNamespace(cell_centers=lambda: centroids),
            nrow=nrow,
            ncol=ncol,
        )
        # Cell (row=1, col=2) centroid is (25.0, 7.5), flat index 5.
        cell = _resolve_cell_index_from_model(model, x=24.0, y=8.0)
        assert cell == (0, 1, 2, 5)

    def test_returns_none_for_missing_model(self):
        assert _resolve_cell_index_from_model(None, x=0.0, y=0.0) is None

    def test_returns_flat_index_when_layout_unknown(self):
        centroids = _make_structured_centroids(1, 4)
        model = SimpleNamespace(
            solver_mesh=SimpleNamespace(cell_centers=lambda: centroids),
        )
        cell = _resolve_cell_index_from_model(model, x=25.0, y=2.5)
        assert cell == (0, 0, 2, 2)


class TestResolveCellIndexFromCellMesh:
    def test_handles_none_mesh(self):
        assert _resolve_cell_index_from_cell_mesh(None, x=0.0, y=0.0) is None

    def test_resolves_via_centres_and_structured_shape(self):
        nrow, ncol = 2, 3
        centroids = _make_structured_centroids(nrow, ncol, dx=10.0, dy=5.0)
        mesh = SimpleNamespace(centers=centroids, structured_shape=(nrow, ncol))
        cell = _resolve_cell_index_from_cell_mesh(mesh, x=14.0, y=2.0)
        assert cell == (0, 0, 1, 1)

    def test_an_unstructured_mesh_gives_the_flat_index_alone(self):
        centroids = _make_structured_centroids(1, 4)
        mesh = SimpleNamespace(centers=centroids, structured_shape=None)
        cell = _resolve_cell_index_from_cell_mesh(mesh, x=25.0, y=2.5)
        assert cell == (0, 0, 2, 2)


class TestReadHeadAtCell:
    def test_reads_dis_3d_head(self):
        from validation_cases.calibration.shared.runtime import _read_head_at_cell

        head = np.arange(2 * 3 * 4, dtype=float).reshape(2, 3, 4)
        # head[1, 2, 3] == 23.0; flat_index irrelevant for DIS arrays.
        assert _read_head_at_cell(head, layer=1, row=2, col=3, flat_index=0, ncol_hint=4) == 23.0

    def test_reads_disv_3d_head_via_flat_index(self):
        from validation_cases.calibration.shared.runtime import _read_head_at_cell

        # DISV: shape (nlay, 1, ncpl). Row/col split must collapse to flat.
        head = np.arange(1 * 1 * 12, dtype=float).reshape(1, 1, 12)
        # Cell (row=2, col=3) on a 3x4 grid -> flat 11.
        assert _read_head_at_cell(head, layer=0, row=2, col=3, flat_index=11, ncol_hint=4) == 11.0

    def test_falls_back_to_2d(self):
        from validation_cases.calibration.shared.runtime import _read_head_at_cell

        head = np.arange(1 * 12, dtype=float).reshape(1, 12)
        assert _read_head_at_cell(head, layer=0, row=0, col=0, flat_index=7, ncol_hint=4) == 7.0


class TestExtractOutputsFromTrialCtx:
    def test_unknown_outputs_return_nan_padded(self):
        # With no execution registry, every declaration collapses to
        # NaN-padded vectors of the expected length.
        decl = SimpleNamespace(
            variable="head",
            support="point",
            x=100.0,
            y=20.0,
            observed_values=(1.0, 2.0, 3.0),
        )
        trial_ctx = SimpleNamespace(execution=None, setup=SimpleNamespace())
        out = _extract_outputs_from_trial_ctx(
            trial_ctx=trial_ctx,
            output_decls=(("head_mid", decl),),
        )
        assert "head_mid" in out
        assert len(out["head_mid"]) == 3
        for v in out["head_mid"]:
            assert np.isnan(v)

    def test_collapses_when_no_flow_run_in_plan(self):
        # Empty registry: no flow run mapped, NaN-padded fallback.
        registry = SimpleNamespace(solver_runs={}, simulation_plan=None)
        trial_ctx = SimpleNamespace(execution=registry, setup=SimpleNamespace())
        decl = SimpleNamespace(
            variable="head",
            support="point",
            x=0.0,
            y=0.0,
            observed_values=(0.0, 0.0),
        )
        out = _extract_outputs_from_trial_ctx(
            trial_ctx=trial_ctx,
            output_decls=(("head", decl),),
        )
        assert all(np.isnan(v) for v in out["head"])
        assert len(out["head"]) == 2


class TestExtractHeadAtPointFromDir:
    def test_returns_none_when_hds_missing(self, tmp_path):
        # The HDS file path is derived from ``model_name``; if the file is
        # absent the helper must fail gracefully (no crash, no NaN flood).
        from validation_cases.calibration.shared.runtime import (
            _extract_head_at_point_from_dir,
        )

        nrow, ncol = 2, 3
        centroids = _make_structured_centroids(nrow, ncol, dx=10.0, dy=5.0)
        model = SimpleNamespace(
            solver_mesh=SimpleNamespace(cell_centers=lambda: centroids),
            nrow=nrow,
            ncol=ncol,
        )
        result = _extract_head_at_point_from_dir(
            tmp_path,
            "missing_model",
            x=24.0,
            y=8.0,
            model=model,
            cell_mesh=None,
        )
        assert result is None

    def test_returns_none_when_no_cell_resolvable(self, tmp_path):
        # cell_mesh=None and model=None: no way to resolve (k,i,j),
        # the helper must short-circuit instead of indexing on bogus data.
        from validation_cases.calibration.shared.runtime import (
            _extract_head_at_point_from_dir,
        )

        # Touch the HDS file so the early exists check passes.
        (tmp_path / "stub_model.hds").write_bytes(b"")

        result = _extract_head_at_point_from_dir(
            tmp_path,
            "stub_model",
            x=24.0,
            y=8.0,
            model=None,
            cell_mesh=None,
        )
        assert result is None


def _quad_grid(nrow: int, ncol: int, cell: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the vertices and the faces of a regular grid, north row first."""
    xs = np.arange(ncol + 1) * cell
    ys = (nrow - np.arange(nrow + 1)) * cell
    vertices = np.array([(x, y) for y in ys for x in xs], dtype=float)
    faces = [
        [
            r * (ncol + 1) + c,
            r * (ncol + 1) + c + 1,
            (r + 1) * (ncol + 1) + c + 1,
            (r + 1) * (ncol + 1) + c,
        ]
        for r in range(nrow)
        for c in range(ncol)
    ]
    return vertices, np.asarray(faces, dtype=int)


class TestTruthAndTrialLocateOnePoint:
    """A noise-free twin closes only when both routes read the same cell."""

    nrow, ncol, cell = 2, 4, 10.0

    def _routes(self) -> tuple[SimpleNamespace, SimpleNamespace]:
        vertices, faces = _quad_grid(self.nrow, self.ncol, self.cell)
        run = SimpleNamespace(
            mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=faces),
            grid=SimpleNamespace(
                shape=(self.nrow, self.ncol),
                extent=(0.0, self.ncol * self.cell, 0.0, self.nrow * self.cell),
                cell_size=self.cell,
            ),
        )
        # A MODFLOW 6 model keeps the grid shape on its solver mesh only.
        model = SimpleNamespace(
            solver_mesh=SimpleNamespace(
                planar_mesh=SimpleNamespace(vertices=vertices, flat_connectivity=faces),
                structured_shape=(self.nrow, self.ncol),
                cell_centers=lambda: vertices[faces].mean(axis=1),
            )
        )
        return run, model


def test_the_truth_discharge_leaves_the_catchment_row_out():
    """The catchment cells lie in the domain, so adding their row counts them twice."""
    budget = pd.DataFrame(
        [
            {"timestep": 0, "zone_id": "domain", "component": "constant_head", "flux_out": 3.0},
            {"timestep": 0, "zone_id": "catchment", "component": "constant_head", "flux_out": 1.0},
            {"timestep": 1, "zone_id": "domain", "component": "constant_head", "flux_out": 2.0},
            {"timestep": 1, "zone_id": "catchment", "component": "constant_head", "flux_out": 0.5},
        ]
    )
    run = SimpleNamespace(budget=lambda: budget)
    values = _extract_outlet_discharge_from_run(run)
    assert values is not None
    assert values.tolist() == [3.0, 2.0]
