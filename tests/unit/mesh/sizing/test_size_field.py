"""The size field refines on its targets and never grows faster than max_slope."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.request import RasterGridSpec, SizeField
from hydromodpy.spatial.mesh.sizing import size_field as size_field_module
from hydromodpy.spatial.mesh.sizing.size_field import (
    OutsideCoarsening,
    SizeTerm,
    build_size_field,
    sample_size_field,
)

_WKT = 'PROJCS["RGF93 / Lambert-93"]'


def _grid(nrow: int = 120, ncol: int = 160, step: float = 10.0) -> RasterGridSpec:
    return RasterGridSpec(
        xmin=1000.0,
        xmax=1000.0 + ncol * step,
        ymin=5000.0,
        ymax=5000.0 + nrow * step,
        dx=step,
        dy=step,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=_WKT,
    )


def _max_slope_of(field: SizeField) -> float:
    """Largest |dh| / distance between pixel centres, over row, column and diagonal pairs."""
    values = field.values
    dx, dy = field.grid.dx, field.grid.dy
    ratios = [
        np.abs(np.diff(values, axis=1)).max() / dx,
        np.abs(np.diff(values, axis=0)).max() / dy,
        np.abs(values[1:, 1:] - values[:-1, :-1]).max() / np.hypot(dx, dy),
        np.abs(values[1:, :-1] - values[:-1, 1:]).max() / np.hypot(dx, dy),
    ]
    return float(max(ratios))


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


@pytest.mark.parametrize("max_slope", [0.5, 0.2, 1.0])
def test_the_size_never_grows_faster_than_max_slope(max_slope: float) -> None:
    field = _all_terms_field(max_slope)
    assert _max_slope_of(field) <= max_slope * (1.0 + 1e-9)


def test_the_field_is_clipped_between_the_floor_and_the_outside_size() -> None:
    field = _all_terms_field()
    assert field.values.min() == pytest.approx(15.0)
    assert 100.0 < field.values.max() <= 300.0
    assert field.values.min() >= 10.0


def test_a_river_term_ramps_at_its_own_slope() -> None:
    grid = _grid(nrow=20, ncol=200)
    # A vertical river through the centre of column 10.
    river = LineString([(1105.0, 5000.0), (1105.0, 5200.0)])
    field = build_size_field(
        grid,
        h0=100.0,
        h_floor=10.0,
        terms=[SizeTerm(name="rivers", region=river, size_m=20.0, ramp_m=400.0)],
        outside=None,
        max_slope=0.5,
    )
    row = field.values[10]
    distance = np.abs(np.arange(200) - 10) * 10.0
    expected = np.minimum(20.0 + (80.0 / 400.0) * distance, 100.0)
    np.testing.assert_allclose(row, expected, rtol=0, atol=1e-9)


def test_a_term_steeper_than_max_slope_is_bounded() -> None:
    grid = _grid(nrow=20, ncol=200)
    river = LineString([(1105.0, 5000.0), (1105.0, 5200.0)])
    field = build_size_field(
        grid,
        h0=100.0,
        h_floor=10.0,
        terms=[SizeTerm(name="rivers", region=river, size_m=20.0, ramp_m=10.0)],
        outside=None,
        max_slope=0.5,
    )
    assert field.values[10, 12] == pytest.approx(20.0 + 0.5 * 20.0)


def test_the_outside_ramp_is_never_shorter_than_its_slope_allows() -> None:
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


def test_a_term_coarser_than_the_background_refines_nothing() -> None:
    grid = _grid(nrow=10, ncol=10)
    field = build_size_field(
        grid,
        h0=50.0,
        h_floor=10.0,
        terms=[
            SizeTerm(
                name="zone", region=box(1000.0, 5000.0, 1050.0, 5050.0), size_m=80.0, ramp_m=10.0
            )
        ],
        outside=None,
        max_slope=0.5,
    )
    assert np.all(field.values == 50.0)


def test_a_large_grid_takes_the_block_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
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
    padded = np.pad(fine.values, ((0, 1), (0, 2)), mode="edge")
    expected = padded.reshape(17, block, 24, block).min(axis=(1, 3))
    np.testing.assert_array_equal(coarse.values, expected)
    assert _max_slope_of(coarse) <= 0.5 * (1.0 + 1e-9)


def test_bilinear_sampling_is_exact_on_a_plane() -> None:
    grid = _grid(nrow=8, ncol=12)
    rows, cols = np.mgrid[0:8, 0:12]
    x = grid.xmin + (cols + 0.5) * grid.dx
    y = grid.ymax - (rows + 0.5) * grid.dy
    field = SizeField(values=10.0 + 0.01 * (x - 1000.0) + 0.02 * (y - 5000.0), grid=grid)
    points = np.array([[1012.0, 5013.0], [1077.3, 5041.9], [1105.0, 5065.0]])
    expected = 10.0 + 0.01 * (points[:, 0] - 1000.0) + 0.02 * (points[:, 1] - 5000.0)
    np.testing.assert_allclose(sample_size_field(field, points), expected, rtol=1e-12)


def test_a_background_finer_than_the_floor_is_refused() -> None:
    with pytest.raises(MeshRequestError, match="finer than the floor"):
        build_size_field(_grid(), h0=5.0, h_floor=10.0, terms=[], outside=None, max_slope=0.5)


def test_term_finer_than_the_floor_warns_with_requested_and_effective_size(caplog):
    """A term below the pixel floor is clipped, and a WARNING names both sizes (C-06)."""
    sill = box(1500.0, 5500.0, 1520.0, 5520.0)
    with caplog.at_level("WARNING", logger="hydromodpy.spatial.mesh.sizing.size_field"):
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
