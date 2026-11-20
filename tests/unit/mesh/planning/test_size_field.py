"""The size field refines on its targets and never grows faster than max_slope.

A target is a geometry, burnt with every pixel it touches, or the pixels a
criterion selected. Each target holds its size on its pixels and ramps back to
the background, the field coarsens outside the catchment, and a field too large
for memory keeps the minimum of each block. A target on no pixel refines
nothing, and a pixel region off the grid of the field is refused with a message
that names it.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.planning import size_field as size_field_module
from hydromodpy.mesh.planning.size_field import (
    OutsideCoarsening,
    PixelRegion,
    SizeTerm,
    build_size_field,
)
from hydromodpy.mesh.request import RasterGridSpec, SizeField
from tests._helpers.mesh_cases import grid_spec

_PROPERTY = settings(derandomize=True, max_examples=50, deadline=None)


def _grid(nrow: int = 120, ncol: int = 160, step: float = 10.0) -> RasterGridSpec:
    return grid_spec(nrow, ncol, step, xmin=1000.0, ymin=5000.0)


def _max_slope_of(field: SizeField) -> float:
    """Largest |dh| / distance between pixel centers, over row, column and diagonal pairs."""
    values = field.values
    dx, dy = field.grid.dx, field.grid.dy
    ratios = [
        np.abs(np.diff(values, axis=1)).max() / dx,
        np.abs(np.diff(values, axis=0)).max() / dy,
        np.abs(values[1:, 1:] - values[:-1, :-1]).max() / np.hypot(dx, dy),
        np.abs(values[1:, :-1] - values[:-1, 1:]).max() / np.hypot(dx, dy),
    ]
    return float(max(ratios))


def _burnt(region: object, grid: RasterGridSpec) -> np.ndarray:
    """The pixels of *grid* that *region* touches, as the field burns a geometry."""
    return rasterize(
        [(region, 1)],
        out_shape=(grid.nrow, grid.ncol),
        transform=Affine(grid.dx, 0.0, grid.xmin, 0.0, -grid.dy, grid.ymax),
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)


def _all_terms_field(max_slope: float = 0.5) -> SizeField:
    grid = _grid()
    river = LineString([(1050.0, 5050.0), (1800.0, 5900.0), (2500.0, 5950.0)])
    zone = box(2100.0, 5100.0, 2300.0, 5300.0)
    return build_size_field(
        grid,
        h0=100.0,
        h_floor=10.0,
        terms=[
            SizeTerm(name="rivers", region=river, size_m=15.0, ramp_m=60.0),
            SizeTerm(name="zone", region=zone, size_m=25.0, ramp_m=40.0),
        ],
        outside=OutsideCoarsening(
            region=box(1100.0, 5100.0, 2000.0, 6000.0), factor=3.0, transition_m=100.0
        ),
        max_slope=max_slope,
    )


def test_field_clipped() -> None:
    field = _all_terms_field()
    assert field.values.min() == pytest.approx(15.0)
    assert 100.0 < field.values.max() <= 300.0
    assert field.values.min() >= 10.0


RIVER_COLUMN_10 = LineString([(1105.0, 5000.0), (1105.0, 5200.0)])  # vertical, centre of column 10

RAMPS = [
    # Ramp 400 m from 20 to 100 m is 0.2 m/m, gentler than max_slope.
    pytest.param(400.0, 0.2, id="gentle ramp"),
    # Ramp 10 m would ask 8 m/m, so max_slope = 0.5 rules.
    pytest.param(10.0, 0.5, id="steeper than max_slope"),
]


@pytest.mark.parametrize(("ramp_m", "slope"), RAMPS)
def test_term_ramp(ramp_m, slope) -> None:
    field = build_size_field(
        _grid(nrow=20, ncol=200),
        h0=100.0,
        h_floor=10.0,
        terms=[SizeTerm(name="rivers", region=RIVER_COLUMN_10, size_m=20.0, ramp_m=ramp_m)],
        outside=None,
        max_slope=0.5,
    )

    distance = np.abs(np.arange(200) - 10) * 10.0
    np.testing.assert_allclose(
        field.values[10], np.minimum(20.0 + slope * distance, 100.0), atol=1e-9
    )


def test_outside_ramp_length() -> None:
    grid = _grid(nrow=10, ncol=200)
    field = build_size_field(
        grid,
        h0=100.0,
        h_floor=10.0,
        terms=[],
        outside=OutsideCoarsening(
            region=box(1000.0, 5000.0, 1100.0, 5100.0), factor=2.0, transition_m=50.0
        ),
        max_slope=0.5,
    )
    # T = max(50, (2 - 1) * 100 / 0.5) = 200 m: 20 pixels to reach 200 m.
    row = field.values[5]
    assert row[9] == pytest.approx(100.0)
    assert row[19] == pytest.approx(150.0)
    assert row[29] == pytest.approx(200.0)
    assert row[-1] == pytest.approx(200.0)


def test_off_grid_changes_nothing() -> None:
    # A zone or a catchment drawn beside the DEM touches no pixel.
    grid = _grid(nrow=10, ncol=10)
    beside = box(5000.0, 5000.0, 5100.0, 5100.0)

    field = build_size_field(
        grid,
        h0=50.0,
        h_floor=10.0,
        terms=[SizeTerm(name="zone", region=beside, size_m=20.0, ramp_m=10.0)],
        outside=OutsideCoarsening(region=beside, factor=2.0, transition_m=50.0),
        max_slope=0.5,
    )

    assert np.all(field.values == 50.0)


def test_large_grid_block_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = _grid(nrow=50, ncol=70)
    terms = [
        SizeTerm(
            name="rivers",
            region=LineString([(1205.0, 5000.0), (1500.0, 5500.0)]),
            size_m=12.0,
            ramp_m=40.0,
        )
    ]
    fine = build_size_field(grid, h0=60.0, h_floor=10.0, terms=terms, outside=None, max_slope=0.5)
    monkeypatch.setattr(size_field_module, "MAX_SIZE_FIELD_PIXELS", 500)
    coarse = build_size_field(grid, h0=60.0, h_floor=10.0, terms=terms, outside=None, max_slope=0.5)
    block = 3
    assert coarse.grid.dx == pytest.approx(block * grid.dx)
    assert coarse.grid.nrow * coarse.grid.ncol <= 500
    assert coarse.grid.xmin == grid.xmin and coarse.grid.ymax == grid.ymax
    assert coarse.grid.crs_wkt == grid.crs_wkt
    padded = np.pad(fine.values, ((0, 1), (0, 2)), mode="edge")
    expected = padded.reshape(17, block, 24, block).min(axis=(1, 3))
    np.testing.assert_array_equal(coarse.values, expected)
    assert _max_slope_of(coarse) <= 0.5 * (1.0 + 1e-9)


def test_narrow_grid_block_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The square root of the pixel ratio gives blocks of 2, whose 2 x 50 rows overflow 99.
    grid = _grid(nrow=3, ncol=100)
    monkeypatch.setattr(size_field_module, "MAX_SIZE_FIELD_PIXELS", 99)

    coarse = build_size_field(grid, h0=60.0, h_floor=10.0, terms=[], outside=None, max_slope=0.5)

    assert coarse.grid.dx == pytest.approx(3 * grid.dx)
    assert (coarse.grid.nrow, coarse.grid.ncol) == (1, 34)
    assert coarse.grid.nrow * coarse.grid.ncol <= 99


def test_term_below_floor_warns(caplog):
    # A term below the pixel floor is clipped, and a WARNING names both sizes.
    sill = box(1500.0, 5500.0, 1520.0, 5520.0)
    with caplog.at_level("WARNING", logger="hydromodpy.mesh.planning.size_field"):
        build_size_field(
            _grid(),
            h0=100.0,
            h_floor=30.0,
            terms=[SizeTerm(name="sill:a-b", region=sill, size_m=9.12, ramp_m=40.0)],
            outside=None,
            max_slope=0.3,
        )
    messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("sill:a-b" in m and "9.12" in m and "30" in m for m in messages), messages


def _pixel_grid() -> RasterGridSpec:
    return grid_spec(60, 80, 10.0)


def _field(region: object, grid: RasterGridSpec) -> np.ndarray:
    return build_size_field(
        grid,
        h0=80.0,
        h_floor=10.0,
        terms=[SizeTerm(name="zone", region=region, size_m=20.0, ramp_m=40.0)],
        outside=None,
        max_slope=0.5,
    ).values


def test_pixel_region_ramp() -> None:
    grid = _pixel_grid()
    mask = np.zeros((grid.nrow, grid.ncol), dtype=bool)
    mask[20:30, 10:15] = True

    values = _field(PixelRegion(mask=mask, grid=grid), grid)

    assert np.all(values[mask] == 20.0)
    # The ramp asks 60 m over 40 m, steeper than max_slope: the slope is 0.5.
    assert values[25, 16] == pytest.approx(20.0 + 0.5 * 20.0)
    assert values[25, 22] == pytest.approx(20.0 + 0.5 * 80.0)
    assert values.max() == 80.0


def _empty_pixels() -> PixelRegion:
    grid = _pixel_grid()
    return PixelRegion(mask=np.zeros((grid.nrow, grid.ncol), dtype=bool), grid=grid)


def test_empty_pixels_refine_nothing() -> None:
    grid = _pixel_grid()
    term = SizeTerm(name="zone", region=_empty_pixels(), size_m=20.0, ramp_m=40.0)

    field = build_size_field(
        grid, h0=100.0, h_floor=10.0, terms=[term], outside=None, max_slope=0.5
    )

    assert np.all(field.values == 100.0)


REFUSALS = [
    pytest.param(
        grid_spec(60, 80, 10.0),
        (3, 3),
        r"a pixel region has shape \(3, 3\)",
        id="mask of another shape",
    ),
    pytest.param(
        grid_spec(120, 160, 5.0), (120, 160), "lies on another grid", id="region of another grid"
    ),
]


@pytest.mark.parametrize(("region_grid", "mask_shape", "message"), REFUSALS)
def test_refusals(region_grid, mask_shape, message) -> None:
    # The field is built on a 60 x 80 grid of 10 m pixels.
    with pytest.raises(MeshRequestError, match=message):
        region = PixelRegion(mask=np.ones(mask_shape, dtype=bool), grid=region_grid)
        _field(region, _pixel_grid())


_PROPERTY_GRID = grid_spec(30, 40, 10.0)
_XY = st.tuples(
    st.floats(min_value=-50.0, max_value=450.0, allow_nan=False),
    st.floats(min_value=-50.0, max_value=350.0, allow_nan=False),
)


@st.composite
def _regions(draw: st.DrawFn) -> Polygon | LineString:
    """A polyline across the grid, or the polygon around it, partly off the grid at times."""
    line = LineString(draw(st.lists(_XY, min_size=2, max_size=4)))
    width = draw(st.floats(min_value=0.0, max_value=60.0))
    return line.buffer(width) if width > 1.0 else line


@st.composite
def _terms(draw: st.DrawFn) -> list[SizeTerm]:
    terms = []
    for index in range(draw(st.integers(1, 3))):
        region = draw(_regions())
        if region.is_empty:
            continue
        size = draw(st.floats(min_value=4.0, max_value=120.0))
        ramp = draw(st.floats(min_value=0.0, max_value=300.0))
        terms.append(SizeTerm(name=f"zone:{index}", region=region, size_m=size, ramp_m=ramp))
    return terms


@_PROPERTY
@given(
    terms=_terms(),
    max_slope=st.floats(min_value=0.05, max_value=2.0),
    factor=st.floats(min_value=1.0, max_value=4.0),
    catchment=_regions(),
)
def test_field_of_any_targets(
    terms: list[SizeTerm], max_slope: float, factor: float, catchment
) -> None:
    # Random polygons and lines: the slope bound, the clip, and each size on its own pixels.
    h0, floor = 80.0, 10.0
    outside = (
        OutsideCoarsening(region=catchment, factor=factor, transition_m=50.0)
        if not catchment.is_empty
        else None
    )

    field = build_size_field(
        _PROPERTY_GRID, h0=h0, h_floor=floor, terms=terms, outside=outside, max_slope=max_slope
    )

    assert _max_slope_of(field) <= max_slope * (1.0 + 1e-9)
    assert field.values.min() >= floor
    assert field.values.max() <= (factor if outside else 1.0) * h0 * (1.0 + 1e-12)
    for term in terms:
        on_it = _burnt(term.region, _PROPERTY_GRID)
        if term.size_m < h0 and on_it.any():
            assert field.values[on_it].max() <= max(term.size_m, floor) * (1.0 + 1e-12)
