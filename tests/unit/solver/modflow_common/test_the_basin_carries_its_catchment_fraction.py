"""The basin of D carries the share of each cell inside the catchment polygon (D08).

The basin stays a hydraulic, all-or-nothing set of cells: the fraction never
changes which cells drain to the outlet. It travels with the basin from the
build to the sidecar and from the sidecar to ``mesh/catchment_fraction``, where
the catchment totals of a spatial quantity read it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from shapely.geometry import box

from hydromodpy.catchment.drainage.descent import DescentBasin
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow_common.catchment_basin import run_basin
from hydromodpy.solver.modflow_common.descent_store import (
    read_descent_sidecar,
    write_descent_sidecar,
    write_descent_sidecar_to_store,
)
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests._helpers.ugrid_meshes import quad_mesh

N = 10
CRS = "EPSG:2154"
# Cuts the cells of the first and last columns and rows the basin reaches.
POLYGON = box(3.0, 3.0, 47.0, 96.0)


def _mesh():
    rows, cols = np.divmod(np.arange(N * N), N)
    centre = np.where(cols < N // 2, 2, 7)
    noise = np.random.default_rng(3).uniform(0.0, 0.4, N * N)
    top = 100.0 + 0.5 * (N - 1 - rows) + np.abs(cols - centre) + noise
    return solver_mesh_from_structured_arrays(
        nrow=N, ncol=N, top=top.reshape(N, N), botm=np.full((1, N, N), -50.0), dx=10.0, dy=10.0
    )


def _catchment(tmp_path, *, polygon=POLYGON) -> CatchmentGeometry:
    import geopandas as gpd

    outlet = (2 * 10.0 + 5.0, 5.0)
    extra = {}
    if polygon is not None:
        shp = tmp_path / "watershed.gpkg"
        gpd.GeoDataFrame(geometry=[polygon], crs=CRS).to_file(shp)
        extra["watershed_shp"] = str(shp)
    geographic = SimpleNamespace(x_outlet=outlet[0], y_outlet=outlet[1], **extra)
    return CatchmentGeometry.from_geographic(geographic, crs=CRS)


def _basin(tmp_path, *, polygon=POLYGON) -> DescentBasin:
    mesh = _mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return run_basin(_catchment(tmp_path, polygon=polygon), mesh, descent)


def _overlay(polygon) -> np.ndarray:
    mesh = _mesh()
    cells = cell_polygons(
        np.asarray(mesh.planar_mesh.vertices, dtype=float),
        mesh.cell_mesh.geometry.padded_connectivity,
    )
    return shapely.area(shapely.intersection(cells, polygon)) / shapely.area(cells)


def test_the_basin_carries_the_polygon_share_of_every_cell(tmp_path) -> None:
    basin = _basin(tmp_path)

    assert basin.catchment_fraction is not None
    np.testing.assert_allclose(basin.catchment_fraction, _overlay(POLYGON), atol=1e-12)
    cut = (basin.catchment_fraction > 0.0) & (basin.catchment_fraction < 1.0)
    assert (cut & basin.mask).any()


def test_the_fraction_travels_from_the_build_to_the_store(tmp_path) -> None:
    basin = _basin(tmp_path)
    mesh = _mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    write_descent_sidecar(descent, tmp_path, "m", basin=basin)

    record = read_descent_sidecar(tmp_path / "m.descent.npz")
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N * N, n_layers=1)
    try:
        vertices, connectivity = quad_mesh(N, N, cell_size=10.0)
        store.write_mesh(vertices, connectivity, np.array([0.0, -50.0]))
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="sim", n_cells=N * N)
        stored = store.root["mesh"]["catchment_fraction"]
        values, attrs, dtype = stored[:], dict(stored.attrs), stored.dtype
    finally:
        store.close()

    assert record is not None
    np.testing.assert_array_equal(record.catchment_fraction, basin.catchment_fraction)
    assert written
    assert dtype == np.float64
    np.testing.assert_array_equal(values, basin.catchment_fraction)
    assert attrs["units"] == "1"


def _rewrite_sidecar(tmp_path, **changes) -> None:
    path = tmp_path / "m.descent.npz"
    with np.load(path, allow_pickle=False) as payload:
        arrays = {name: payload[name] for name in payload.files}
    for name, value in changes.items():
        if value is None:
            arrays.pop(name)
        else:
            arrays[name] = value
    np.savez(path, **arrays)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"catchment_fraction": np.full(N * N, 1.5)}, r"catchment fraction outside \[0, 1\]"),
        (
            {
                "basin": None,
                "basin_outlet": None,
                "basin_rule": None,
                "basin_area_m2": None,
                "basin_seeded_at_outlet": None,
            },
            "catchment fraction without a basin",
        ),
    ],
    ids=["out_of_range", "without_basin"],
)
def test_a_sidecar_fraction_that_does_not_hold_is_refused(tmp_path, changes, message) -> None:
    basin = _basin(tmp_path)
    mesh = _mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    write_descent_sidecar(descent, tmp_path, "m", basin=basin)
    _rewrite_sidecar(tmp_path, **changes)

    with pytest.raises(ValueError, match=message):
        read_descent_sidecar(tmp_path / "m.descent.npz")


@pytest.mark.parametrize(
    ("with_basin", "fraction", "message"),
    [
        (False, np.ones(N * N), "stored with the basin it weighs"),
        (True, np.ones(N * N + 1), "one value per cell"),
        (True, np.full(N * N, -0.1), r"in \[0, 1\]"),
    ],
    ids=["without_basin", "wrong_size", "negative"],
)
def test_the_store_refuses_a_fraction_that_does_not_fit(
    tmp_path, with_basin, fraction, message
) -> None:
    basin = _basin(tmp_path)
    mesh = _mesh()
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N * N, n_layers=1)
    try:
        with pytest.raises(ValueError, match=message):
            store.write_descent(
                receiver=descent.receiver,
                surface=descent.surface,
                base_level=descent.base_level,
                constant_head=descent.constant_head,
                raised=descent.raised,
                channel=descent.channel,
                pinned=descent.pinned,
                attrs={"adjacency": "shared_nodes"},
                basin=basin.mask if with_basin else None,
                basin_attrs={"descent_outlet": basin.outlet} if with_basin else None,
                catchment_fraction=fraction,
            )
    finally:
        store.close()
