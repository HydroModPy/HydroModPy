"""A ``Run`` reads its record from the run directory, or from the index once sealed.

Series are in m3/s, boxes and cell centres in m (Lambert-93). A running run reads its rows
without the index, a sealed one reads them through the catalog, and both give the same windows.
``Run.field(bbox=)`` keeps the cells whose centre lies in the box.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.record.manifest import InputEntry, read_manifest
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import list_trash
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import make_project, seal_run

LAMBERT_X0, LAMBERT_Y0, CELL = 385_050.0, 6_814_050.0, 75.0
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


@pytest.fixture
def no_index(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a run step opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)


def monthly_store(project: Path) -> RunStore:
    """A running run of three monthly steps with a simulated and an observed discharge."""
    store = open_run_store(
        project,
        "monthly",
        n_timesteps=3,
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_timeseries(sid, "J0014010", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS))
    store.write_timeseries(
        sid, "J0014010", "discharge", pd.Series([1.5, 2.5], index=STAMPS[:2]), source="observed"
    )
    store.write_budgets(
        sid,
        [
            {"timestep": t, "zone_id": "catchment", "component": "drain", "flux_out": 1.0 + t}
            for t in range(3)
        ],
    )
    return store


def lambert_grid(nrow, ncol):
    """A grid of 75 m cells in Lambert-93, row 0 at the north, as the regular engine writes it."""
    ys = LAMBERT_Y0 + CELL * (nrow - np.arange(nrow + 1))
    xs = LAMBERT_X0 + CELL * np.arange(ncol + 1)
    vertices = np.array([[x, y, 0.0] for y in ys for x in xs])
    node = np.arange((nrow + 1) * (ncol + 1)).reshape(nrow + 1, ncol + 1)
    faces = np.array(
        [
            [node[i, j], node[i, j + 1], node[i + 1, j + 1], node[i + 1, j]]
            for i in range(nrow)
            for j in range(ncol)
        ],
        dtype=np.int32,
    )
    return vertices, faces


def irregular_mesh():
    """Six cells of 3, 4 and 5 corners, padded with -1, none on a pixel lattice."""
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [40.0, 0.0, 0.0],
            [90.0, 10.0, 0.0],
            [140.0, 0.0, 0.0],
            [0.0, 60.0, 0.0],
            [50.0, 70.0, 0.0],
            [100.0, 55.0, 0.0],
            [150.0, 65.0, 0.0],
            [20.0, 120.0, 0.0],
            [80.0, 125.0, 0.0],
            [140.0, 120.0, 0.0],
        ]
    )
    faces = np.array(
        [
            [0, 1, 5, 4, -1],
            [1, 2, 6, 5, -1],
            [2, 3, 7, 6, -1],
            [4, 5, 9, 8, -1],
            [5, 6, 9, -1, -1],
            [6, 7, 10, 9, -1],
        ],
        dtype=np.int32,
    )
    return vertices, faces


@contextmanager
def sealed_on_mesh(
    project: Path, vertices, faces, values, *, structured_shape=None, dem_shape=None
) -> Iterator[tuple[Catalog, str]]:
    """Seal a one-period run on the given mesh, with an optional DEM grid of its own."""
    store = open_run_store(
        project,
        "run0",
        n_cells=len(faces),
        n_layers=1,
        n_timesteps=1,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 2, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    zarr_store = store.open_zarr(sid)
    try:
        zarr_store.write_mesh(
            vertices, faces, np.array([10.0, 0.0]), structured_shape=structured_shape
        )
    finally:
        zarr_store.close()
    store.write_time(sid, np.array(["2000-02-01"], dtype="datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    store.write_field(sid, "head", 0, values.reshape(1, -1), n_timesteps=1)
    if dem_shape is not None:
        nrow, ncol = dem_shape
        store.write_geographic_metadata(
            sid, {"dem_res": 50.0, "nrow": nrow, "ncol": ncol, "crs_proj": "EPSG:2154"}
        )
        store.write_geographic_raster(
            sid,
            "watershed_dem",
            np.full((nrow, ncol), 100.0),
            transform=(50.0, 0.0, 0.0, 0.0, -50.0, 500.0),
            crs="EPSG:2154",
            nodata=-9999.0,
        )
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


def test_running_run_reads_directory(tmp_path, no_index):
    with monthly_store(tmp_path / "p") as store:
        run = Run(store.sim_id, store)

        assert run.status == "running"
        assert run.n_timesteps == 3
        assert run.stations("discharge") == ["J0014010"]
        assert run.timeseries("discharge").tolist() == [1.0, 2.0, 3.0]
        assert run.timeseries("discharge", period=("2000-02-15", "2000-04-30")).tolist() == [
            2.0,
            3.0,
        ]
        assert run.observed("discharge")["value"].tolist() == [1.5, 2.5]
        assert run.budget(component="drain")["flux_out"].tolist() == [1.0, 2.0, 3.0]
        assert run.has_table("budgets") and not run.has_table("mass_balance")
        assert list(run.periods.edges) == list(
            pd.to_datetime(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
        )
        assert run.periods.step_at("2000-02-15") == 1


# (window, simulated values, observed values)
WINDOWS = [
    pytest.param(("2000-02-01", "2000-03-01"), [2.0], [1.5], id="one stamp"),
    pytest.param(("2000-02-15", "2000-02-20"), [2.0], [1.5], id="inside a period"),
    pytest.param(("2000-01-01", "2000-02-01"), [1.0], [], id="first period, no observation"),
    pytest.param(("2000-01-01", "2000-01-01"), [1.0], [], id="empty window on a start"),
    pytest.param(("2000-03-01", "2000-03-01"), [2.0], [1.5], id="empty window on a stamp"),
    pytest.param("2000", [1.0, 2.0, 3.0], [1.5, 2.5], id="whole year"),
]


@pytest.mark.parametrize(("window", "simulated", "observed"), WINDOWS)
def test_window_in_every_reader(tmp_path, window, simulated, observed):
    store = monthly_store(tmp_path / "p")
    kept = store.query_timeseries(store.sim_id, "J0014010", "discharge", window)
    assert kept.tolist() == simulated
    run_dir = store.run_dir
    seal_completed(store)
    run = hmp.open(run_dir)
    rebuild_index(tmp_path / "p")

    assert run.read("discharge", sel={"period": window}).tolist() == simulated
    assert run.timeseries("discharge", period=window).tolist() == simulated
    with Catalog(tmp_path / "p") as catalog:
        read = catalog.query_timeseries(run.sim_id, "J0014010", "discharge", period=window)
        assert read.tolist() == simulated
    if observed:
        assert run.timeseries("discharge", period=window, source="observed").tolist() == observed
        assert run.observed("discharge", period=window)["value"].tolist() == observed
    else:
        with pytest.raises(ValueError, match="No observations"):
            run.observed("discharge", period=window)


def test_late_table_keeps_licence(tmp_path):
    store = monthly_store(tmp_path / "p")
    store.record_input(
        store.sim_id,
        InputEntry(
            variable="discharge:J0014010",
            provider="hubeau",
            path="data/hubeau/discharge.csv",
            license="etalab-2.0",
        ),
    )
    run_dir = store.run_dir
    seal_completed(store)
    close_sealed_attempt(run_dir)
    sealed_licence = read_manifest(run_dir)["run"]["license"]

    with RunStore.open(run_dir) as reopened:
        reopened.write_view(
            reopened.sim_id,
            "observation_points",
            [{"station_id": "p1", "x": 0.0, "y": 0.0, "cell_id": 0, "layer": 0}],
        )
        footer = read_kv_metadata(reopened.table_path_for(reopened.sim_id, "observation_points"))

    assert sealed_licence not in (None, "", "LicenseRef-undetermined")
    assert footer["license"] == sealed_licence


def test_tags_notes_and_delete(tmp_path):
    project = tmp_path / "p"
    store = monthly_store(project)
    run_dir, sid = store.run_dir, store.sim_id
    seal_completed(store)
    close_sealed_attempt(run_dir)

    with RunStore.open(run_dir) as sealed:
        run = Run(sid, sealed)
        run.tag("keep", "+pinned", "-keep")
        run.note("best fit")

        payload = json.loads((run_dir / "annotations.json").read_text(encoding="utf-8"))
        assert payload["sim_id"] == sid
        assert payload["tags"] == ["pinned"]
        assert [note["note"] for note in payload["notes"]] == ["best fit"]
        assert run.tags == ["pinned"]

    with RunStore.open(run_dir) as sealed:
        run = Run(sid, sealed)
        run.tag("-pinned")
        run.delete()

    assert not run_dir.exists()
    assert [entry.rel_dir for entry in list_trash(project)] == ["runs/monthly"]


def test_long_layer_name_listed_whole(tmp_path, no_index):
    import geopandas as gpd
    from shapely.geometry import LineString

    # The listing reads the name from the file name, so it is not cut to 32 characters.
    name = "hydrographic_network_reference_permanent"
    layer = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])], crs="EPSG:2154")
    with open_run_store(tmp_path / "p", "layers") as store:
        store.write_geographic_feature(store.sim_id, name, layer)

        assert store.list_geographic_features(store.sim_id) == [name]
        assert len(Run(store.sim_id, store).hydrographic_network("reference_permanent")) == 1


# A Project closes its catalog at the end of its with block. A Run taken from it
# reopens a reader on the same index instead of failing with a closed connection.
def test_two_readers_of_one_index_coexist(tmp_path):
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "x")
    rebuild_index(root)
    first = Catalog(root)
    run = Run(sid, first)
    first.close()
    assert run.name == "x"
    reader = Catalog(root)
    assert reader[sid].name == "x"
    reader.close()
    run._catalog.close()


def test_bbox_on_irregular_mesh(project):
    vertices, faces = irregular_mesh()
    values = np.arange(1.0, 7.0)
    # The DEM grid has as many pixels as the mesh has cells, 2 x 3 = 6, at other places.
    with sealed_on_mesh(project, vertices, faces, values, dem_shape=(2, 3)) as (catalog, sid):
        run = Run(sid, catalog)

        box = (0.0, 0.0, 100.0, 70.0)
        centers = run.mesh.cell_centers()
        inside = (
            (centers[:, 0] >= box[0])
            & (centers[:, 0] <= box[2])
            & (centers[:, 1] >= box[1])
            & (centers[:, 1] <= box[3])
        )
        assert 0 < inside.sum() < len(values)

        masked = run.field("head", time=0, bbox=box)
        np.testing.assert_array_equal(np.isfinite(masked[0]), inside)
        np.testing.assert_array_equal(masked[0][inside], values[inside])

        dataset = run.array.to_xarray_batch(("head",), bbox=box)
        assert dataset.sizes["cell"] == inside.sum()
        np.testing.assert_array_equal(dataset["head"].values.reshape(-1), values[inside])


def test_bbox_on_pixel_grid(project):
    nrow, ncol = 4, 5
    vertices, faces = lambert_grid(nrow, ncol)
    values = np.arange(nrow * ncol, dtype=float)
    with sealed_on_mesh(project, vertices, faces, values, structured_shape=(nrow, ncol)) as (
        catalog,
        sid,
    ):
        run = Run(sid, catalog)

        # Pixel (i, j) is centred at (xmin + (j + .5) cs, ymax - (i + .5) cs).
        cols, rows = np.meshgrid(np.arange(ncol), np.arange(nrow))
        xs = LAMBERT_X0 + (cols.ravel() + 0.5) * CELL
        ys = LAMBERT_Y0 + nrow * CELL - (rows.ravel() + 0.5) * CELL
        box = (LAMBERT_X0 + CELL, LAMBERT_Y0 + CELL, LAMBERT_X0 + 3.6 * CELL, LAMBERT_Y0 + 3 * CELL)
        expected = (xs >= box[0]) & (xs <= box[2]) & (ys >= box[1]) & (ys <= box[3])

        masked = run.field("head", time=0, bbox=box)
        np.testing.assert_array_equal(np.isfinite(masked[0]), expected)
        assert run.mesh.structured_shape == (nrow, ncol)


def test_bbox_refusal(project):
    vertices, faces = irregular_mesh()
    with sealed_on_mesh(project, vertices, faces, np.arange(6.0)) as (catalog, sid):
        with pytest.raises(ValueError, match="xmin<xmax"):
            Run(sid, catalog).field("head", time=0, bbox=(10.0, 0.0, 0.0, 10.0))
