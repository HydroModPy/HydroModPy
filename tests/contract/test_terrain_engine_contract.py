"""Conformance suite for the terrain port, run against every engine.

The port is only worth its name if two independent implementations answer the
same questions the same way, so every assertion here is parametrized over
``WhiteboxTerrainEngine`` and ``NumpyTerrainEngine``. A member that only makes
sense for one of them cannot survive this file.

The terrains are built here rather than loaded, because on a plane and on a V
valley the answer is known in closed form: a plane draining east accumulates
1, 2, 3 ... along a row, and the catchment of the exit of a valley is the whole
valley. That is what lets almost every assertion be exact instead of banded.
Both surfaces are tie-free by construction: the two engines break ties their
own way, and comparing them where a tie decides would compare tie-breaking,
not routing.

Two committed DEMs close the loop on real surfaces, where flats and ties are
real. On ``tests/data/sfr_cheze/dem_valley.tif`` the two engines agree cell for
cell and are compared on the band of row 74 of ``tests/TOLERANCES.md``. On
``examples/data/dem/DEM_gouville_25m.tif`` they do **not** agree, and the suite
does not pretend otherwise: measured, the filled DEMs differ by up to 3.76 m,
the pointer on 96 of 5 400 cells, and the catchment of the basin exit is 1 459
cells for Whitebox against 587 for numpy -- a factor 2.5 on the area, because
the two resolve the same plateaus at different stages and the water leaves by
different boundary cells. Neither answer is wrong; substitutable is not
equivalent. What both engines do owe on that DEM is asserted, exactly and with
no band: after conditioning, not one interior cell drains nowhere.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import (
    TerrainCapabilityError,
    TerrainProductError,
    TerrainRequestError,
)
from hydromodpy.spatial.terrain import (
    LN_FLOAT32_COLLISION_COUNT,
    OUTLET_LAYER_NAME,
    SNAPPED_OUTLET_LAYER_NAME,
    CatchmentLayout,
    ConditioningExtent,
    DrainageDirections,
    Outlet,
    TerrainEngine,
    missing_engine_members,
    snap_window_cells,
)
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS
from tests._helpers.tolerances import tol

rasterio = pytest.importorskip("rasterio")

RES = 25.0
CELL_AREA_M2 = RES * RES
CRS = "EPSG:2154"
NODATA = -9999.0

REAL_DEM = Path(__file__).resolve().parents[1] / "data" / "sfr_cheze" / "dem_valley.tif"


# --------------------------------------------------------------------------- #
# Engines under test
# --------------------------------------------------------------------------- #


def _numpy_engine():
    from hydromodpy.spatial.terrain import NumpyTerrainEngine

    return NumpyTerrainEngine()


def _whitebox_engine():
    pytest.importorskip("whitebox_workflows")
    from tests._helpers.whitebox import configure_whitebox_single_thread

    monkeypatch = pytest.MonkeyPatch()
    configure_whitebox_single_thread(monkeypatch)
    try:
        from hydromodpy.spatial.terrain import WhiteboxTerrainEngine

        return WhiteboxTerrainEngine()
    finally:
        monkeypatch.undo()


ENGINE_FACTORIES = {"numpy_d8": _numpy_engine, "whitebox_workflows": _whitebox_engine}


@pytest.fixture(params=sorted(ENGINE_FACTORIES))
def engine(request):
    """One terrain engine, once per implementation."""
    return ENGINE_FACTORIES[request.param]()


# --------------------------------------------------------------------------- #
# Terrains
# --------------------------------------------------------------------------- #


def _write_dem(path: Path, surface: np.ndarray) -> Path:
    rows, cols = surface.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs=CRS,
        nodata=NODATA,
        transform=rasterio.transform.from_origin(0.0, rows * RES, RES, RES),
    ) as dst:
        dst.write(surface.astype("float32"), 1)
    return path


def _plane(size: int, drow: int, dcol: int) -> np.ndarray:
    """A plane whose steepest descent is exactly ``(drow, dcol)`` everywhere."""
    rows, cols = np.mgrid[0:size, 0:size]
    return 100.0 - (drow * rows + dcol * cols).astype("float64")


def _valley(size: int) -> np.ndarray:
    """A V valley draining south, with strictly steeper sides than floor."""
    rows, cols = np.mgrid[0:size, 0:size]
    return 100.0 - rows * 0.5 + np.abs(cols - size // 2) * 2.0


def _read(path: Path) -> np.ndarray:
    with rasterio.open(str(path)) as src:
        return src.read(1)


def _interior_data_cells(codes: np.ndarray) -> np.ndarray:
    """Cells a pointer owes a downstream neighbour: not on the frame, not beside a hole.

    A frame cell has nowhere inside the grid to point at. A cell beside an
    absent one has nowhere either, because an absent cell is not a drainage
    target for either engine.
    """
    absent = codes == -32768
    interior = np.zeros(codes.shape, dtype=bool)
    interior[1:-1, 1:-1] = True
    beside_a_hole = np.zeros(codes.shape, dtype=bool)
    for drow in (-1, 0, 1):
        for dcol in (-1, 0, 1):
            beside_a_hole |= np.roll(np.roll(absent, drow, axis=0), dcol, axis=1)
    return interior & ~absent & ~beside_a_hole


def _crs_of(path: Path) -> str:
    with rasterio.open(str(path)) as src:
        return str(src.crs)


@pytest.fixture
def plane_east(tmp_path) -> Path:
    return _write_dem(tmp_path / "plane_east.tif", _plane(30, 0, 1))


@pytest.fixture
def valley(tmp_path) -> Path:
    return _write_dem(tmp_path / "valley.tif", _valley(31))


def _products(engine, dem: Path, out: Path, *, method="fill", units="cells", transform="none"):
    """Run the chain a caller runs: condition, point, accumulate."""
    conditioned = engine.condition_dem(
        dem,
        method=method,
        extent=ConditioningExtent.regional(),
        out=out / "conditioned.tif",
    )
    directions = engine.drainage_directions(conditioned, out=out / "pointer.tif")
    accumulation = engine.flow_accumulation(
        directions,
        units=units,
        transform=transform,
        out=out / f"acc_{units}_{transform}.tif",
    )
    return conditioned, directions, accumulation


# --------------------------------------------------------------------------- #
# The port itself
# --------------------------------------------------------------------------- #


def test_an_engine_satisfies_the_port(engine) -> None:
    assert missing_engine_members(engine) == ()
    assert isinstance(engine, TerrainEngine)


def test_a_digest_is_stable_across_calls(engine) -> None:
    assert engine.engine_digest() == engine.engine_digest()


def test_two_engines_never_share_a_digest() -> None:
    digests = {factory().engine_digest() for factory in ENGINE_FACTORIES.values()}

    assert len(digests) == len(ENGINE_FACTORIES)


def test_an_outlet_id_that_is_not_a_directory_name_is_refused() -> None:
    with pytest.raises(TerrainRequestError):
        Outlet(outlet_id="../escape", x=0.0, y=0.0)


def test_a_conditioning_extent_declares_its_buffer_or_none() -> None:
    with pytest.raises(TerrainRequestError):
        ConditioningExtent(kind="per_outlet_buffer")
    with pytest.raises(TerrainRequestError):
        ConditioningExtent(kind="regional", buffer_distance_m=100.0)


# --------------------------------------------------------------------------- #
# Conditioning
# --------------------------------------------------------------------------- #


def test_conditioning_leaves_a_draining_surface_alone(engine, plane_east, tmp_path) -> None:
    """Every cell of a plane already drains, so nothing may move."""
    conditioned = engine.condition_dem(
        plane_east,
        method="fill",
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )

    assert np.array_equal(_read(conditioned.path), _read(plane_east))


def test_conditioning_raises_a_pit_to_its_lowest_way_out(engine, tmp_path) -> None:
    """The one pit of a plane is filled to the elevation of its lowest neighbour."""
    surface = _plane(21, 0, 1)
    pit = (10, 10)
    surface[pit] -= 20.0
    dem = _write_dem(tmp_path / "pitted.tif", surface)
    neighbours = [
        surface[pit[0] + drow, pit[1] + dcol] for _code, (drow, dcol) in D8_WBT_OFFSETS.items()
    ]

    conditioned = engine.condition_dem(
        dem,
        method="fill",
        extent=ConditioningExtent.regional(),
        out=tmp_path / "out" / "conditioned.tif",
    )
    filled = _read(conditioned.path)

    # An engine that resolves plateaus during the fill raises the pit to the
    # next float32 above its way out rather than exactly onto it. Both answers
    # are admissible; a third value is not. No tolerance: the interval is two
    # adjacent float32.
    lowest = np.float32(min(neighbours))
    assert lowest <= filled[pit] <= np.nextafter(lowest, np.float32(np.inf))
    assert int(np.count_nonzero(filled != surface.astype("float32"))) == 1
    assert float(np.min(filled - surface.astype("float32"))) >= 0.0


def test_a_conditioning_extent_no_engine_serves_is_refused(engine, plane_east, tmp_path) -> None:
    with pytest.raises(TerrainCapabilityError):
        engine.condition_dem(
            plane_east,
            method="fill",
            extent=ConditioningExtent.per_outlet_buffer(500.0),
            out=tmp_path / "out" / "conditioned.tif",
        )


def test_a_conditioning_method_no_engine_serves_is_refused(engine, plane_east, tmp_path) -> None:
    with pytest.raises(TerrainCapabilityError):
        engine.condition_dem(
            plane_east,
            method="carve",
            extent=ConditioningExtent.regional(),
            out=tmp_path / "out" / "conditioned.tif",
        )


def test_the_numpy_engine_refuses_breaching_by_name(plane_east, tmp_path) -> None:
    """Least-cost breaching is not implemented there, and it says so."""
    with pytest.raises(TerrainCapabilityError, match="breach"):
        _numpy_engine().condition_dem(
            plane_east,
            method="breach",
            extent=ConditioningExtent.regional(),
            out=tmp_path / "out" / "conditioned.tif",
        )


def test_the_numpy_engine_refuses_a_pointer_that_holds_a_cycle(valley, tmp_path) -> None:
    """A pointer with a cycle has no accumulation order, and is not guessed at.

    Hand-written, because no conditioning produces one: two cells pointing at
    each other. The engine says the DEM behind the pointer was not conditioned
    rather than returning a count for the cells it could still order.
    """
    engine = _numpy_engine()
    out = tmp_path / "out"
    _conditioned, directions, _acc = _products(engine, valley, out)
    codes = _read(directions.path).copy()
    east, west = 2, 32
    codes[5, 5] = east
    codes[5, 6] = west
    with rasterio.open(str(directions.path)) as src:
        profile = src.profile.copy()
    cyclic = out / "cyclic_pointer.tif"
    with rasterio.open(str(cyclic), "w", **profile) as dst:
        dst.write(codes, 1)

    with pytest.raises(TerrainProductError, match="cycle"):
        engine.flow_accumulation(
            DrainageDirections(
                path=cyclic,
                pointer_convention="d8_wbt",
                conditioned_dem=directions.conditioned_dem,
            ),
            units="cells",
            transform="none",
            out=out / "acc_cyclic.tif",
        )


# --------------------------------------------------------------------------- #
# Directions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code", sorted(D8_WBT_OFFSETS))
def test_the_pointer_writes_the_code_its_convention_declares(engine, code, tmp_path) -> None:
    """A plane tilted at one octant is coded with that octant's code (C6).

    The expected code is read from the declared table, so a pointer convention
    and the raster it emits cannot drift apart without this failing.
    """
    drow, dcol = D8_WBT_OFFSETS[code]
    dem = _write_dem(tmp_path / f"plane_{code}.tif", _plane(40, drow, dcol))

    _conditioned, directions, _acc = _products(engine, dem, tmp_path / "out")
    codes = _read(directions.path)

    assert directions.pointer_convention == "d8_wbt"
    inner = codes[5:-5, 5:-5]
    values, counts = np.unique(inner[inner > 0], return_counts=True)
    assert int(values[np.argmax(counts)]) == code


def test_the_pointer_codes_a_cell_with_no_way_out_as_zero(engine, plane_east, tmp_path) -> None:
    """Exactly the downslope edge of a plane has no downstream cell."""
    _conditioned, directions, _acc = _products(engine, plane_east, tmp_path / "out")
    codes = _read(directions.path)

    assert int(np.count_nonzero(codes == 0)) == codes.shape[0]
    assert np.all(codes[:, -1] == 0)


# --------------------------------------------------------------------------- #
# Accumulation
# --------------------------------------------------------------------------- #


def test_accumulation_counts_the_cell_itself(engine, plane_east, tmp_path) -> None:
    """On a plane draining east, row j reads 1, 2, 3 ... exactly."""
    _conditioned, _directions, accumulation = _products(engine, plane_east, tmp_path / "out")
    values = _read(accumulation.path)

    expected = np.tile(np.arange(1, values.shape[1] + 1, dtype="float32"), (values.shape[0], 1))
    assert np.array_equal(values, expected)


def test_accumulation_in_m2_is_the_count_times_the_cell_area(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, _directions, cells = _products(engine, valley, out, units="cells")
    _c, _d, square_metres = _products(engine, valley, out, units="m2")

    assert np.array_equal(_read(square_metres.path), _read(cells.path) * CELL_AREA_M2)


def test_the_ln_transform_is_the_log_of_the_untransformed_product(engine, valley, tmp_path) -> None:
    """``ln`` means the natural logarithm, which is what the chain emits.

    The regional accumulation raster HydroModPy writes is this product, and a
    reader who assumed base 10 would be wrong by a factor 2.3.
    """
    out = tmp_path / "out"
    _conditioned, _directions, cells = _products(engine, valley, out, units="cells")
    _c, _d, transformed = _products(engine, valley, out, units="cells", transform="ln")

    counts = _read(cells.path).astype("float64")
    logged = _read(transformed.path).astype("float64")
    positive = counts > 0
    gap = np.abs(np.log(counts[positive]) - logged[positive])

    assert float(gap.max()) <= tol("terrain_engine_conformance__ln_transform_identity")


def test_a_transform_no_engine_serves_is_refused(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, directions, _acc = _products(engine, valley, out)

    with pytest.raises(TerrainCapabilityError):
        engine.flow_accumulation(
            directions,
            units="cells",
            transform="log10",
            out=out / "acc_log10.tif",
        )


@pytest.mark.parametrize("transform", ["none", "ln"])
def test_no_valid_cell_carries_the_nodata_the_product_declares(
    engine, valley, tmp_path, transform
) -> None:
    """A headwater cell of the ln product reads 0, so the nodata cannot be 0.

    The DEM has no absent cell, so the count has to be zero whatever the
    transform. With a nodata of 0 the ln product loses every headwater under a
    masked read, and nothing downstream says so.
    """
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out, transform=transform)
    values = _read(accumulation.path)

    with rasterio.open(str(accumulation.path)) as src:
        assert src.nodata == accumulation.nodata
        assert int(np.count_nonzero(src.read(1, masked=True).mask)) == 0
    assert int(np.count_nonzero(values == accumulation.nodata)) == 0


# --------------------------------------------------------------------------- #
# Stream network
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("threshold", [10.0, 20.0, 50.0])
def test_a_threshold_selects_the_cells_that_carry_more_than_it(
    engine, valley, tmp_path, threshold
) -> None:
    """The channel count is the cell count above the threshold, exactly (C5)."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    streams = engine.stream_network(
        accumulation,
        threshold=threshold,
        out=out / f"streams_{int(threshold)}.tif",
    )

    counts = _read(accumulation.path)
    assert int(np.count_nonzero(_read(streams.path) == 1)) == int(
        np.count_nonzero(counts > threshold)
    )
    assert streams.threshold_units == "cells"


