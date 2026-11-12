from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr


@pytest.fixture
def sz(tmp_path):
    path = tmp_path / "test_sim.zarr"
    store = SimulationZarr.create(path, n_cells=100, n_layers=3)
    yield store
    store.close()


def _make_mesh(n_cells=6):
    vertices = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [2.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [2.0, 1.0],
            [0.0, 2.0],
            [1.0, 2.0],
            [2.0, 2.0],
        ],
        dtype="float64",
    )
    connectivity = np.array(
        [
            [0, 1, 4, 3],
            [1, 2, 5, 4],
            [3, 4, 7, 6],
            [4, 5, 8, 7],
            [0, 1, 4, -1],
            [4, 5, 8, -1],
        ],
        dtype="int32",
    )
    z_interfaces = np.array([0.0, -5.0, -15.0, -30.0], dtype="float64")
    return vertices, connectivity[:n_cells], z_interfaces


class TestCreate:
    def test_cell_types_stored(self, tmp_path):
        path = tmp_path / "typed.zarr"
        s = SimulationZarr.create(path, n_cells=10, n_layers=1, cell_types=["triangle"])
        assert s.root.attrs["cell_types"] == ["triangle"]
        s.close()

    def test_close_releases_root_reference(self, tmp_path):
        path = tmp_path / "closed.zarr"
        target = tmp_path / "renamed.zarr"
        s = SimulationZarr.create(path, n_cells=5, n_layers=2)
        s.close()
        assert s._root is None
        with pytest.raises(RuntimeError, match="closed"):
            _ = s.root
        path.rename(target)
        assert target.exists()


class TestMesh:
    def test_optional_arrays(self, sz):
        verts, conn, z = _make_mesh(4)
        layers = np.array([0, 0, 1, 1], dtype="int32")
        source = np.array([0, 1, 0, 1], dtype="int32")
        sz.write_mesh(verts, conn, z, layer_indices=layers, source_cell_indices=source)
        mesh = sz.root["mesh"]
        np.testing.assert_array_equal(mesh["layer_indices"][:], layers)
        np.testing.assert_array_equal(mesh["source_cell_indices"][:], source)


class TestCriterionCells:
    """The two per-face masks the stream criterion read are kept beside the mesh."""

    @staticmethod
    def _water(n: int) -> np.ndarray:
        mask = np.zeros(n, dtype=bool)
        mask[[1, 2]] = True
        return mask

    @pytest.mark.parametrize(
        ("values", "match"),
        [
            (np.zeros(3, dtype=bool), "one value per cell"),
            (np.zeros((2, 4), dtype=bool), "one value per cell"),
        ],
        ids=["wrong size", "not flat"],
    )
    def test_a_mask_that_does_not_fit_the_stored_mesh_is_refused(self, sz, values, match):
        verts, conn, z = _make_mesh(4)
        sz.write_mesh(verts, conn, z)

        with pytest.raises(ValueError, match=match):
            sz.write_criterion_cells(open_water=values)


class TestField:
    def test_missing_n_timesteps_raises(self, sz):
        with pytest.raises(ValueError, match="n_timesteps required"):
            sz.write_field("head", 0, np.zeros((3, 100)))

    def test_3d_shape_rejected(self, sz):
        with pytest.raises(ValueError, match="1D or 2D"):
            sz.write_field("bad", 0, np.zeros((2, 3, 4)), n_timesteps=1)


class TestGeographicRaster:
    def test_read_missing_raises(self, sz):
        with pytest.raises(KeyError):
            sz.read_geographic_raster("nonexistent")


class TestG05ToXarray:
    """Phase G05: SimulationZarr.to_xarray()."""

    def test_dataset_has_registered_vars(self, sz):
        sz.write_field("head", 0, np.ones((3, 100)), n_timesteps=1)
        sz.write_field(
            "watertable_depth",
            0,
            np.ones(100),
            n_timesteps=1,
            subgroup="derived",
        )
        ds = sz.to_xarray()
        assert "head" in ds.data_vars
        assert "watertable_depth" in ds.data_vars
        assert ds.attrs["Conventions"] == "CF-1.11, ACDD-1.3, UGRID-1.0"

    def test_cf_attrs_survive_round_trip(self, sz):
        sz.write_field("head", 0, np.ones((3, 100)), n_timesteps=1)
        ds = sz.to_xarray()
        assert ds["head"].attrs["csdms_standard_name"] == "subsurface_water__hydraulic_head"
        assert ds["head"].attrs["units"] == "m"


class TestG05BalancedChunking:
    def test_balanced_chunks_pack_multiple_timesteps(self, tmp_path):
        path = tmp_path / "bal.zarr"
        s = SimulationZarr.create(
            path,
            n_cells=100,
            n_layers=2,
        )
        try:
            s.write_field("head", 0, np.ones((2, 100)), n_timesteps=10)
            # 2 * 100 * 8 = 1.6KB; target ~1MiB -> all 10 timesteps fit in a
            # single chunk.
            assert s.root["head"].chunks[0] > 1
            assert s.root.attrs.get("chunking") == "balanced"
        finally:
            s.close()

    def test_consolidate_metadata_writes_sentinel(self, tmp_path):
        path = tmp_path / "cons.zarr"
        s = SimulationZarr.create(path, n_cells=10, n_layers=1)
        try:
            s.write_field("head", 0, np.ones((1, 10)), n_timesteps=1)
            s.consolidate_metadata()
        finally:
            s.close()
        # zarr v3 drops the consolidated metadata into zarr.json
        assert (path / "zarr.json").is_file()
