"""Point interrogation of a finished run: cell, layer, virtual fields, caches."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run.point import PointRequest, read_point, resolve_point, write_point_table
from hydromodpy.results.spatial_index import (
    CellLocator,
    cell_index_cache_dir,
    clear_locator_cache,
    point_in_cell,
)
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

# A 2x2 grid of unit squares: cells 0..3, centers at (0.5, 0.5) ... (1.5, 1.5).
VERTICES = np.array(
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
CONNECTIVITY = np.array(
    [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]],
    dtype="int32",
)
N_CELLS = 4
N_LAYERS = 2
N_STEPS = 3


def _make_run(root: Path, *, name: str = "probe", offset: float = 0.0) -> str:
    """Seal one transient two-layer run whose head is a known function; return its id."""
    store = open_run_store(
        root,
        name,
        n_cells=N_CELLS,
        n_layers=N_LAYERS,
        n_timesteps=N_STEPS,
        flow_regime="transient",
        bbox=(0.0, 0.0, 2.0, 2.0),
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
    )
    sid = store.sim_id
    store_zarr = store.open_zarr(sid)
    try:
        store_zarr.write_mesh(
            VERTICES,
            CONNECTIVITY,
            np.array([10.0, 5.0, 0.0]),
            topography=np.full(N_CELLS, 10.0),
            layer_thickness=np.full((N_LAYERS, N_CELLS), 5.0),
        )
    finally:
        store_zarr.close()
    store.write_time(
        sid,
        np.array([1577836800, 1577923200, 1578009600], dtype="int64"),
        units="seconds since 1970-01-01T00:00:00Z",
    )
    for step in range(N_STEPS):
        head = np.array(
            [[cell + 10 * step + offset for cell in range(N_CELLS)] for _ in range(N_LAYERS)],
            dtype="float64",
        )
        head[1] -= 0.5  # a vertical gradient, so the layer choice is observable
        store.write_field(sid, "head", step, head, n_timesteps=N_STEPS if step == 0 else None)
    seal_completed(store)
    return sid


@pytest.fixture
def run(tmp_path):
    clear_locator_cache()
    root = tmp_path / "demo"
    sid = _make_run(root)
    rebuild_index(root)
    with Catalog(root) as catalog:
        yield catalog[sid]


# -- locating ---------------------------------------------------------------


class TestRequest:
    def test_coordinates_or_cell_but_not_both(self):
        with pytest.raises(ValueError, match="not both"):
            PointRequest(x=0.5, y=0.5, cell=1)

    def test_one_of_them_is_required(self):
        with pytest.raises(ValueError, match="not both"):
            PointRequest()

    def test_half_a_coordinate_is_refused(self):
        with pytest.raises(ValueError, match="both x and y"):
            PointRequest(x=0.5, cell=None)

    def test_layer_and_depth_are_exclusive(self):
        with pytest.raises(ValueError, match="not both"):
            PointRequest(cell=0, layer=1, depth=2.0)


class TestResolve:
    def test_an_out_of_range_cell_is_refused(self, run):
        with pytest.raises(IndexError, match="out of range"):
            resolve_point(run, PointRequest(cell=99))

    def test_a_negative_layer_counts_from_the_bottom(self, run):
        assert resolve_point(run, PointRequest(cell=0, layer=-1)).layer == 1


# -- reading ----------------------------------------------------------------


class TestReadPoint:
    def test_one_timestep_returns_one_row(self, run):
        frame = run.probe.series("head", cell=1, timestep=-1)
        assert len(frame) == 1
        assert frame["timestep"].iloc[0] == N_STEPS - 1

    def test_an_out_of_range_timestep_is_refused(self, run):
        with pytest.raises(IndexError, match="out of range"):
            run.probe.series("head", cell=1, timestep=9)

    def test_an_unknown_field_is_named(self, run):
        with pytest.raises(KeyError, match="nosuchfield"):
            run.probe.series("nosuchfield", cell=0)


class TestWriteTable:
    def test_csv_round_trips(self, run, tmp_path):
        import pandas as pd

        dest = write_point_table(run.probe.series("head", cell=1), tmp_path / "p.csv")
        assert pd.read_csv(dest)["value"].tolist() == [1.0, 11.0, 21.0]

    def test_parquet_round_trips(self, run, tmp_path):
        import pandas as pd

        dest = write_point_table(run.probe.series("head", cell=1), tmp_path / "p.parquet")
        assert pd.read_parquet(dest)["value"].tolist() == [1.0, 11.0, 21.0]

    def test_the_output_argument_writes_and_still_returns(self, run, tmp_path):
        dest = tmp_path / "out.csv"
        frame = run.probe.series("head", cell=1, output=dest)
        assert dest.is_file()
        assert len(frame) == N_STEPS

    def test_an_unknown_extension_is_refused(self, run, tmp_path):
        with pytest.raises(ValueError, match="use .csv or .parquet"):
            write_point_table(run.probe.series("head", cell=1), tmp_path / "p.xlsx")


# -- several runs at once ---------------------------------------------------


def test_a_runset_reads_the_same_point_on_every_run(tmp_path):
    clear_locator_cache()
    root = tmp_path / "demo"
    _make_run(root, name="base")
    _make_run(root, name="scenario", offset=100.0)
    rebuild_index(root)
    with Catalog(root) as catalog:
        frame = catalog.find(project="demo").probe.series("head", cell=1)
    assert set(frame["run"]) == {"base", "scenario"}


# -- the point-to-cell caches -----------------------------------------------


class TestLocatorCache:
    def test_a_cached_point_never_builds_the_tree(self, tmp_path):
        warm = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        warm.locate({"p": (1.5, 0.5)})
        cold = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        assert cold.locate({"p": (1.5, 0.5)}) == {"p": 1}
        assert cold._tree is None

    def test_a_point_outside_is_cached_as_outside(self, tmp_path):
        locator = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        assert locator.locate({"p": (9.0, 9.0)}, warn_outside=False) == {"p": None}
        cold = CellLocator(VERTICES, CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c")
        assert cold.locate({"p": (9.0, 9.0)}, warn_outside=False) == {"p": None}

    def test_a_run_populates_the_project_cache(self, run):
        run.probe.series("head", x=1.5, y=0.5)
        cache_dir = cell_index_cache_dir(run._catalog.project_path)
        assert list(cache_dir.glob("*.json"))

    def test_the_free_function_still_answers(self):
        assert point_in_cell(VERTICES, CONNECTIVITY, {"p": (0.5, 1.5)}) == {"p": 2}

    def test_a_point_outside_warns(self):
        with pytest.warns(UserWarning, match="outside the mesh"):
            point_in_cell(VERTICES, CONNECTIVITY, {"p": (9.0, 9.0)})
