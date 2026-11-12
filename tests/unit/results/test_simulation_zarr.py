"""The Zarr field store of one run: cells by layers, timed fields, mesh and CF metadata.

Field values are per cell and per layer, time axes follow CF conventions
(``units = "<unit> since <epoch>"``). A chunk targets about 1 MiB.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr


@pytest.fixture
def sz(tmp_path):
    store = SimulationZarr.create(tmp_path / "test_sim.zarr", n_cells=100, n_layers=3)
    yield store
    store.close()


def square_block_mesh():
    """Four unit squares (m) in a 2 x 2 block, with the interfaces of three layers (m)."""
    vertices = np.array([[x, y] for y in range(3) for x in range(3)], dtype="float64")
    connectivity = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
    z_interfaces = np.array([0.0, -5.0, -15.0, -30.0], dtype="float64")
    return vertices, connectivity, z_interfaces


class TimeAxis:
    """A stored ``time`` array with its CF units, enough for ``read_time``."""

    def __init__(self, values, units):
        self._values = np.asarray(values)
        self.attrs = {"units": units}

    def __getitem__(self, key):
        return self._values[key]


def zarr_with_time_axis(values, units="seconds since 1970-01-01"):
    # Only the root is touched by read_time, so the store is built without a file.
    store = object.__new__(SimulationZarr)
    store._root = {"time": TimeAxis(values, units)}
    return store


def test_cell_types_are_stored(tmp_path):
    s = SimulationZarr.create(
        tmp_path / "typed.zarr", n_cells=10, n_layers=1, cell_types=["triangle"]
    )

    assert s.root.attrs["cell_types"] == ["triangle"]
    s.close()


def test_close_releases_the_root(tmp_path):
    path = tmp_path / "closed.zarr"
    target = tmp_path / "renamed.zarr"
    s = SimulationZarr.create(path, n_cells=5, n_layers=2)
    s.close()

    assert s._root is None
    with pytest.raises(RuntimeError, match="closed"):
        _ = s.root
    path.rename(target)
    assert target.exists()


def test_optional_mesh_arrays(sz):
    vertices, connectivity, z_interfaces = square_block_mesh()
    layers = np.array([0, 0, 1, 1], dtype="int32")
    source = np.array([0, 1, 0, 1], dtype="int32")

    sz.write_mesh(
        vertices, connectivity, z_interfaces, layer_indices=layers, source_cell_indices=source
    )

    mesh = sz.root["mesh"]
    np.testing.assert_array_equal(mesh["layer_indices"][:], layers)
    np.testing.assert_array_equal(mesh["source_cell_indices"][:], source)


def test_days_since_epoch_are_decoded():
    store = zarr_with_time_axis([0, 1, 2], units="days since 1970-01-01")

    index = pd.DatetimeIndex(store.read_time())

    assert list(index.strftime("%Y-%m-%d")) == ["1970-01-01", "1970-01-02", "1970-01-03"]


def test_a_missing_or_empty_time_axis_reads_none():
    without_axis = object.__new__(SimulationZarr)
    without_axis._root = {}

    assert without_axis.read_time() is None
    assert zarr_with_time_axis([]).read_time() is None


def test_to_xarray_holds_the_registered_variables(sz):
    sz.write_field("head", 0, np.ones((3, 100)), n_timesteps=1)
    sz.write_field("watertable_depth", 0, np.ones(100), n_timesteps=1, subgroup="derived")

    ds = sz.to_xarray()

    assert "head" in ds.data_vars
    assert "watertable_depth" in ds.data_vars
    assert ds.attrs["Conventions"] == "CF-1.11, ACDD-1.3, UGRID-1.0"


def test_cf_attributes_survive_the_round_trip(sz):
    sz.write_field("head", 0, np.ones((3, 100)), n_timesteps=1)

    ds = sz.to_xarray()

    assert ds["head"].attrs["csdms_standard_name"] == "subsurface_water__hydraulic_head"
    assert ds["head"].attrs["units"] == "m"


def test_balanced_chunks_pack_several_timesteps(tmp_path):
    s = SimulationZarr.create(tmp_path / "bal.zarr", n_cells=100, n_layers=2)
    try:
        s.write_field("head", 0, np.ones((2, 100)), n_timesteps=10)
        # 2 * 100 * 8 B = 1.6 kB per timestep, so all 10 fit in one chunk of about 1 MiB.
        assert s.root["head"].chunks[0] > 1
        assert s.root.attrs.get("chunking") == "balanced"
    finally:
        s.close()


def test_consolidated_metadata_leaves_its_sentinel(tmp_path):
    path = tmp_path / "cons.zarr"
    s = SimulationZarr.create(path, n_cells=10, n_layers=1)
    try:
        s.write_field("head", 0, np.ones((1, 10)), n_timesteps=1)
        s.consolidate_metadata()
    finally:
        s.close()

    # zarr v3 drops the consolidated metadata into zarr.json
    assert (path / "zarr.json").is_file()


MASK_REFUSALS = [
    pytest.param(np.zeros(3, dtype=bool), id="wrong size"),
    pytest.param(np.zeros((2, 4), dtype=bool), id="not flat"),
]


@pytest.mark.parametrize("mask", MASK_REFUSALS)
def test_a_criterion_mask_that_does_not_fit_the_mesh_is_refused(sz, mask):
    sz.write_mesh(*square_block_mesh())

    with pytest.raises(ValueError, match="one value per cell"):
        sz.write_criterion_cells(open_water=mask)


FIELD_REFUSALS = [
    pytest.param(np.zeros((3, 100)), None, "n_timesteps required", id="no n_timesteps"),
    pytest.param(np.zeros((2, 3, 4)), 1, "1D or 2D", id="three dimensions"),
]


@pytest.mark.parametrize(("values", "n_timesteps", "match"), FIELD_REFUSALS)
def test_a_field_that_does_not_fit_is_refused(sz, values, n_timesteps, match):
    with pytest.raises(ValueError, match=match):
        sz.write_field("bad", 0, values, n_timesteps=n_timesteps)


def test_reading_a_missing_raster_is_refused(sz):
    with pytest.raises(KeyError):
        sz.read_geographic_raster("nonexistent")
