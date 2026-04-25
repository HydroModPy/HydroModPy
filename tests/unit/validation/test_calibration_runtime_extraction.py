"""Tests for the head-at-point cell-index resolution in the twin runtime.

Covers the lightweight v0.6 path where ``setup.mesh_planar`` is ``None``
for sgrid simulations: the runtime helper must resolve the structured
cell from the solver model registered in ``execution.models_by_run_id``
instead of relying on a pre-existing planar mesh.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from validation_cases.calibration.shared.runtime import (
    _extract_outputs_from_trial_ctx,
    _model_cell_centroids,
    _nearest_cell_index_legacy,
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
            solver_mesh=SimpleNamespace(cell_centroids=lambda: centroids),
            nrow=2,
            ncol=3,
        )
        out = _model_cell_centroids(model)
        assert out is not None
        np.testing.assert_array_equal(out, centroids)

    def test_falls_back_to_runtime_mesh_planar(self):
        centroids = _make_structured_centroids(1, 4)
        model = SimpleNamespace(
            solver_mesh=None,
            runtime_mesh_planar=SimpleNamespace(cell_centroids=centroids),
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
            solver_mesh=SimpleNamespace(cell_centroids=lambda: centroids),
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
            solver_mesh=SimpleNamespace(cell_centroids=lambda: centroids),
        )
        cell = _resolve_cell_index_from_model(model, x=25.0, y=2.5)
        assert cell == (0, 0, 2, 2)


class TestNearestCellIndexLegacy:
    def test_handles_none_mesh(self):
        assert _nearest_cell_index_legacy(None, x=0.0, y=0.0) is None

    def test_resolves_via_centroids_and_shape(self):
        nrow, ncol = 2, 3
        centroids = _make_structured_centroids(nrow, ncol, dx=10.0, dy=5.0)
        mesh = SimpleNamespace(cell_centroids=centroids, shape=(1, nrow, ncol))
        cell = _nearest_cell_index_legacy(mesh, x=14.0, y=2.0)
        assert cell == (0, 0, 1, 1)


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
        registry = SimpleNamespace(
            output_dirs_by_run_id={},
            models_by_run_id={},
            simulation_plan=None,
        )
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
            solver_mesh=SimpleNamespace(cell_centroids=lambda: centroids),
            nrow=nrow,
            ncol=ncol,
        )
        result = _extract_head_at_point_from_dir(
            tmp_path,
            "missing_model",
            x=24.0,
            y=8.0,
            model=model,
            mesh_planar=None,
        )
        assert result is None

    def test_returns_none_when_no_cell_resolvable(self, tmp_path):
        # mesh_planar=None and model=None: no way to resolve (k,i,j),
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
            mesh_planar=None,
        )
        assert result is None
