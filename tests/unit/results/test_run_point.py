"""Point interrogation of a finished run: the cell and layer of a point, its series, its cache.

Coordinates are in meters of the mesh CRS and heads in meters. The head of cell
``c`` at step ``t`` is ``c + 10 t``, and layer 1 sits 0.5 m below layer 0.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run.point import PointRequest, read_point, resolve_point, write_point_table
from hydromodpy.results.spatial_index import cell_index_cache_dir, clear_locator_cache
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


REFUSED_REQUESTS = [
    pytest.param({"x": 0.5, "y": 0.5, "cell": 1}, "not both", id="coordinates and cell"),
    pytest.param({}, "not both", id="neither"),
    pytest.param({"x": 0.5, "cell": None}, "both x and y", id="half a coordinate"),
    pytest.param({"cell": 0, "layer": 1, "depth": 2.0}, "not both", id="layer and depth"),
]


@pytest.mark.parametrize(("fields", "message"), REFUSED_REQUESTS)
def test_refused_requests(fields, message):
    with pytest.raises(ValueError, match=message):
        PointRequest(**fields)


def test_an_out_of_range_cell_is_refused(run):
    with pytest.raises(IndexError, match="out of range"):
        resolve_point(run, PointRequest(cell=99))


def test_a_negative_layer_counts_from_the_bottom(run):
    assert resolve_point(run, PointRequest(cell=0, layer=-1)).layer == 1


def test_one_timestep_returns_one_row(run):
    frame = run.probe.series("head", cell=1, timestep=-1)

    assert len(frame) == 1
    assert frame["timestep"].iloc[0] == N_STEPS - 1


READ_REFUSALS = [
    pytest.param(
        {"name": "head", "cell": 1, "timestep": 9}, IndexError, "out of range", id="timestep"
    ),
    pytest.param({"name": "nosuchfield", "cell": 0}, KeyError, "nosuchfield", id="field"),
]


@pytest.mark.parametrize(("call", "error", "message"), READ_REFUSALS)
def test_read_refusals(run, call, error, message):
    name = call.pop("name")
    with pytest.raises(error, match=message):
        run.probe.series(name, **call)


@pytest.mark.parametrize(
    ("suffix", "read"),
    [
        pytest.param(".csv", pd.read_csv, id="csv"),
        pytest.param(".parquet", pd.read_parquet, id="parquet"),
    ],
)
def test_table_round_trip(run, tmp_path, suffix, read):
    dest = write_point_table(run.probe.series("head", cell=1), tmp_path / f"p{suffix}")

    assert read(dest)["value"].tolist() == [1.0, 11.0, 21.0]


def test_the_output_argument_writes_and_still_returns(run, tmp_path):
    dest = tmp_path / "out.csv"
    frame = run.probe.series("head", cell=1, output=dest)

    assert dest.is_file()
    assert len(frame) == N_STEPS


def test_an_unknown_extension_is_refused(run, tmp_path):
    with pytest.raises(ValueError, match="use .csv or .parquet"):
        write_point_table(run.probe.series("head", cell=1), tmp_path / "p.xlsx")


def test_a_runset_reads_the_same_point_on_every_run(tmp_path):
    clear_locator_cache()
    root = tmp_path / "demo"
    _make_run(root, name="base")
    _make_run(root, name="scenario", offset=100.0)
    rebuild_index(root)
    with Catalog(root) as catalog:
        frame = catalog.find(project="demo").probe.series("head", cell=1)

    assert set(frame["run"]) == {"base", "scenario"}


def test_a_run_populates_the_project_cache(run):
    run.probe.series("head", x=1.5, y=0.5)
    cache_dir = cell_index_cache_dir(run._catalog.project_path)

    assert list(cache_dir.glob("*.json"))
