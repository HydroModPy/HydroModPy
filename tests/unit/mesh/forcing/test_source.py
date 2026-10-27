"""The readers shared by the forcings, :mod:`hydromodpy.spatial.mesh.forcing._source`.

They convert the unit of a record, find its field variable and its x and y
axes, and put a slice on the cells, by centre or by shared area.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.spatial.mesh.forcing import discretize_fields_on_cells, discretize_points_on_cells
from hydromodpy.spatial.mesh.forcing._source import find_xy_dims, pick_field_variable
from tests.unit.mesh.forcing.forcing_cases import (
    MM_DAY_TO_M_S,
    ORIGIN,
    centres,
    field_record,
    grid_source,
    mesh_centres,
    pixel_axes,
    square_pixels,
    static_field,
    triangle_mesh,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("unit", "value", "expected_m_s"),
    [
        ("mm/day", 10.0, 10.0 * MM_DAY_TO_M_S),
        ("mm/jour", 10.0, 10.0 * MM_DAY_TO_M_S),
        ("m/day", 0.01, 0.01 / 86400.0),
        ("m/s", 1.5e-7, 1.5e-7),
        ("mm/s", 0.001, 0.001 * 1e-3),
    ],
)
def test_a_record_unit_converts_to_m_per_s(unit, value, expected_m_s):
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=[static_field(2, 2, value, unit=unit)]),
        centers=centres(2, 2),
        nper=1,
    )

    np.testing.assert_allclose(result[0], expected_m_s, rtol=1e-8)


def test_an_unknown_unit_is_refused():
    with pytest.raises(ValueError, match=r"Unsupported .*unit 'degC'"):
        discretize_fields_on_cells(
            load_result=LoadResult(fields=[static_field(2, 2, 10.0, unit="degC")]),
            centers=centres(2, 2),
            nper=1,
        )


def _dataset_led_by(name: str, variable: xr.DataArray, *, grid_mapping: str | None) -> xr.Dataset:
    """A 3 mm/day field written after another variable, as a CF or land-surface export does."""
    x, y = pixel_axes(2, 2)
    attrs = {"grid_mapping": grid_mapping} if grid_mapping else {}
    field = xr.DataArray(np.full((2, 2), 3.0), dims=("y", "x"), attrs=attrs)
    return xr.Dataset({name: variable, "recharge": field}, coords={"x": x, "y": y})


@pytest.mark.parametrize(
    "dataset",
    [
        _dataset_led_by(
            "crs",
            xr.DataArray(0, attrs={"grid_mapping_name": "lambert_conformal_conic"}),
            grid_mapping="crs",
        ),
        _dataset_led_by("pixel_count", xr.DataArray(4.0), grid_mapping=None),
    ],
    ids=["cf-grid-mapping", "scalar-beside-the-grid"],
)
def test_the_variable_beside_the_field_is_not_read_as_the_field(dataset):
    result = discretize_fields_on_cells(
        load_result=LoadResult(fields=[field_record(dataset)]),
        centers=centres(2, 2),
        nper=1,
    )

    np.testing.assert_allclose(result[0], 3.0 * MM_DAY_TO_M_S)


def test_a_dataset_of_one_dimensional_variables_falls_back_to_its_first_variable():
    dataset = xr.Dataset({"mean": ("time", [1.0, 2.0]), "count": ("time", [3, 4])})

    assert pick_field_variable(dataset) == "mean"


def test_an_empty_dataset_has_no_field_variable():
    assert pick_field_variable(xr.Dataset()) is None


@pytest.mark.parametrize(
    ("dims", "expected"),
    [
        (("time", "y", "x"), ("x", "y")),
        (("lat", "lon"), ("lon", "lat")),
        (("time", "rlat", "rlon"), ("rlon", "rlat")),
    ],
    ids=["named-x-y", "named-lon-lat", "rotated-pole-last-two"],
)
def test_the_x_and_y_axes_are_named_or_taken_last(dims, expected):
    array = xr.DataArray(np.zeros((1,) * len(dims)), dims=dims)

    assert find_xy_dims(array) == expected


def test_a_dataarray_with_one_spatial_axis_is_refused():
    stations = xr.DataArray(np.zeros((3, 2)), dims=("time", "station"))

    with pytest.raises(ValueError, match=r"Cannot identify X/Y dimensions.*'station'"):
        find_xy_dims(stations)


def _area_without_mesh():
    x, y = square_pixels(10.0, 40.0)
    discretize_fields_on_cells(
        load_result=grid_source(np.ones((y.size, x.size)), x, y),
        centers=mesh_centres(triangle_mesh()),
        nper=1,
        method="area",
    )


def _area_on_another_mesh():
    x, y = square_pixels(10.0, 40.0)
    discretize_fields_on_cells(
        load_result=grid_source(np.ones((y.size, x.size)), x, y),
        centers=mesh_centres(triangle_mesh())[:6],
        nper=1,
        method="area",
        mesh=triangle_mesh(),
    )


def _area_on_stations():
    discretize_points_on_cells(
        load_result=LoadResult(), centers=np.zeros((3, 2)), nper=1, method="area"
    )


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (_area_without_mesh, "needs the cell polygons"),
        (_area_on_another_mesh, r"the planar mesh holds \d+ cells for 6 centres"),
        (_area_on_stations, "station source has no pixel"),
    ],
    ids=["without-the-cell-polygons", "on-the-polygons-of-other-cells", "on-a-station-source"],
)
def test_area_is_refused_where_it_has_no_polygon_or_no_pixel(call, match):
    with pytest.raises(ValueError, match=match):
        call()


def test_a_cell_no_pixel_reaches_takes_the_nearest_pixel():
    mesh = triangle_mesh()
    x = ORIGIN[0] + (np.arange(50) + 0.5) * 10.0
    y = ORIGIN[1] + (np.arange(100) + 0.5) * 10.0
    values = np.where(x[None, :] < ORIGIN[0] + 250.0, 1.0, 3.0) * np.ones((y.size, 1))
    source = grid_source(values, x, y)

    def on_cells(method: str) -> np.ndarray:
        return discretize_fields_on_cells(
            load_result=source, centers=mesh_centres(mesh), nper=1, method=method, mesh=mesh
        )[0]

    result, nearest = on_cells("area"), on_cells("nearest")
    outside = mesh_centres(mesh)[:, 0] > ORIGIN[0] + 600.0
    assert outside.any()
    np.testing.assert_array_equal(result[outside], nearest[outside])
    assert np.all(np.isfinite(result))
