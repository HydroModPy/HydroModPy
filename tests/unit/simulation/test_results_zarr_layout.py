"""Tests for simulation/results/zarr_layout.py — Zarr v3 layout."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.results.zarr_layout import (
    create_simulation_group,
    write_field_chunk,
    write_mesh_arrays,
)


@pytest.fixture
def zarr_path(tmp_path):
    return str(tmp_path / "test_results.zarr")


class TestCreateSimulationGroup:
    def test_basic(self, zarr_path):
        grp = create_simulation_group(
            zarr_path, "sim-001", n_cells=100, n_layers=3,
        )
        assert grp.attrs["n_cells"] == 100
        assert grp.attrs["n_layers"] == 3
        assert "mesh" in grp
        assert "derived" in grp
        assert "budget" in grp
        assert "pathlines" in grp

    def test_cell_types_stored(self, zarr_path):
        grp = create_simulation_group(
            zarr_path, "sim-002",
            n_cells=50, n_layers=1, cell_types=["triangle", "quad"],
        )
        assert grp.attrs["cell_types"] == ["triangle", "quad"]

    def test_idempotent(self, zarr_path):
        create_simulation_group(zarr_path, "sim-003", n_cells=10, n_layers=1)
        grp = create_simulation_group(zarr_path, "sim-003", n_cells=10, n_layers=1)
        assert grp.attrs["n_cells"] == 10


class TestWriteMeshArrays:
    def test_roundtrip_triangles(self, zarr_path):
        n_nodes, n_cells = 6, 4
        vertices = np.random.default_rng(0).random((n_nodes, 2))
        connectivity = np.array([
            [0, 1, 2], [1, 3, 2], [2, 3, 4], [3, 5, 4],
        ], dtype="int32")
        z_interfaces = np.array([0.0, -5.0, -15.0])

        grp = create_simulation_group(
            zarr_path, "mesh-tri", n_cells=n_cells, n_layers=2,
        )
        write_mesh_arrays(grp, vertices, connectivity, z_interfaces)

        mesh = grp["mesh"]
        np.testing.assert_array_equal(mesh["vertices"][:], vertices)
        np.testing.assert_array_equal(mesh["face_node_connectivity"][:], connectivity)
        np.testing.assert_array_equal(mesh["z_interfaces"][:], z_interfaces)
        assert mesh.attrs["n_nodes"] == n_nodes
        assert mesh.attrs["n_cells"] == n_cells
        assert mesh.attrs["n_layers"] == 2

    def test_mixed_tri_quad(self, zarr_path):
        vertices = np.random.default_rng(1).random((8, 2))
        # 2 triangles + 1 quad, padded with -1
        connectivity = np.array([
            [0, 1, 2, -1],
            [2, 3, 4, -1],
            [4, 5, 6, 7],
        ], dtype="int32")
        z_interfaces = np.array([0.0, -10.0])
        layer_idx = np.array([0, 0, 0], dtype="int32")
        source_idx = np.array([0, 1, 2], dtype="int32")

        grp = create_simulation_group(
            zarr_path, "mesh-mix", n_cells=3, n_layers=1,
        )
        write_mesh_arrays(
            grp, vertices, connectivity, z_interfaces,
            layer_indices=layer_idx, source_cell_indices=source_idx,
        )

        mesh = grp["mesh"]
        np.testing.assert_array_equal(mesh["layer_indices"][:], layer_idx)
        np.testing.assert_array_equal(mesh["source_cell_indices"][:], source_idx)


class TestWriteFieldChunk:
    def test_3d_roundtrip(self, zarr_path):
        n_layers, n_cells, n_ts = 3, 50, 10
        grp = create_simulation_group(
            zarr_path, "field-3d", n_cells=n_cells, n_layers=n_layers,
        )

        rng = np.random.default_rng(42)
        all_values = rng.random((n_ts, n_layers, n_cells))

        for t in range(n_ts):
            write_field_chunk(
                grp, "head", t, all_values[t],
                n_timesteps=n_ts if t == 0 else None,
            )

        result = grp["head"][:]
        np.testing.assert_array_almost_equal(result, all_values)

    def test_2d_field(self, zarr_path):
        n_cells, n_ts = 100, 5
        grp = create_simulation_group(
            zarr_path, "field-2d", n_cells=n_cells, n_layers=1,
        )

        rng = np.random.default_rng(99)
        for t in range(n_ts):
            vals = rng.random(n_cells)
            write_field_chunk(
                grp, "watertable_depth", t, vals,
                n_timesteps=n_ts if t == 0 else None,
                subgroup="derived",
            )

        result = grp["derived"]["watertable_depth"][:]
        assert result.shape == (n_ts, n_cells)

    def test_missing_n_timesteps_raises(self, zarr_path):
        grp = create_simulation_group(
            zarr_path, "field-err", n_cells=10, n_layers=1,
        )
        with pytest.raises(ValueError, match="n_timesteps required"):
            write_field_chunk(grp, "head", 0, np.zeros((2, 10)))

    def test_bad_ndim_raises(self, zarr_path):
        grp = create_simulation_group(
            zarr_path, "field-bad", n_cells=10, n_layers=1,
        )
        with pytest.raises(ValueError, match="1D or 2D"):
            write_field_chunk(
                grp, "head", 0, np.zeros((2, 3, 4, 5)), n_timesteps=1,
            )
