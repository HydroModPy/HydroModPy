"""A property map read on the cells of a mesh, :mod:`hydromodpy.model.properties.raster_cells`.

Coordinates are in m of Lambert-93 unless a map is written in another CRS. A cell takes
the mean of the pixels it covers, whatever its shape.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import numpy as np
import pytest
import shapely
from pyproj import CRS, Transformer

from hydromodpy.catchment.surface import Surface
from hydromodpy.core.config_kit.field_param.sections import RasterMean
from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.mesh_cells import cell_mesh_from_edges
from hydromodpy.model.properties.property_table import (
    map_flow_properties,
    require_positive_conductivity,
)
from hydromodpy.model.properties.raster_cells import (
    MEANS,
    POINTS_PER_SIDE,
    points_per_side,
    raster_cells,
    read_property_maps,
)
from tests._helpers.field_cases import planar_mesh
from tests._helpers.geotiffs import write_geotiff

L93 = CRS.from_epsg(2154).to_wkt()
X0, Y0 = 350_000.0, 6_800_000.0
NODATA = -9999.0


def _map(tmp_path: Path, values, *, cell: float, origin=(X0, Y0 + 200.0), crs="EPSG:2154"):
    path = write_geotiff(
        tmp_path / "map.tif", np.asarray(values, dtype=float), origin=origin, cell=cell,
        crs=crs, nodata=NODATA, dtype="float64",
    )  # fmt: skip
    return Surface.from_raster(path, name="k_map")


def _grid(n_x: int, n_y: int, size: float):
    return cell_mesh_from_edges(
        X0 + size * np.arange(n_x + 1), Y0 + size * np.arange(n_y + 1), crs_wkt=L93
    )


SIXTEEN = np.arange(1.0, 17.0).reshape(4, 4)
"""Four rows of 50 m pixels, north first, under four cells of 100 m."""


@pytest.mark.parametrize(
    ("mean", "of"),
    [
        ("arithmetic", lambda v: np.mean(v)),
        ("geometric", lambda v: np.exp(np.mean(np.log(v)))),
        ("harmonic", lambda v: len(v) / np.sum(1.0 / np.asarray(v))),
    ],
)
def test_a_square_cell_takes_the_mean_of_its_pixels(tmp_path, mean, of):
    cells = raster_cells(
        _grid(2, 2, 100.0), _map(tmp_path, SIXTEEN, cell=50.0), mean=mean, map_name="k"
    )

    # Cell 0 is south-west, so it covers the two south rows of the map, west half.
    expected = [of([9, 10, 13, 14]), of([11, 12, 15, 16]), of([1, 2, 5, 6]), of([3, 4, 7, 8])]
    np.testing.assert_allclose(cells.values, expected, rtol=1e-12)
    assert cells.covered.all()


def _linear_map(tmp_path: Path):
    """A map of 10 m pixels whose value is the easting in m from X0, at each pixel center."""
    columns = 10.0 * np.arange(20) + 5.0
    return _map(tmp_path, np.tile(columns, (20, 1)), cell=10.0)


TRIANGLES = (
    np.array([[X0, Y0], [X0 + 200, Y0], [X0 + 200, Y0 + 200], [X0, Y0 + 200]]),
    [[0, 1, 2], [0, 2, 3]],
    CellType.TRIANGLE,
)
VORONOI = (
    np.array(
        [
            [X0 + 100, Y0],
            [X0 + 180, Y0 + 40],
            [X0 + 190, Y0 + 150],
            [X0 + 100, Y0 + 200],
            [X0 + 20, Y0 + 160],
            [X0 + 10, Y0 + 50],
            [X0, Y0 + 200],
            [X0, Y0],
        ]
    ),  # fmt: skip
    [[0, 1, 2, 3, 4, 5], [5, 4, 6, 7]],
    CellType.POLYGON,
)


@pytest.mark.parametrize("cells", [TRIANGLES, VORONOI], ids=["triangles", "voronoi-polygons"])
def test_any_cell_shape_takes_the_area_mean_of_the_map(tmp_path, cells):
    # The area mean of a field linear in x is its value at the centroid of the cell.
    vertices, rows, cell_type = cells
    mesh = planar_mesh(vertices, rows, cell_type, crs_wkt=L93)

    read = raster_cells(mesh, _linear_map(tmp_path), mean="arithmetic", map_name="k")

    centroids = [shapely.Polygon(vertices[row]).centroid.x - X0 for row in rows]
    # Within 3 % of the 200 m cells: the triangle lattice of ``cell_sampling`` leans a
    # little towards the first corner, for the zone fractions too.
    np.testing.assert_allclose(read.values, centroids, atol=6.0)


def test_a_map_in_another_crs_is_read_where_it_lies(tmp_path):
    # Four cells of 1 km along the easting, read on a map in longitude and latitude
    # whose value is 1 west of the meridian through the middle of the row, 2 east of it.
    to_lonlat = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    lon_mid, _ = to_lonlat.transform(X0 + 2000.0, Y0 + 500.0)
    west, south = to_lonlat.transform(X0 - 500.0, Y0 - 500.0)
    east, north = to_lonlat.transform(X0 + 4500.0, Y0 + 1500.0)
    step = 0.0005
    lon = west + step * (np.arange(int((east - west) / step) + 1) + 0.5)
    rows = int((north - south) / step) + 1
    values = np.tile(np.where(lon < lon_mid, 1.0, 2.0), (rows, 1))
    surface = _map(tmp_path, values, cell=step, origin=(west, north), crs="EPSG:4326")

    read = raster_cells(_grid(4, 1, 1000.0), surface, mean="arithmetic", map_name="k")

    assert read.values[0] == 1.0 and read.values[3] == 2.0


def test_a_cell_the_map_does_not_reach_holds_no_value(tmp_path):
    # The west cell lies on the map, the middle one half on nodata, the east one outside it.
    values = np.array([[4.0, 4.0, 6.0, NODATA]] * 2)
    surface = _map(tmp_path, values, cell=50.0, origin=(X0, Y0 + 100.0))

    read = raster_cells(_grid(3, 1, 100.0), surface, mean="arithmetic", map_name="k")

    np.testing.assert_allclose(read.values[:2], [4.0, 6.0])
    assert np.isnan(read.values[2])
    assert read.covered.tolist() == [True, True, False]


def test_a_geometric_mean_refuses_a_value_at_or_below_zero(tmp_path):
    surface = _map(tmp_path, np.where(SIXTEEN == 6, 0.0, SIXTEEN), cell=50.0)

    with pytest.raises(ValueError, match="at or below zero under 1 cell.s., and a geometric mean"):
        raster_cells(_grid(2, 2, 100.0), surface, mean="geometric", map_name="k")
    arithmetic = raster_cells(_grid(2, 2, 100.0), surface, mean="arithmetic", map_name="k")
    assert arithmetic.values[2] == pytest.approx(2.0)


def test_the_points_follow_the_pixels_within_their_bounds():
    mesh = _grid(2, 2, 100.0)
    assert [points_per_side(mesh, pixel) for pixel in (1000.0, 50.0, 12.5, 1.0)] == [4, 4, 16, 16]
    assert points_per_side(mesh, float("nan")) == POINTS_PER_SIDE[0]
    assert tuple(MEANS) == get_args(RasterMean)


def _raster_profile(identifier: str, map_name: str, **options) -> FieldParam:
    return FieldParam(identifier=identifier, kind="raster", raster_map=map_name, **options)


def test_the_maps_a_flow_reads_are_read_by_name(tmp_path):
    path = write_geotiff(tmp_path / "k.tif", SIXTEEN, cell=50.0)
    source = SimpleNamespace(name="k_map", path=path, default_crs="EPSG:2154")
    data = SimpleNamespace(property_map=SimpleNamespace(sources=[source]))
    profiles = {"K": _raster_profile("K", "k_map"), "Sy": FieldParam(identifier="Sy", kind="homogeneous", value=0.1)}  # fmt: skip

    maps = read_property_maps(profiles, data)

    assert list(maps) == ["k_map"]
    np.testing.assert_array_equal(maps["k_map"].as_array(), SIXTEEN)
    assert read_property_maps({"Sy": profiles["Sy"]}, None) == {}
    with pytest.raises(ConfigError, match=r"flow.param.Ss reads the map\(s\) \['ss_map'\]"):
        read_property_maps({"Ss": _raster_profile("Ss", "ss_map")}, data)


def test_a_raster_profile_gives_the_cells_their_value_in_si(tmp_path):
    # A conductivity is averaged geometrically, a storage arithmetically, unless told.
    assert _raster_profile("K", "k").mean == "geometric"
    assert _raster_profile("Sy", "s").mean == "arithmetic"
    assert _raster_profile("K", "k", mean="harmonic").mean == "harmonic"
    mesh = _grid(2, 1, 100.0)
    surface = _map(tmp_path, [[8.64, 8.64, NODATA, NODATA]] * 2, cell=50.0, origin=(X0, Y0 + 100.0))
    profile = _raster_profile("K", "k_map", unit="m/day").reading(surface)

    cells = raster_cells(mesh, profile.raster_surface, mean=profile.mean, map_name="k_map")
    field = profile.to_mesh_field(cells, depth=0.0)

    # The uncovered cell holds 0, which the solver refuses on an active cell.
    np.testing.assert_allclose(field.cell_values, [1e-4, 0.0])
    assert profile.as_dict() == {"id": "K", "kind": "raster", "unit": "m/s", "map": "k_map", "mean": "geometric", "original_unit": "m/day"}  # fmt: skip
    with pytest.raises(ValueError, match="only a mesh reads"):
        profile.to_array(shape=(2,))


def test_an_active_cell_off_the_map_is_refused_by_name(tmp_path):
    # The map covers the west cell only, so the east one holds K = 0 and is refused.
    surface = _map(tmp_path, [[8.64, 8.64, NODATA, NODATA]] * 2, cell=50.0, origin=(X0, Y0 + 100.0))
    profiles = {"K": _raster_profile("K", "k_map", unit="m/day").reading(surface)}
    mapped = map_flow_properties(
        profiles=profiles, domain=None, cell_mesh=_grid(2, 1, 100.0),
        layer_depths=np.zeros((1, 2)), properties=("K",), required={"K"},
    )  # fmt: skip

    np.testing.assert_allclose(mapped["hk"], [[1e-4, 0.0]])
    with pytest.raises(DataContractViolation, match="read from the map 'k_map'"):
        require_positive_conductivity(mapped["hk"], active_mask=np.ones(2, bool), profiles=profiles)
