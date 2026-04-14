from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.zarr_store import SimulationZarr


@pytest.fixture
def sz(tmp_path):
    path = tmp_path / "test_sim.zarr"
    store = SimulationZarr.create(path, n_cells=100, n_layers=3)
    yield store
    store.close()


def _make_mesh(n_cells=6):
    vertices = np.array([
        [0.0, 0.0], [1.0, 0.0], [2.0, 0.0],
        [0.0, 1.0], [1.0, 1.0], [2.0, 1.0],
        [0.0, 2.0], [1.0, 2.0], [2.0, 2.0],
    ], dtype="float64")
    connectivity = np.array([
        [0, 1, 4, 3], [1, 2, 5, 4],
        [3, 4, 7, 6], [4, 5, 8, 7],
        [0, 1, 4, -1], [4, 5, 8, -1],
    ], dtype="int32")
    z_interfaces = np.array([0.0, -5.0, -15.0, -30.0], dtype="float64")
    return vertices, connectivity[:n_cells], z_interfaces


class TestCreate:
    def test_subgroups_exist(self, sz):
        for name in ("mesh", "derived", "budget", "pathlines", "geographic"):
            assert name in sz.root

    def test_attrs(self, sz):
        assert sz.root.attrs["n_cells"] == 100
        assert sz.root.attrs["n_layers"] == 3

    def test_cell_types_stored(self, tmp_path):
        path = tmp_path / "typed.zarr"
        s = SimulationZarr.create(path, n_cells=10, n_layers=1, cell_types=["triangle"])
        assert s.root.attrs["cell_types"] == ["triangle"]
        s.close()

    def test_reopen(self, tmp_path):
        path = tmp_path / "reopen.zarr"
        s1 = SimulationZarr.create(path, n_cells=5, n_layers=2)
        s1.close()
        s2 = SimulationZarr(path)
        assert s2.root.attrs["n_cells"] == 5
        assert "mesh" in s2.root
        s2.close()


class TestMesh:
    def test_write_read_roundtrip(self, sz):
        verts, conn, z = _make_mesh(4)
        sz.write_mesh(verts, conn, z)
        mesh = sz.root["mesh"]
        np.testing.assert_array_equal(mesh["vertices"][:], verts)
        np.testing.assert_array_equal(mesh["face_node_connectivity"][:], conn)
        np.testing.assert_array_equal(mesh["z_interfaces"][:], z)

    def test_mesh_attrs(self, sz):
        verts, conn, z = _make_mesh(4)
        sz.write_mesh(verts, conn, z)
        mesh = sz.root["mesh"]
        assert mesh.attrs["n_nodes"] == 9
        assert mesh.attrs["n_cells"] == 4
        assert mesh.attrs["n_layers"] == 3

    def test_optional_arrays(self, sz):
        verts, conn, z = _make_mesh(4)
        layers = np.array([0, 0, 1, 1], dtype="int32")
        source = np.array([0, 1, 0, 1], dtype="int32")
        sz.write_mesh(verts, conn, z, layer_indices=layers, source_cell_indices=source)
        mesh = sz.root["mesh"]
        np.testing.assert_array_equal(mesh["layer_indices"][:], layers)
        np.testing.assert_array_equal(mesh["source_cell_indices"][:], source)


class TestField:
    def test_3d_roundtrip(self, sz):
        rng = np.random.default_rng(42)
        n_ts, n_lay, n_cells = 5, 3, 100
        for t in range(n_ts):
            vals = rng.random((n_lay, n_cells))
            sz.write_field("head", t, vals, n_timesteps=n_ts if t == 0 else None)
        result = sz.read_field("head", 2)
        assert result.shape == (n_lay, n_cells)

    def test_2d_field_in_subgroup(self, sz):
        rng = np.random.default_rng(7)
        n_ts, n_cells = 3, 100
        for t in range(n_ts):
            vals = rng.random(n_cells)
            sz.write_field(
                "watertable_depth", t, vals,
                n_timesteps=n_ts if t == 0 else None,
                subgroup="derived",
            )
        result = sz.read_field("watertable_depth", 1, subgroup="derived")
        assert result.shape == (n_cells,)

    def test_missing_n_timesteps_raises(self, sz):
        with pytest.raises(ValueError, match="n_timesteps required"):
            sz.write_field("head", 0, np.zeros((3, 100)))

    def test_read_with_layer(self, sz):
        n_ts, n_lay, n_cells = 2, 3, 100
        vals = np.ones((n_lay, n_cells))
        sz.write_field("head", 0, vals, n_timesteps=n_ts)
        result = sz.read_field("head", 0, layer=1)
        assert result.shape == (n_cells,)

    def test_auto_search_derived(self, sz):
        n_ts, n_cells = 2, 100
        vals = np.ones(n_cells)
        sz.write_field("wt", 0, vals, n_timesteps=n_ts, subgroup="derived")
        result = sz.read_field("wt", 0)
        assert result.shape == (n_cells,)

    def test_read_missing_variable_raises(self, sz):
        with pytest.raises(KeyError):
            sz.read_field("nonexistent", 0)

    def test_3d_shape_rejected(self, sz):
        with pytest.raises(ValueError, match="1D or 2D"):
            sz.write_field("bad", 0, np.zeros((2, 3, 4)), n_timesteps=1)


class TestGeographicRaster:
    def test_write_read_roundtrip(self, sz):
        rng = np.random.default_rng(99)
        data = rng.random((50, 60))
        transform = (10.0, 0.0, 500000.0, 0.0, -10.0, 6800000.0)
        sz.write_geographic_raster("dem", data, transform=transform, crs="EPSG:2154")
        result_data, meta = sz.read_geographic_raster("dem")
        np.testing.assert_array_equal(result_data, data)
        assert meta["crs"] == "EPSG:2154"
        assert meta["transform"] == transform
        assert meta["nodata"] == -99999.0

    def test_read_missing_raises(self, sz):
        with pytest.raises(KeyError):
            sz.read_geographic_raster("nonexistent")


class TestContextManager:
    def test_enter_exit(self, tmp_path):
        path = tmp_path / "ctx.zarr"
        with SimulationZarr.create(path, n_cells=10, n_layers=1) as s:
            assert "mesh" in s.root