def test_a_transformed_accumulation_cannot_be_thresholded(engine, valley, tmp_path) -> None:
    """R1: a cell threshold on a log raster selects nothing, and silently.

    This refusal is what replaces ``looks_log_scaled``, the runtime heuristic
    that guessed the transform back from the values it happened to find.
    """
    out = tmp_path / "out"
    _conditioned, _directions, transformed = _products(engine, valley, out, transform="ln")

    with pytest.raises(TerrainProductError, match="transform"):
        engine.stream_network(transformed, threshold=20.0, out=out / "streams.tif")


def test_a_non_positive_threshold_is_refused(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    with pytest.raises(TerrainRequestError):
        engine.stream_network(accumulation, threshold=0.0, out=out / "streams.tif")


# --------------------------------------------------------------------------- #
# Delineation
# --------------------------------------------------------------------------- #


def _valley_exit(size: int = 31) -> Outlet:
    """The cell every cell of the V valley drains through."""
    floor = size // 2
    return Outlet(
        outlet_id="valley_exit",
        x=(floor + 0.5) * RES,
        y=RES * 0.5,
    )


def test_the_whole_valley_drains_through_its_exit(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    (catchment,) = engine.delineate(
        accumulation,
        [_valley_exit()],
        out_dir=out / "catchments",
        snap_distance_m=RES,
    )

    assert catchment.cell_count == 31 * 31
    assert catchment.area_m2 == pytest.approx(31 * 31 * CELL_AREA_M2, rel=0.0, abs=1e-6)
    assert catchment.outlet.outlet_id == "valley_exit"


def test_the_mask_marks_the_catchment_and_nothing_else(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    (catchment,) = engine.delineate(
        accumulation,
        [_valley_exit()],
        out_dir=out / "catchments",
        snap_distance_m=RES,
    )
    mask = _read(catchment.mask_path)

    assert set(np.unique(mask).tolist()) <= {1, -32768}
    assert int(np.count_nonzero(mask == 1)) == catchment.cell_count


def test_a_batch_answers_every_outlet_in_the_order_it_was_given(engine, valley, tmp_path) -> None:
    """N outlets against one accumulation, each with its own directory."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    floor = 15
    outlets = [
        Outlet(outlet_id="left_side", x=(floor - 6 + 0.5) * RES, y=(31 - 20 - 0.5) * RES),
        _valley_exit(),
        Outlet(outlet_id="mid_floor", x=(floor + 0.5) * RES, y=(31 - 20 - 0.5) * RES),
    ]

    catchments = engine.delineate(
        accumulation,
        outlets,
        out_dir=out / "catchments",
        snap_distance_m=RES,
    )

    assert [c.outlet.outlet_id for c in catchments] == [o.outlet_id for o in outlets]
    assert all(c.mask_path.is_file() and c.boundary_path.is_file() for c in catchments)
    assert all(c.mask_path.parent.name == c.outlet.outlet_id for c in catchments)
    # The valley exit drains everything, so no sibling catchment can be larger.
    assert max(c.cell_count for c in catchments) == catchments[1].cell_count


def _off_talweg() -> Outlet:
    """Two cells west of the floor, three rows above the exit, on purpose."""
    return Outlet(outlet_id="off_talweg", x=(15 - 2 + 0.5) * RES, y=(31 - 28 - 0.5) * RES)


def test_a_snapped_outlet_is_the_accumulation_maximum_of_its_window(
    engine, valley, tmp_path
) -> None:
    """The snap takes the largest accumulation of the window it searches.

    The window is the measured one: a square of half-width
    ``floor(snap_distance_m / (2 * cell size))`` cells. Asserting a Euclidean
    radius instead would pass on the numpy engine and fail on Whitebox, which
    is how this window came to be measured in the first place.
    """
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    declared = _off_talweg()
    snap_distance_m = 4 * RES

    (catchment,) = engine.delineate(
        accumulation,
        [declared],
        out_dir=out / "catchments",
        snap_distance_m=snap_distance_m,
    )

    counts = _read(accumulation.path)
    reach_rows, reach_cols = snap_window_cells(snap_distance_m, dx=RES, dy=RES)
    with rasterio.open(str(accumulation.path)) as src:
        snapped_row, snapped_col = src.index(catchment.snapped_x, catchment.snapped_y)
        row0, col0 = src.index(declared.x, declared.y)
    window = counts[
        row0 - reach_rows : row0 + reach_rows + 1,
        col0 - reach_cols : col0 + reach_cols + 1,
    ]

    assert (reach_rows, reach_cols) == (2, 2)
    assert counts[snapped_row, snapped_col] == window.max()
    assert catchment.snap_distance_m == pytest.approx(
        math.hypot(catchment.snapped_x - declared.x, catchment.snapped_y - declared.y)
    )


def test_a_snap_window_narrower_than_two_cells_moves_nothing(engine, valley, tmp_path) -> None:
    """A snap distance of one cell size snaps nowhere, and that is measured.

    It is the half of the contract a caller gets wrong: ``snap_dist`` is the
    width of the window, so the smallest value that moves an outlet at all is
    twice the cell size.
    """
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    declared = _off_talweg()

    (catchment,) = engine.delineate(
        accumulation,
        [declared],
        out_dir=out / "catchments",
        snap_distance_m=RES,
    )

    assert snap_window_cells(RES, dx=RES, dy=RES) == (0, 0)
    assert catchment.snap_distance_m == pytest.approx(0.0)
    assert (catchment.snapped_x, catchment.snapped_y) == pytest.approx((declared.x, declared.y))


def test_delineation_repeats_cell_for_cell(engine, valley, tmp_path) -> None:
    """Two identical requests produce the same mask, byte for byte."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    masks = []
    for attempt in range(2):
        (catchment,) = engine.delineate(
            accumulation,
            [_valley_exit()],
            out_dir=out / f"attempt_{attempt}",
            snap_distance_m=RES,
        )
        masks.append(_read(catchment.mask_path).tobytes())

    assert masks[0] == masks[1]


@pytest.mark.parametrize(
    ("units", "transform"),
    [("cells", "ln"), ("m2", "none")],
)
def test_a_rank_preserving_product_delineates_the_same_catchment(
    engine, valley, tmp_path, units, transform
) -> None:
    """A snap is a rank, so every order-preserving product answers the same.

    This is the assertion that lets the geographic pipeline hand the engine the
    ``ln`` raster it has always written, instead of paying for a second
    accumulation to say the same thing. It is exact and not banded: the same
    cell, the same count, the same area.
    """
    out = tmp_path / "out"
    _c, _d, reference = _products(engine, valley, out / "ref")
    _c2, _d2, other = _products(engine, valley, out / "other", units=units, transform=transform)

    (expected,) = engine.delineate(
        reference, [_valley_exit()], out_dir=out / "ref_c", snap_distance_m=RES * 4
    )
    (measured,) = engine.delineate(
        other, [_valley_exit()], out_dir=out / "other_c", snap_distance_m=RES * 4
    )

    assert (measured.snapped_x, measured.snapped_y) == (expected.snapped_x, expected.snapped_y)
    assert measured.cell_count == expected.cell_count
    assert measured.area_m2 == pytest.approx(expected.area_m2, rel=0.0, abs=1e-6)


def test_a_delineation_leaves_the_four_artefacts_the_port_declares(
    engine, valley, tmp_path
) -> None:
    """Every engine writes the mask, the boundary and the two point layers.

    The port says it in one line - "the two point layers every engine writes
    beside a catchment" - and nothing checked it until F10a made an engine
    selectable by name from outside. ``NumpyTerrainEngine`` wrote neither, and
    the geographic pipeline reads both back from disk: a delineation that was
    numerically right came out of the chain as "no catchment, widen your snap
    distance". A registry that certifies a class by the members it declares
    cannot see that, so the conformance suite has to.
    """
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    (catchment,) = engine.delineate(
        accumulation, [_valley_exit()], out_dir=out / "c", snap_distance_m=RES * 4
    )

    site_dir = Path(catchment.mask_path).parent
    for name in (OUTLET_LAYER_NAME, SNAPPED_OUTLET_LAYER_NAME):
        assert (site_dir / name).is_file(), name
    assert Path(catchment.mask_path).is_file()
    assert Path(catchment.boundary_path).is_file()


def test_the_snapped_point_layer_holds_the_point_the_catchment_declares(
    engine, valley, tmp_path
) -> None:
    """The layer on disk and the field on the product say the same thing.

    Two sources for one coordinate is how a report and a delineation start
    disagreeing, and only the file survives the process.
    """
    geopandas = pytest.importorskip("geopandas")
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    (catchment,) = engine.delineate(
        accumulation, [_valley_exit()], out_dir=out / "c", snap_distance_m=RES * 4
    )

    frame = geopandas.read_file(str(Path(catchment.mask_path).parent / SNAPPED_OUTLET_LAYER_NAME))
    point = frame.geometry.iloc[0]

    assert point.x == pytest.approx(catchment.snapped_x, abs=1e-6)
    assert point.y == pytest.approx(catchment.snapped_y, abs=1e-6)


def test_a_transform_that_does_not_preserve_the_order_cannot_be_delineated(
    engine, valley, tmp_path
) -> None:
    """The refusal is on the rank, not on the vocabulary of the moment."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    scrambled = replace(accumulation, transform="rank_destroying")

    with pytest.raises(TerrainProductError, match="order of the cells"):
        engine.delineate(
            scrambled,
            [_valley_exit()],
            out_dir=out / "catchments",
            snap_distance_m=RES,
        )


def test_an_empty_batch_is_refused(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    with pytest.raises(TerrainRequestError):
        engine.delineate(accumulation, [], out_dir=out / "c", snap_distance_m=RES)


def test_two_outlets_cannot_share_an_id_in_one_batch(engine, valley, tmp_path) -> None:
    """Otherwise the second one overwrites the first one's files, in silence.

    The first ``Catchment`` would keep the cell count it was given and name a
    file holding the other catchment's mask. Refused before anything is written.
    """
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    outlets = [
        Outlet(outlet_id="twice", x=(15 + 0.5) * RES, y=RES * 0.5),
        Outlet(outlet_id="twice", x=(15 - 6 + 0.5) * RES, y=(31 - 20 - 0.5) * RES),
    ]

    with pytest.raises(TerrainRequestError, match="twice"):
        engine.delineate(
            accumulation,
            outlets,
            out_dir=out / "catchments",
            snap_distance_m=RES,
        )
    assert not (out / "catchments").exists()


def test_a_non_positive_snap_distance_is_refused(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    with pytest.raises(TerrainRequestError):
        engine.delineate(
            accumulation,
            [_valley_exit()],
            out_dir=out / "c",
            snap_distance_m=0.0,
        )


# --------------------------------------------------------------------------- #
# Provenance of the products
# --------------------------------------------------------------------------- #


def test_every_product_carries_the_crs_of_the_dem_it_came_from(engine, valley, tmp_path) -> None:
    """A product that forgets its CRS is a product nothing downstream can place."""
    out = tmp_path / "out"
    conditioned, directions, accumulation = _products(engine, valley, out)
    streams = engine.stream_network(accumulation, threshold=20.0, out=out / "streams.tif")

    assert conditioned.crs == CRS
    for product in (conditioned, directions, accumulation, streams):
        assert _crs_of(product.path) == CRS


def test_the_product_chain_names_what_it_was_derived_from(engine, valley, tmp_path) -> None:
    out = tmp_path / "out"
    conditioned, directions, accumulation = _products(engine, valley, out)

    assert directions.conditioned_dem == conditioned
    assert accumulation.directions == directions
    assert accumulation.units == "cells"
    assert accumulation.transform == "none"


# --------------------------------------------------------------------------- #
# A real surface
# --------------------------------------------------------------------------- #


def test_an_absent_cell_is_no_drainage_target_and_both_engines_say_so(
    tmp_path,
) -> None:
    """A hole inside the domain leaves a depression beside it unfilled, on both.

    Measured, and it is a property of the chain rather than of one engine: on a
    plane draining east with a 3x3 nodata block and a pit whose only low way out
    crosses it, Whitebox and numpy write the same conditioned DEM, the same
    pointer and the same accumulation -- the pit stays at 62 m, keeps no
    downstream neighbour, and the accumulation tops out at 27 on both.

    This test asserts the **agreement**, not that the behaviour is right: a sea
    or lake mask inside a domain is exactly the case where draining into the
    hole would be the physical answer, and neither engine does it. The port says
    so in ``condition_dem``; changing it is a decision about the chain, not about
    one implementation.
    """
    pytest.importorskip("whitebox_workflows")
    size = 21
    surface = _plane(size, 0, 1)
    surface[9:12, 9:12] = NODATA
    surface[10, 8] -= 30.0
    dem = _write_dem(tmp_path / "holed.tif", surface)

    products = {}
    for name, factory in sorted(ENGINE_FACTORIES.items()):
        conditioned, directions, accumulation = _products(factory(), dem, tmp_path / name)
        products[name] = (conditioned, directions, accumulation)

    for left, right in zip(*(products[name] for name in sorted(products)), strict=True):
        assert np.array_equal(_read(left.path), _read(right.path)), left.path
    for name, (_conditioned, directions, _accumulation) in products.items():
        codes = _read(directions.path)
        assert codes[10, 8] == 0, name
        assert int(np.count_nonzero((codes == 0) & _interior_data_cells(codes))) == 0, name


def test_two_outlet_ids_that_differ_only_by_case_are_refused(engine, valley, tmp_path) -> None:
    """One directory on a case-insensitive filesystem, so refused on every one."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    outlets = [
        Outlet(outlet_id="Exit", x=(15 + 0.5) * RES, y=RES * 0.5),
        Outlet(outlet_id="exit", x=(15 - 6 + 0.5) * RES, y=(31 - 20 - 0.5) * RES),
    ]

    with pytest.raises(TerrainRequestError, match="case-folded"):
        engine.delineate(accumulation, outlets, out_dir=out / "c", snap_distance_m=RES)


def test_an_outlet_id_too_long_for_a_directory_name_is_refused() -> None:
    """Otherwise the first mkdir raises a raw OSError instead of a named refusal."""
    with pytest.raises(TerrainRequestError, match="characters"):
        Outlet(outlet_id="a" * 300, x=0.0, y=0.0)


@pytest.fixture(scope="module")
def real_dem_products(tmp_path_factory) -> dict[str, object]:
    """Run the chain once per engine on the committed valley DEM.

    Module-scoped because the surface is 10 000 cells and three outlets share
    the same products -- which is the point of a batch signature.
    """
    pytest.importorskip("whitebox_workflows")
    root = tmp_path_factory.mktemp("real_dem")
    products = {}
    for name, factory in sorted(ENGINE_FACTORIES.items()):
        engine = factory()
        _conditioned, _directions, accumulation = _products(engine, REAL_DEM, root / name)
        products[name] = (engine, accumulation)
    return products


def _channel_outlet(column: int, accumulation_path: Path) -> tuple[Outlet, float]:
    """The highest-accumulation cell of one column: the channel at that section."""
    with rasterio.open(str(accumulation_path)) as src:
        counts = src.read(1)
        row = int(np.argmax(counts[:, column]))
        x, y = src.xy(row, column)
        resolution = float(abs(src.transform.a))
    return Outlet(outlet_id=f"channel_col_{column}", x=float(x), y=float(y)), resolution


@pytest.mark.parametrize("column", [25, 50, 75])
def test_the_two_engines_agree_on_a_real_dem(real_dem_products, tmp_path, column) -> None:
    """Same DEM, same channel section, two engines: the areas have to agree.

    This is the assertion the analytic terrains cannot make: on a real surface
    the flats are real -- 10 000 cells hold 541 distinct elevations here -- and
    two engines are entitled to resolve them their own way. The sections are
    taken mid-basin so the catchment is a proper subset of the domain (3.19,
    1.63 and 0.42 km2) and not the whole grid, which would agree trivially.

    The band is row 74 of ``tests/TOLERANCES.md``. Measured gap: exactly zero,
    on all three sections, and the conditioned DEM, the pointer and the
    accumulation are identical cell for cell. The band is kept rather than
    tightened to equality because cross-engine tie-breaking is not a property
    either engine promises.
    """
    areas = {}
    for name, (engine, accumulation) in sorted(real_dem_products.items()):
        outlet, resolution = _channel_outlet(column, accumulation.path)
        (catchment,) = engine.delineate(
            accumulation,
            [outlet],
            out_dir=tmp_path / name,
            snap_distance_m=2 * resolution,
        )
        areas[name] = catchment.area_m2 / 1_000_000.0

    assert min(areas.values()) > 0.0
    assert max(areas.values()) < 6.25, "a section catchment cannot be the whole 6.25 km2 domain"
    gap_km2 = abs(areas["numpy_d8"] - areas["whitebox_workflows"])
    assert gap_km2 <= tol("terrain_engine_conformance__cross_engine_catchment_area"), areas


def test_the_second_engine_reproduces_the_production_chain_on_a_real_dem(
    real_dem_products,
) -> None:
    """The numpy engine is not a stub: it reproduces Whitebox cell for cell here.

    Measured on the committed valley DEM: the filled DEM, the D8 pointer and the
    accumulation are identical, 0 differing cells of 10 000. That is what makes
    the conformance suite a comparison of two implementations rather than of one
    implementation and a placeholder.
    """
    numpy_acc = real_dem_products["numpy_d8"][1]
    whitebox_acc = real_dem_products["whitebox_workflows"][1]

    for numpy_product, whitebox_product in (
        (numpy_acc.directions.conditioned_dem, whitebox_acc.directions.conditioned_dem),
        (numpy_acc.directions, whitebox_acc.directions),
        (numpy_acc, whitebox_acc),
    ):
        assert np.array_equal(_read(numpy_product.path), _read(whitebox_product.path)), (
            numpy_product.path
        )


@pytest.mark.parametrize(
    "dem_name",
    ["tests/data/sfr_cheze/dem_valley.tif", "examples/data/dem/DEM_gouville_25m.tif"],
)
def test_conditioning_leaves_no_interior_cell_without_a_way_out(engine, tmp_path, dem_name) -> None:
    """After conditioning, no cell inside a real DEM may drain nowhere.

    This is the assertion the analytic terrains could not make and the one a
    second engine actually needs: before the fill resolved plateaus, the numpy
    engine left **637 of 5 400** cells of the coastal DEM coded as draining
    nowhere, and under-reported the largest upstream area eightfold, while every
    test on the plane and the valley stayed green. Both engines now leave zero,
    which is exact and needs no band.

    A cell on the frame is excluded: it has no downstream neighbour inside the
    grid by construction, and that is not a defect. Neither is a cell beside an
    absent one -- see the nodata test below, where both engines agree that an
    absent cell is not a drainage target.
    """
    dem = Path(__file__).resolve().parents[2] / dem_name
    _conditioned, directions, _accumulation = _products(engine, dem, tmp_path / "out")
    codes = _read(directions.path)
    interior = _interior_data_cells(codes)

    assert int(np.count_nonzero((codes == 0) & interior)) == 0


# --------------------------------------------------------------------------- #
# Where the artefacts land
# --------------------------------------------------------------------------- #


def test_a_flat_layout_writes_the_two_files_the_caller_named(engine, valley, tmp_path) -> None:
    """What makes the port adoptable by a pipeline with a published layout."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)

    (catchment,) = engine.delineate(
        accumulation,
        [_valley_exit()],
        out_dir=out / "geographic",
        snap_distance_m=RES,
        layout=CatchmentLayout.flat(mask_name="watershed.tif", boundary_name="watershed.shp"),
    )

    assert catchment.mask_path == out / "geographic" / "watershed.tif"
    assert catchment.boundary_path == out / "geographic" / "watershed.shp"
    assert catchment.mask_path.is_file() and catchment.boundary_path.is_file()
    # And it still answers the question: the valley drains through its exit.
    assert catchment.cell_count == 31 * 31


def test_a_flat_layout_refuses_a_batch(engine, valley, tmp_path) -> None:
    """Two outlets, one pair of files: the second would eat the first."""
    out = tmp_path / "out"
    _conditioned, _directions, accumulation = _products(engine, valley, out)
    outlets = [
        _valley_exit(),
        Outlet(outlet_id="mid_floor", x=(15 + 0.5) * RES, y=(31 - 20 - 0.5) * RES),
    ]

    with pytest.raises(TerrainRequestError, match="flat layout"):
        engine.delineate(
            accumulation,
            outlets,
            out_dir=out / "geographic",
            snap_distance_m=RES,
            layout=CatchmentLayout.flat(mask_name="w.tif", boundary_name="w.shp"),
        )


@pytest.mark.parametrize(
    ("mask_name", "boundary_name"),
    [
        ("../escape.tif", "boundary.shp"),
        ("sub/mask.tif", "boundary.shp"),
        ("mask.tif", "boundary.geojson"),
        ("mask.asc", "boundary.shp"),
        ("", "boundary.shp"),
    ],
)
def test_a_layout_refuses_a_name_that_is_not_one(mask_name, boundary_name) -> None:
    """A name carrying a separator writes outside the directory that was named."""
    with pytest.raises(TerrainRequestError):
        CatchmentLayout.flat(mask_name=mask_name, boundary_name=boundary_name)


@pytest.mark.parametrize("boundary_name", [OUTLET_LAYER_NAME, SNAPPED_OUTLET_LAYER_NAME])
def test_a_flat_layout_refuses_to_land_on_the_outlet_layer(boundary_name) -> None:
    """The boundary would overwrite the point the delineation ran from."""
    with pytest.raises(TerrainRequestError, match="point layer"):
        CatchmentLayout.flat(mask_name="watershed.tif", boundary_name=boundary_name)


def test_the_per_outlet_layout_has_no_such_collision() -> None:
    """A directory per outlet separates them, so the same name is legal there."""
    layout = CatchmentLayout(
        per_outlet_directory=True,
        mask_name="mask.tif",
        boundary_name=OUTLET_LAYER_NAME,
    )
    assert layout.boundary_name == OUTLET_LAYER_NAME


# --------------------------------------------------------------------------- #
# What float32 stops resolving
# --------------------------------------------------------------------------- #


def test_a_transformed_accumulation_in_square_metres_is_refused(engine, valley, tmp_path) -> None:
    """The bound is measured for bare counts only, so nothing else may claim it."""
    out = tmp_path / "out"
    _c, _d, accumulation = _products(engine, valley, out, units="m2")
    transformed = replace(accumulation, transform="ln")

    with pytest.raises(TerrainProductError, match="cells"):
        engine.delineate(transformed, [_valley_exit()], out_dir=out / "c", snap_distance_m=RES)


def test_an_accumulation_float32_cannot_order_is_refused(engine, valley, tmp_path) -> None:
    """Above the measured count, a snap window ties on cells of different area.

    The raster is written here rather than routed, because reaching
    ``LN_FLOAT32_COLLISION_COUNT`` by routing needs a million-cell DEM. What is
    under test is the refusal, and the refusal reads the stored values.
    """
    out = tmp_path / "out"
    _c, _d, accumulation = _products(engine, valley, out)

    over = out / "acc_over_the_bound.tif"
    with rasterio.open(str(accumulation.path)) as src:
        profile = src.profile.copy()
        shape = (src.height, src.width)
    profile.update(dtype="float32", count=1)
    values = np.full(shape, math.log(LN_FLOAT32_COLLISION_COUNT + 1), dtype="float32")
    with rasterio.open(str(over), "w", **profile) as dst:
        dst.write(values, 1)
    too_large = replace(accumulation, path=over, transform="ln")

    with pytest.raises(TerrainProductError, match="float32"):
        engine.delineate(too_large, [_valley_exit()], out_dir=out / "c", snap_distance_m=RES)


def test_the_bound_does_not_fire_on_anything_this_repository_routes(
    engine, valley, tmp_path
) -> None:
    """Anti-vacuity: the guard has to let the real products through."""
    out = tmp_path / "out"
    _c, _d, accumulation = _products(engine, valley, out, transform="ln")

    (catchment,) = engine.delineate(
        accumulation, [_valley_exit()], out_dir=out / "c", snap_distance_m=RES
    )

    assert catchment.cell_count == 31 * 31
