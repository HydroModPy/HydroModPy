"""A run places its field values on its own mesh, not on the DEM pixels.

``Run.field(bbox=)`` and the xarray reader select the cells whose centre lies in
the box, the centres being the ones of ``run.mesh``. The default GeoTIFF
resolution is the side of the smallest cell of that mesh. Neither reads the DEM
grid of the catalog, which a mesh is not obliged to follow.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.config_kit.export_spec import ExportRequest
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.run import Run
from hydromodpy.results.run.contracts import Mesh, polygon_areas
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

LAMBERT_X0, LAMBERT_Y0, CELL = 385_050.0, 6_814_050.0, 75.0


@pytest.fixture
def project(tmp_path) -> Path:
    return tmp_path / "workspace"


@contextmanager
def _sealed(
    project: Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    values: np.ndarray,
    *,
    structured_shape: tuple[int, int] | None = None,
    dem_shape: tuple[int, int] | None = None,
) -> Iterator[tuple[Catalog, str]]:
    """Seal a one-period run on the given mesh, with an optional DEM grid of its own.

    Yields the catalog of the project, indexed with the run, and the id of the run.
    """
    name = f"run{len(list(project.glob('runs/*')))}" if project.exists() else "run0"
    store = open_run_store(
        project,
        name,
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
            sid,
            {"dem_res": 50.0, "nrow": nrow, "ncol": ncol, "crs_proj": "EPSG:2154"},
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


def _lambert_grid(nrow: int, ncol: int) -> tuple[np.ndarray, np.ndarray]:
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


def _irregular_mesh() -> tuple[np.ndarray, np.ndarray]:
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


def test_bbox_selects_the_cells_of_an_irregular_mesh(project) -> None:
    vertices, faces = _irregular_mesh()
    values = np.arange(1.0, 7.0)
    # The DEM grid has as many pixels as the mesh has cells, 2 x 3 = 6, at other places.
    with _sealed(project, vertices, faces, values, dem_shape=(2, 3)) as (catalog, sid):
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

        masked = run.field("head", 0, bbox=box)
        np.testing.assert_array_equal(np.isfinite(masked[0]), inside)
        np.testing.assert_array_equal(masked[0][inside], values[inside])

        dataset = run.array.to_xarray_batch(("head",), bbox=box)
        assert dataset.sizes["cell"] == inside.sum()
        np.testing.assert_array_equal(dataset["head"].values.reshape(-1), values[inside])


def test_bbox_on_a_grid_of_pixels_keeps_the_pixel_rule(project) -> None:
    nrow, ncol = 4, 5
    vertices, faces = _lambert_grid(nrow, ncol)
    values = np.arange(nrow * ncol, dtype=float)
    with _sealed(project, vertices, faces, values, structured_shape=(nrow, ncol)) as (catalog, sid):
        run = Run(sid, catalog)

        # The rule of the DEM lattice: pixel (i, j) is centred at (xmin + (j + .5) cs, ymax - (i + .5) cs).
        cols, rows = np.meshgrid(np.arange(ncol), np.arange(nrow))
        xs = LAMBERT_X0 + (cols.ravel() + 0.5) * CELL
        ys = LAMBERT_Y0 + nrow * CELL - (rows.ravel() + 0.5) * CELL
        box = (LAMBERT_X0 + CELL, LAMBERT_Y0 + CELL, LAMBERT_X0 + 3.6 * CELL, LAMBERT_Y0 + 3 * CELL)
        expected = (xs >= box[0]) & (xs <= box[2]) & (ys >= box[1]) & (ys <= box[3])

        masked = run.field("head", 0, bbox=box)
        np.testing.assert_array_equal(np.isfinite(masked[0]), expected)
        assert run.mesh.structured_shape == (nrow, ncol)


def test_a_bbox_that_is_not_a_box_is_refused(project) -> None:
    vertices, faces = _irregular_mesh()
    with _sealed(project, vertices, faces, np.arange(6.0)) as (catalog, sid):
        with pytest.raises(ValueError, match="xmin<xmax"):
            Run(sid, catalog).field("head", 0, bbox=(10.0, 0.0, 0.0, 10.0))


def test_stored_face_centres_win_over_the_corner_mean() -> None:
    vertices, faces = _irregular_mesh()
    mean = Mesh(vertices, faces, np.array([1.0, 0.0])).cell_centers()
    stored_x, stored_y = mean[:, 0] + 1.0, mean[:, 1] - 2.0
    stored = Mesh(
        vertices, faces, np.array([1.0, 0.0]), face_x=stored_x, face_y=stored_y
    ).cell_centers()
    np.testing.assert_array_equal(stored, np.column_stack((stored_x, stored_y)))
    # The mean of a padded row ignores the padding.
    np.testing.assert_allclose(mean[4], vertices[[5, 6, 9], :2].mean(axis=0))


def test_areas_keep_their_precision_far_from_the_origin() -> None:
    vertices, faces = _lambert_grid(3, 3)
    np.testing.assert_array_equal(polygon_areas(vertices, faces), np.full(9, CELL * CELL))
    _, irregular = _irregular_mesh()
    areas = polygon_areas(_irregular_mesh()[0], irregular)
    triangle = 0.5 * abs((100 - 50) * (125 - 70) - (80 - 50) * (55 - 70))  # cell 4: corners 5, 6, 9
    assert areas[4] == pytest.approx(triangle)
    assert np.isnan(polygon_areas(vertices, np.array([[0, 1, -1, -1]]))[0])


def test_a_face_table_padded_with_nan_gives_the_areas_of_its_integer_twin() -> None:
    vertices, faces = _lambert_grid(2, 2)
    padded = faces.astype(float)
    padded[0, 3] = np.nan

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        areas = polygon_areas(vertices, padded)

    twin = faces.copy()
    twin[0, 3] = -1
    np.testing.assert_array_equal(areas, polygon_areas(vertices, twin))


def test_the_default_geotiff_resolution_is_the_smallest_cell(project) -> None:
    import rasterio

    vertices, faces = _irregular_mesh()
    areas = polygon_areas(vertices, faces)
    with _sealed(project, vertices, faces, np.arange(6.0)) as (catalog, sid):
        written = export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))

        with rasterio.open(written[0]) as src:
            # The exporter fits whole pixels of at most that side over the extent.
            side = np.sqrt(np.nanmin(areas))
            assert src.width == int(np.ceil(np.ptp(vertices[:, 0]) / side))
            assert src.height == int(np.ceil(np.ptp(vertices[:, 1]) / side))


def test_a_grid_of_75_m_cells_exports_at_75_m(project) -> None:
    import rasterio

    vertices, faces = _lambert_grid(4, 5)
    with _sealed(project, vertices, faces, np.arange(20.0), structured_shape=(4, 5)) as (
        catalog,
        sid,
    ):
        written = export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))

        with rasterio.open(written[0]) as src:
            assert src.res == (CELL, CELL)
            assert (src.height, src.width) == (4, 5)


def test_a_default_that_would_give_too_many_pixels_asks_for_a_resolution(project) -> None:
    # A 1 m cell in a 200 km wide domain: 4e10 pixels.
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [200_000.0, 0.0, 0.0],
            [200_000.0, 200_000.0, 0.0],
            [0.0, 200_000.0, 0.0],
        ]
    )
    faces = np.array([[0, 1, 2, 3], [1, 4, 5, 2], [3, 2, 5, 6]], dtype=np.int32)
    with _sealed(project, vertices, faces, np.arange(3.0)) as (catalog, sid):
        with pytest.raises(ValueError, match=r"resolution=") as raised:
            export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))
        assert "smallest cell" in str(raised.value)

        written = export_run(
            catalog, sid, ExportRequest(variables="head", time="2000-01-15", resolution=20_000.0)
        )
        assert written[0].exists()
