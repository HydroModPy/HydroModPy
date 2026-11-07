"""Area-weighted forcing conserves the volume of the grid it reads, :mod:`~.area_weights`.

The hand references never call shapely on the pixels: the integral over the domain is a sum of
pixel values times interval overlaps.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import shapely
from hypothesis import given, settings
from hypothesis import strategies as st

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.model.forcing.area_weights import area_mean, area_weights
from hydromodpy.model.forcing.cells import discretize_fields_on_cells
from tests._helpers import forcing_cases as fc

pytestmark = pytest.mark.fast

CONSERVATION_REL = 1.0e-9


def _on_cells(mesh, load_result: LoadResult, method: str, nper: int = 1, **kwargs) -> dict:
    return discretize_fields_on_cells(
        load_result=load_result, centers=fc.mesh_centres(mesh), nper=nper, method=method, mesh=mesh, mesh_crs=None, **kwargs
    )  # fmt: skip


def _relative_gap(rates: np.ndarray, areas: np.ndarray, expected: float) -> float:
    return abs(float((rates * areas).sum()) - expected) / expected


@pytest.mark.parametrize(
    ("mesh_builder", "offset"),
    [(fc.triangle_mesh, 0.0), (fc.voronoi_mesh, 3.7)],
    ids=["triangles-aligned-pixels", "voronoi-unaligned-pixels"],
)
def test_the_area_volume_equals_the_integral_of_the_grid_and_nearest_misses_it(
    mesh_builder, offset
):
    mesh = mesh_builder()
    x, y = fc.square_pixels(10.0, 40.0, offset=offset)
    values = fc.rough_values(x, y)
    expected = fc.integral_over_square(values, x, y) * fc.MM_DAY_TO_M_S

    area, nearest = (
        _on_cells(mesh, fc.grid_source(values, x, y), m)[0] for m in ("area", "nearest")
    )

    assert _relative_gap(area, fc.mesh_areas(mesh), expected) < CONSERVATION_REL
    assert _relative_gap(nearest, fc.mesh_areas(mesh), expected) > 1.0e-3


def _boxes(x: np.ndarray, y: np.ndarray, half_x: float, half_y: float) -> np.ndarray:
    """The pixel boxes laid out like the weights, ``(y, x)`` flattened."""
    xx, yy = np.meshgrid(x, y, indexing="xy")
    return shapely.box(xx - half_x, yy - half_y, xx + half_x, yy + half_y).reshape(-1)


def test_the_shared_areas_of_concave_cells_match_the_exact_overlay() -> None:
    l_shape = np.array([[0, 0], [90, 0], [90, 30], [30, 30], [30, 80], [0, 80]], float)
    u_shape = np.array([[100, 0], [190, 0], [190, 80], [160, 80], [160, 25], [130, 25], [130, 80], [100, 80]], float)  # fmt: skip
    mesh = fc.polygon_mesh([l_shape + fc.ORIGIN, u_shape + fc.ORIGIN])
    x = fc.ORIGIN[0] - 7.3 + (np.arange(23) + 0.5) * 9.7
    y = (fc.ORIGIN[1] - 4.1 + (np.arange(11) + 0.5) * 9.7)[::-1]

    weights = area_weights(mesh, x, y).toarray()

    boxes = _boxes(x, y, 0.5 * 9.7, 0.5 * 9.7)
    for cell, ring in enumerate((l_shape, u_shape)):
        exact = shapely.area(shapely.intersection(shapely.Polygon(ring + fc.ORIGIN), boxes))
        np.testing.assert_allclose(weights[cell], exact, rtol=0.0, atol=1e-8)
        assert weights[cell].sum() == pytest.approx(shapely.Polygon(ring).area, rel=1e-12)


@settings(derandomize=True, max_examples=50, deadline=None)
@given(
    radii=st.lists(st.floats(0.2, 1.0), min_size=3, max_size=12),
    pixel=st.floats(3.0, 25.0),
    shift=st.tuples(st.floats(0.0, 1.0), st.floats(0.0, 1.0)),
    descending=st.tuples(st.booleans(), st.booleans()),
    clockwise=st.booleans(),
)
def test_the_shared_areas_of_a_star_shaped_cell_match_the_exact_overlay(radii, pixel, shift, descending, clockwise):  # fmt: skip
    # Evenly spaced corners at positive radii draw a simple ring, often concave.
    angles = 2.0 * np.pi * np.arange(len(radii)) / len(radii)
    ring = 50.0 + 40.0 * np.asarray(radii)[:, None] * np.column_stack([np.cos(angles), np.sin(angles)])  # fmt: skip
    ring = (ring[::-1] if clockwise else ring) + fc.ORIGIN
    n = int(np.ceil(100.0 / pixel)) + 2
    axes = [
        fc.ORIGIN[k] - pixel + shift[k] * pixel + (np.arange(n) + 0.5) * pixel for k in range(2)
    ]
    x, y = (axis[::-1] if flip else axis for axis, flip in zip(axes, descending, strict=True))

    weights = area_weights(fc.polygon_mesh([ring]), x, y).toarray()[0]

    exact = shapely.area(shapely.intersection(shapely.Polygon(ring), _boxes(x, y, pixel / 2, pixel / 2)))  # fmt: skip
    np.testing.assert_allclose(weights, exact, rtol=0.0, atol=1e-6)
    assert weights.sum() == pytest.approx(shapely.Polygon(ring).area, rel=1e-9)


def _daily_grid(folder: Path):
    """A voronoi mesh under 60 daily grids, read on January and February."""
    x, y = fc.square_pixels(10.0, 40.0, offset=1.3)
    days = pd.date_range("2020-01-01", periods=60, freq="D")
    cube = np.stack([fc.rough_values(x, y, seed=day) for day in range(days.size)])
    record = fc.field_record(fc.grid_dataset(cube, x, y, days), days=60)
    periods = [cube[0:31].mean(axis=0), cube[31:60].mean(axis=0)]
    return fc.voronoi_mesh(), record, x, y, periods, fc.window("2020-01-01", "2020-02-29")


def _geotiff_bands(folder: Path):
    """A triangle mesh under a GeoTIFF of two bands, one per period."""
    x, y = fc.square_pixels(12.5, 50.0, offset=2.1)
    bands = np.stack([fc.rough_values(x, y, seed=seed) for seed in (1, 2)])
    record = fc.field_record(str(fc.write_geotiff(folder / "recharge.tif", bands, x, y)))
    return fc.triangle_mesh(), record, x, y, list(bands), None


@pytest.mark.parametrize(
    "source", [_daily_grid, _geotiff_bands], ids=["transient-grid", "multi-band-geotiff"]
)
def test_every_period_conserves_its_volume(tmp_path: Path, source) -> None:
    mesh, record, x, y, periods, simulation_window = source(tmp_path)
    result = _on_cells(mesh, LoadResult(fields=[record]), "area", nper=2, simulation_window=simulation_window)  # fmt: skip
    for kper, values in enumerate(periods):
        expected = fc.integral_over_square(values, x, y) * fc.MM_DAY_TO_M_S
        assert _relative_gap(result[kper], fc.mesh_areas(mesh), expected) < CONSERVATION_REL


def test_a_uniform_grid_gives_its_value_to_a_cell_it_only_partly_covers() -> None:
    mesh = fc.triangle_mesh()
    x = fc.ORIGIN[0] + 250.0 + (np.arange(40) + 0.5) * 10.0
    y = fc.ORIGIN[1] + 250.0 + (np.arange(40) + 0.5) * 10.0
    result = _on_cells(mesh, fc.grid_source(np.full((40, 40), 4.0), x, y), "area")[0]
    np.testing.assert_allclose(result, 4.0 * fc.MM_DAY_TO_M_S, rtol=1e-12)


def _one_square_cell():
    return fc.polygon_mesh([np.array([[0.0, 0.0], [30, 0], [30, 30], [0, 30]]) + fc.ORIGIN])


_X3 = fc.ORIGIN[0] + np.array([5.0, 15.0, 25.0])
_Y3 = fc.ORIGIN[1] + np.array([25.0, 15.0, 5.0])


def _on_pixels(x: np.ndarray) -> None:
    _on_cells(_one_square_cell(), fc.grid_source(np.ones((_Y3.size, x.size)), x, _Y3), "area")


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: _on_pixels(fc.ORIGIN[0] + np.array([15.0])), "at least two pixel centres along x"),
        (lambda: _on_pixels(_X3[[0, 2, 1]]), "pixel centres sorted along x"),
        (lambda: area_weights(_one_square_cell(), *np.meshgrid(_X3[:2], _Y3[:2])),
         "needs a grid with 1-D x and y axes"),
        (lambda: area_mean(area_weights(_one_square_cell(), _X3, _Y3), np.ones((1, 2, 3))),
         r"the values must be laid out \(y, x\)"),
    ],
    ids=["a-raster-one-pixel-wide", "an-axis-out-of-order", "2-d-axes", "values-not-y-x"],
)  # fmt: skip
def test_area_refuses_pixels_it_cannot_place(call, match) -> None:
    with pytest.raises(ValueError, match=match):
        call()
