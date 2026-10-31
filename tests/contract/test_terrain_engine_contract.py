"""Conformance suite for the terrain port, run against every engine the registry serves.

An engine installed beside this build is run without a line of ``tests/`` naming
it, and held to the files on disk no declaration mentions. The plane and the V
valley hold no tie, so their assertions are exact. On ``dem_valley.tif`` the two
in-tree engines agree cell for cell; on ``DEM_gouville_25m.tif`` they do not
(1 459 against 587 exit cells), so only "no interior cell drains nowhere" is asserted.
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
    CappedBreach,
    CatchmentLayout,
    ConditioningExtent,
    DrainageDirections,
    JensonSnap,
    Outlet,
    TerrainEngine,
    missing_engine_members,
    registry,
    snap_window_cells,
)
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.tolerances import tol

rasterio = pytest.importorskip("rasterio")

RES = 25.0
CELL_AREA_M2 = RES * RES
CRS = "EPSG:2154"
NODATA = -9999.0
ROOT = Path(__file__).resolve().parents[2]
REAL_DEM = ROOT / "tests" / "data" / "sfr_cheze" / "dem_valley.tif"
_REAL_DEMS = ["tests/data/sfr_cheze/dem_valley.tif", "examples/data/dem/DEM_gouville_25m.tif"]
CAPPED = CappedBreach(max_depth_m=0.5, max_distance_m=200.0)

IN_TREE_ENGINE_IDS = ("numpy_d8", "whitebox_workflows")
"""The two engines this repository ships, read by the cross-engine agreement tests only."""


def _engine(engine_id: str):
    """Build what the registry serves under *engine_id*.

    A built-in this environment cannot load is a skip (Whitebox is an optional
    extra). A plugin that survived ``load_plugins`` and fails to build is a defect.
    Whitebox is pinned to one worker first, for determinism, not for selection.
    """
    if engine_id == "whitebox_workflows":
        pytest.importorskip("whitebox_workflows")
        from tests._helpers.whitebox import configure_whitebox_single_thread

        monkeypatch = pytest.MonkeyPatch()
        configure_whitebox_single_thread(monkeypatch)
        monkeypatch.undo()
    try:
        return registry.create(engine_id)
    except TerrainRequestError:
        if engine_id in registry.builtin_engine_ids():
            pytest.skip(f"{engine_id!r} is declared by this build and not installed here")
        raise


@pytest.fixture(scope="module", params=registry.list_engine_ids())
def engine(request):
    """One terrain engine, once per implementation this installation serves (stateless)."""
    return _engine(request.param)


def _write_dem(path: Path, surface: np.ndarray) -> Path:
    return write_geotiff(path, surface, cell=RES, crs=CRS, nodata=NODATA, dtype="float32")


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


def _drains_nowhere(directions) -> int:
    """Interior data cells coded 0, away from the frame and from any absent cell."""
    codes = _read(directions.path)
    absent = codes == -32768
    interior = np.zeros(codes.shape, dtype=bool)
    interior[1:-1, 1:-1] = True
    beside_a_hole = np.zeros(codes.shape, dtype=bool)
    for drow in (-1, 0, 1):
        for dcol in (-1, 0, 1):
            beside_a_hole |= np.roll(np.roll(absent, drow, axis=0), dcol, axis=1)
    return int(np.count_nonzero((codes == 0) & interior & ~absent & ~beside_a_hole))


@pytest.fixture(scope="module")
def plane_east(tmp_path_factory) -> Path:
    return _write_dem(tmp_path_factory.mktemp("plane") / "plane_east.tif", _plane(30, 0, 1))


@pytest.fixture(scope="module")
def valley(tmp_path_factory) -> Path:
    return _write_dem(tmp_path_factory.mktemp("valley") / "valley.tif", _valley(31))


def _condition(engine, dem: Path, out: Path, method="fill"):
    """Condition the whole DEM, the regional extent every caller of this tree uses."""
    return engine.condition_dem(dem, method=method, extent=ConditioningExtent.regional(), out=out)


def _products(engine, dem: Path, out: Path, *, method="fill", units="cells", transform="none"):
    """Run the chain a caller runs: condition, point, accumulate."""
    conditioned = _condition(engine, dem, out / "conditioned.tif", method)
    directions = engine.drainage_directions(conditioned, out=out / "pointer.tif")
    accumulation = engine.flow_accumulation(
        directions, units=units, transform=transform, out=out / f"acc_{units}_{transform}.tif"
    )
    return conditioned, directions, accumulation


@pytest.fixture(scope="module")
def valley_chain(engine, valley, tmp_path_factory):
    """The valley chain per ``(units, transform)``, run once and shared read-only."""
    root = tmp_path_factory.mktemp("valley_chain")
    cache: dict[tuple[str, str], tuple] = {}

    def chain(units: str = "cells", transform: str = "none"):
        if (units, transform) not in cache:
            out = root / f"{units}_{transform}"
            cache[units, transform] = _products(
                engine, valley, out, units=units, transform=transform
            )
        return cache[units, transform]

    return chain


def _accumulation(valley_chain, units: str = "cells", transform: str = "none"):
    return valley_chain(units, transform)[2]


def test_an_engine_satisfies_the_port_with_a_stable_digest(engine) -> None:
    assert missing_engine_members(engine) == ()
    assert isinstance(engine, TerrainEngine)
    assert engine.engine_digest() == engine.engine_digest()


def test_no_two_engines_share_a_digest() -> None:
    """The digest stamps a sealed job, so two engines must never answer the same one."""
    digests = {}
    for engine_id in registry.list_engine_ids():
        try:
            digests[engine_id] = registry.create(engine_id).engine_digest()
        except TerrainRequestError:
            if engine_id not in registry.builtin_engine_ids():
                raise
            # A built-in this environment cannot load; skipped below if alone.
            continue

    if len(digests) < 2:
        pytest.skip(f"only {sorted(digests)} resolves here, and one digest compares to nothing")
    assert len(set(digests.values())) == len(digests), digests


def _flat_layout(mask_name: str, boundary_name: str):
    return lambda: CatchmentLayout.flat(mask_name=mask_name, boundary_name=boundary_name)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        pytest.param(lambda: Outlet(outlet_id="../escape", x=0.0, y=0.0), None, id="outlet_id_not_a_directory_name"),
        # Otherwise the first mkdir raises a raw OSError instead of a named refusal.
        pytest.param(lambda: Outlet(outlet_id="a" * 300, x=0.0, y=0.0), "characters", id="outlet_id_too_long"),
        pytest.param(lambda: ConditioningExtent(kind="per_outlet_buffer"), "buffer", id="buffer_extent_without_its_buffer"),
        pytest.param(lambda: ConditioningExtent(kind="regional", buffer_distance_m=100.0), "buffer", id="regional_extent_with_a_buffer"),
        pytest.param(lambda: ConditioningExtent(kind="ridge"), "Unknown conditioning extent", id="unknown_extent"),
        # A name carrying a separator writes outside the directory that was named.
        pytest.param(_flat_layout("../escape.tif", "boundary.shp"), None, id="mask_escapes"),
        pytest.param(_flat_layout("sub/mask.tif", "boundary.shp"), None, id="mask_in_a_sub_directory"),
        pytest.param(_flat_layout("mask.tif", "boundary.geojson"), None, id="boundary_not_a_shapefile"),
        pytest.param(_flat_layout("mask.asc", "boundary.shp"), None, id="mask_not_a_geotiff"),
        pytest.param(_flat_layout("", "boundary.shp"), None, id="empty_mask_name"),
        # The boundary would overwrite the point the delineation ran from.
        pytest.param(_flat_layout("watershed.tif", OUTLET_LAYER_NAME), "point layer", id="boundary_on_the_outlet_layer"),
        pytest.param(_flat_layout("watershed.tif", SNAPPED_OUTLET_LAYER_NAME), "point layer", id="boundary_on_the_snapped_outlet_layer"),
    ],
)  # fmt: skip
def test_a_port_value_that_names_nothing_usable_is_refused(build, match) -> None:
    with pytest.raises(TerrainRequestError, match=match):
        build()


def test_the_per_outlet_layout_has_no_such_collision() -> None:
    """A directory per outlet separates them, so the same name is legal there."""
    layout = CatchmentLayout(True, mask_name="mask.tif", boundary_name=OUTLET_LAYER_NAME)
    assert layout.boundary_name == OUTLET_LAYER_NAME


def test_conditioning_raises_a_pit_to_its_lowest_way_out(engine, tmp_path) -> None:
    surface = _plane(21, 0, 1)
    pit = (10, 10)
    surface[pit] -= 20.0
    dem = _write_dem(tmp_path / "pitted.tif", surface)
    neighbours = [surface[pit[0] + dr, pit[1] + dc] for dr, dc in D8_WBT_OFFSETS.values()]
    filled = _read(_condition(engine, dem, tmp_path / "out" / "conditioned.tif").path)
    # An engine resolving plateaus in the fill may stop one float32 above the way out.
    lowest = np.float32(min(neighbours))
    assert lowest <= filled[pit] <= np.nextafter(lowest, np.float32(np.inf))
    assert int(np.count_nonzero(filled != surface.astype("float32"))) == 1
    assert float(np.min(filled - surface.astype("float32"))) >= 0.0


@pytest.mark.parametrize(
    ("method", "extent"),
    [("fill", ConditioningExtent.per_outlet_buffer(500.0)), ("carve", ConditioningExtent.regional())],
    ids=["extent", "method"],
)  # fmt: skip
def test_a_conditioning_no_engine_serves_is_refused(
    engine, plane_east, tmp_path, method, extent
) -> None:
    with pytest.raises(TerrainCapabilityError):
        engine.condition_dem(plane_east, method=method, extent=extent, out=tmp_path / "c.tif")


@pytest.mark.parametrize("method", ["breach", CAPPED], ids=["breach", "capped"])
def test_the_numpy_engine_refuses_breaching_by_name(plane_east, tmp_path, method) -> None:
    with pytest.raises(TerrainCapabilityError, match="breach"):
        _condition(_engine("numpy_d8"), plane_east, tmp_path / "c.tif", method)


def test_the_numpy_engine_refuses_a_pointer_that_holds_a_cycle(valley, tmp_path) -> None:
    """Two cells pointing at each other, written by hand: no conditioning makes one."""
    engine = _engine("numpy_d8")
    out = tmp_path / "out"
    _conditioned, directions, _acc = _products(engine, valley, out)
    codes = _read(directions.path).copy()
    codes[5, 5], codes[5, 6] = 2, 32  # east, west
    cyclic = write_geotiff(out / "cyclic_pointer.tif", codes, cell=RES, crs=CRS, nodata=-32768)
    pointer = DrainageDirections(
        path=cyclic, pointer_convention="d8_wbt", conditioned_dem=directions.conditioned_dem
    )

    with pytest.raises(TerrainProductError, match="cycle"):
        engine.flow_accumulation(
            pointer, units="cells", transform="none", out=out / "acc_cyclic.tif"
        )


@pytest.mark.parametrize("code", sorted(D8_WBT_OFFSETS))
def test_the_pointer_writes_the_code_its_convention_declares(engine, code, tmp_path) -> None:
    """A plane tilted at one octant carries that octant's code, read from the table (C6)."""
    dem = _write_dem(tmp_path / f"plane_{code}.tif", _plane(40, *D8_WBT_OFFSETS[code]))
    _conditioned, directions, _acc = _products(engine, dem, tmp_path / "out")
    inner = _read(directions.path)[5:-5, 5:-5]
    assert directions.pointer_convention == "d8_wbt"
    values, counts = np.unique(inner[inner > 0], return_counts=True)
    assert int(values[np.argmax(counts)]) == code


def test_a_draining_plane_is_left_alone_its_edge_drains_nowhere_and_row_j_counts_1_2_3(
    engine, plane_east, tmp_path
) -> None:
    """Conditioning moves nothing, only the downslope edge is coded 0, and a cell counts itself."""
    conditioned, directions, accumulation = _products(engine, plane_east, tmp_path / "out")
    codes, values = _read(directions.path), _read(accumulation.path)
    assert np.array_equal(_read(conditioned.path), _read(plane_east))
    assert int(np.count_nonzero(codes == 0)) == codes.shape[0]
    assert np.all(codes[:, -1] == 0)
    expected = np.tile(np.arange(1, values.shape[1] + 1, dtype="float32"), (values.shape[0], 1))
    assert np.array_equal(values, expected)


def test_m2_is_the_count_times_the_cell_area_and_ln_its_natural_logarithm(valley_chain) -> None:
    """A reader assuming base 10 for ``ln`` would be off by a factor 2.3."""
    counts = _read(_accumulation(valley_chain).path)
    logged = _read(_accumulation(valley_chain, transform="ln").path).astype("float64")
    positive = counts > 0
    gap = np.abs(np.log(counts[positive].astype("float64")) - logged[positive])
    assert np.array_equal(_read(_accumulation(valley_chain, "m2").path), counts * CELL_AREA_M2)
    assert float(gap.max()) <= tol("terrain_engine_conformance__ln_transform_identity")


@pytest.mark.parametrize(("units", "transform"), [("cells", "log10"), ("km2", "none")])
def test_an_accumulation_no_engine_serves_is_refused(
    engine, valley_chain, tmp_path, units, transform
) -> None:
    directions = valley_chain()[1]
    with pytest.raises(TerrainCapabilityError):
        engine.flow_accumulation(
            directions, units=units, transform=transform, out=tmp_path / "a.tif"
        )


@pytest.mark.parametrize("transform", ["none", "ln"])
def test_no_valid_cell_carries_the_nodata_the_product_declares(valley_chain, transform) -> None:
    """A headwater of the ln product reads 0, so a nodata of 0 would mask it."""
    accumulation = _accumulation(valley_chain, transform=transform)
    with rasterio.open(str(accumulation.path)) as src:
        assert src.nodata == accumulation.nodata
        assert int(np.count_nonzero(src.read(1, masked=True).mask)) == 0
    assert int(np.count_nonzero(_read(accumulation.path) == accumulation.nodata)) == 0


@pytest.mark.parametrize("threshold", [10.0, 20.0, 50.0])
def test_a_threshold_selects_the_cells_that_carry_more_than_it(
    engine, valley_chain, tmp_path, threshold
) -> None:
    """The channel count is the cell count above the threshold, exactly (C5)."""
    accumulation = _accumulation(valley_chain)
    streams = engine.stream_network(accumulation, threshold=threshold, out=tmp_path / "s.tif")
    selected = int(np.count_nonzero(_read(streams.path) == 1))
    assert selected == int(np.count_nonzero(_read(accumulation.path) > threshold))
    assert streams.threshold_units == "cells"


@pytest.mark.parametrize(
    ("transform", "threshold", "error", "match"),
    [
        # R1: a cell threshold on a log raster selects nothing, silently. This
        # refusal replaces the ``looks_log_scaled`` runtime heuristic.
        ("ln", 20.0, TerrainProductError, "transform"),
        ("none", 0.0, TerrainRequestError, None),
    ],
    ids=["transformed_accumulation", "non_positive_threshold"],
)
def test_a_stream_network_that_would_select_nothing_is_refused(
    engine, valley_chain, tmp_path, transform, threshold, error, match
) -> None:
    accumulation = _accumulation(valley_chain, transform=transform)
    with pytest.raises(error, match=match):
        engine.stream_network(accumulation, threshold=threshold, out=tmp_path / "streams.tif")


_VALLEY_EXIT = Outlet(outlet_id="valley_exit", x=(15 + 0.5) * RES, y=RES * 0.5)
"""The cell every cell of the V valley drains through."""
_MID_FLOOR = Outlet(outlet_id="mid_floor", x=(15 + 0.5) * RES, y=(31 - 20 - 0.5) * RES)
_OFF_TALWEG = Outlet(outlet_id="off_talweg", x=(15 - 2 + 0.5) * RES, y=(31 - 28 - 0.5) * RES)
"""Two cells west of the floor, three rows above the exit, on purpose."""


def _exit_catchment(engine, accumulation, out_dir: Path, snap_distance_m: float, **options):
    """The one catchment of the valley exit."""
    (catchment,) = engine.delineate(
        accumulation, [_VALLEY_EXIT], out_dir=out_dir, snap_distance_m=snap_distance_m, **options
    )
    return catchment


@pytest.fixture(scope="module")
def valley_catchment(engine, valley_chain, tmp_path_factory):
    """The catchment of the valley exit, delineated once per engine."""
    out = tmp_path_factory.mktemp("valley_catchment")
    return _exit_catchment(engine, _accumulation(valley_chain), out, RES * 4)


def test_the_whole_valley_drains_through_its_exit(valley_catchment) -> None:
    """And the mask marks the catchment and nothing else."""
    mask = _read(valley_catchment.mask_path)
    assert valley_catchment.cell_count == 31 * 31
    assert valley_catchment.area_m2 == pytest.approx(31 * 31 * CELL_AREA_M2, rel=0.0, abs=1e-6)
    assert valley_catchment.outlet.outlet_id == "valley_exit"
    assert set(np.unique(mask).tolist()) <= {1, -32768}
    assert int(np.count_nonzero(mask == 1)) == valley_catchment.cell_count


def test_a_batch_answers_every_outlet_in_the_order_it_was_given(
    engine, valley_chain, tmp_path
) -> None:
    """N outlets against one accumulation, each with its own directory."""
    left = Outlet(outlet_id="left_side", x=(15 - 6 + 0.5) * RES, y=(31 - 20 - 0.5) * RES)
    outlets = [left, _VALLEY_EXIT, _MID_FLOOR]
    catchments = engine.delineate(
        _accumulation(valley_chain), outlets, out_dir=tmp_path / "c", snap_distance_m=RES
    )
    assert [c.outlet.outlet_id for c in catchments] == [o.outlet_id for o in outlets]
    assert all(c.mask_path.is_file() and c.boundary_path.is_file() for c in catchments)
    assert all(c.mask_path.parent.name == c.outlet.outlet_id for c in catchments)
    # The valley exit drains everything, so no sibling catchment can be larger.
    assert max(c.cell_count for c in catchments) == catchments[1].cell_count


@pytest.mark.parametrize(
    ("cells", "window"), [(4, (2, 2)), (1, (0, 0))], ids=["window_max", "narrower_than_two_cells"]
)
def test_a_snapped_outlet_is_the_accumulation_maximum_of_its_window(
    engine, valley_chain, tmp_path, cells, window
) -> None:
    """The window is a square of half-width ``floor(snap_distance_m / (2 * cell))`` cells.

    A Euclidean radius passes on numpy and fails on Whitebox. A snap distance of
    one cell size therefore moves nothing: the smallest one that moves is two cells.
    """
    accumulation = _accumulation(valley_chain)
    declared = _OFF_TALWEG
    snap_distance_m = cells * RES

    (catchment,) = engine.delineate(
        accumulation, [declared], out_dir=tmp_path / "c", snap_distance_m=snap_distance_m
    )

    counts = _read(accumulation.path)
    reach_rows, reach_cols = snap_window_cells(snap_distance_m, dx=RES, dy=RES)
    with rasterio.open(str(accumulation.path)) as src:
        snapped_row, snapped_col = src.index(catchment.snapped_x, catchment.snapped_y)
        row0, col0 = src.index(declared.x, declared.y)
    searched = counts[row0 - reach_rows : row0 + reach_rows + 1, col0 - reach_cols : col0 + reach_cols + 1]  # fmt: skip
    assert (reach_rows, reach_cols) == window
    assert counts[snapped_row, snapped_col] == searched.max()
    assert catchment.snap_distance_m == pytest.approx(
        math.hypot(catchment.snapped_x - declared.x, catchment.snapped_y - declared.y)
    )
    if window == (0, 0):
        assert catchment.snap_distance_m == pytest.approx(0.0)
        assert (catchment.snapped_x, catchment.snapped_y) == pytest.approx((declared.x, declared.y))


def test_a_jenson_snap_lands_on_a_stream_cell_or_the_engine_refuses_it_by_name(
    engine, valley_chain, tmp_path
) -> None:
    """An engine serves the snap method or says it cannot; served, it lands on the network.

    The two engines of this tree are held to the cell in
    ``tests/unit/geographic/core/test_catchment_from_point.py``.
    """
    accumulation = _accumulation(valley_chain)
    streams = engine.stream_network(accumulation, threshold=60.0, out=tmp_path / "streams.tif")

    try:
        (catchment,) = engine.delineate(
            accumulation, [_OFF_TALWEG], out_dir=tmp_path / "catchments",
            snap_distance_m=4 * RES, snap=JensonSnap(streams=streams),
        )  # fmt: skip
    except TerrainCapabilityError:
        return

    with rasterio.open(str(streams.path)) as src:
        row, col = src.index(catchment.snapped_x, catchment.snapped_y)
    assert _read(streams.path)[row, col] == 1
    assert catchment.snap_distance_m == pytest.approx(2 * RES)


def test_delineation_repeats_cell_for_cell(engine, valley_chain, tmp_path) -> None:
    accumulation = _accumulation(valley_chain)
    masks = [
        _read(_exit_catchment(engine, accumulation, tmp_path / str(i), RES).mask_path)
        for i in range(2)
    ]
    assert masks[0].tobytes() == masks[1].tobytes()


@pytest.mark.parametrize(("units", "transform"), [("cells", "ln"), ("m2", "none")])
def test_a_rank_preserving_product_delineates_the_same_catchment(
    engine, valley_chain, valley_catchment, tmp_path, units, transform
) -> None:
    """A snap is a rank, so the geographic pipeline may hand the engine its ``ln`` raster."""
    expected = valley_catchment
    measured = _exit_catchment(
        engine, _accumulation(valley_chain, units, transform), tmp_path, RES * 4
    )
    assert (measured.snapped_x, measured.snapped_y) == (expected.snapped_x, expected.snapped_y)
    assert measured.cell_count == expected.cell_count
    assert measured.area_m2 == pytest.approx(expected.area_m2, rel=0.0, abs=1e-6)


def test_a_delineation_leaves_the_four_artefacts_the_port_declares(valley_catchment) -> None:
    """The mask, the boundary and the two point layers, the snapped one at the declared point.

    No declaration names these files, and the geographic pipeline reads both point
    layers back. ``NumpyTerrainEngine`` wrote neither until F10a, so a right
    delineation came out of the chain as "no catchment, widen your snap distance".
    """
    site_dir = Path(valley_catchment.mask_path).parent
    for name in (OUTLET_LAYER_NAME, SNAPPED_OUTLET_LAYER_NAME):
        assert (site_dir / name).is_file(), name
    assert Path(valley_catchment.mask_path).is_file()
    assert Path(valley_catchment.boundary_path).is_file()
    geopandas = pytest.importorskip("geopandas")
    point = geopandas.read_file(str(site_dir / SNAPPED_OUTLET_LAYER_NAME)).geometry.iloc[0]
    assert point.x == pytest.approx(valley_catchment.snapped_x, abs=1e-6)
    assert point.y == pytest.approx(valley_catchment.snapped_y, abs=1e-6)


def test_both_point_layers_carry_the_outlet_and_the_coordinates_of_their_own_point(
    engine, valley_chain, tmp_path
) -> None:
    """Every engine writes the same columns, and x and y name the point the layer holds.

    The outlet sits off the talweg, so the snap moves it and the two layers hold
    two different points.
    """
    geopandas = pytest.importorskip("geopandas")
    (catchment,) = engine.delineate(
        _accumulation(valley_chain), [_OFF_TALWEG], out_dir=tmp_path, snap_distance_m=RES * 4
    )
    assert catchment.snap_distance_m > 0.0
    expected = {
        OUTLET_LAYER_NAME: (_OFF_TALWEG.x, _OFF_TALWEG.y),
        SNAPPED_OUTLET_LAYER_NAME: (catchment.snapped_x, catchment.snapped_y),
    }
    for name, point in expected.items():
        frame = geopandas.read_file(str(catchment.mask_path.parent / name))
        columns = [column for column in frame.columns if column != "geometry"]
        assert columns == ["outlet_id", "x", "y"], name
        row = frame.iloc[0]
        assert row["outlet_id"] == _OFF_TALWEG.outlet_id, name
        assert (row["x"], row["y"]) == pytest.approx(point, abs=1e-6), name
        assert (row.geometry.x, row.geometry.y) == pytest.approx(point, abs=1e-6), name


_FLAT = CatchmentLayout.flat(mask_name="w.tif", boundary_name="w.shp")


@pytest.mark.parametrize(
    ("outlets", "units", "transform", "options", "error", "match"),
    [
        pytest.param([], "cells", "none", {}, TerrainRequestError, None, id="empty_batch"),
        # Otherwise the second one overwrites the first one's files, in silence.
        pytest.param([_MID_FLOOR, replace(_MID_FLOOR, x=(15 - 6 + 0.5) * RES)], "cells", "none", {},
            TerrainRequestError, "mid_floor", id="two_outlets_share_an_id"),
        # One directory on a case-insensitive filesystem, so refused on every one.
        pytest.param([_VALLEY_EXIT, replace(_VALLEY_EXIT, outlet_id="VALLEY_EXIT")], "cells", "none", {},
            TerrainRequestError, "case-folded", id="ids_differ_only_by_case"),
        pytest.param([_VALLEY_EXIT], "cells", "none", {"snap_distance_m": 0.0}, TerrainRequestError, None,
            id="non_positive_snap_distance"),
        # Two outlets, one pair of files: the second would eat the first.
        pytest.param([_VALLEY_EXIT, _MID_FLOOR], "cells", "none", {"layout": _FLAT}, TerrainRequestError,
            "flat layout", id="flat_layout_with_a_batch"),
        # The refusal is on the rank, not on the vocabulary of the moment.
        pytest.param([_VALLEY_EXIT], "cells", "rank_destroying", {}, TerrainProductError, "order of the cells",
            id="transform_destroys_the_order"),
        # The float32 bound is measured for bare counts only, so nothing else may claim it.
        pytest.param([_VALLEY_EXIT], "m2", "ln", {}, TerrainProductError, "cells", id="transformed_square_metres"),
    ],
)  # fmt: skip
def test_a_delineation_request_the_port_cannot_answer_is_refused_before_writing(
    engine, valley_chain, tmp_path, outlets, units, transform, options, error, match
) -> None:
    accumulation = replace(_accumulation(valley_chain, units), transform=transform)
    request = {"out_dir": tmp_path / "c", "snap_distance_m": RES, **options}
    with pytest.raises(error, match=match):
        engine.delineate(accumulation, outlets, **request)
    assert not (tmp_path / "c").exists()


def test_a_flat_layout_writes_the_two_files_the_caller_named(
    engine, valley_chain, tmp_path
) -> None:
    """What makes the port adoptable by a pipeline with a published layout."""
    out = tmp_path / "geographic"
    layout = CatchmentLayout.flat(mask_name="watershed.tif", boundary_name="watershed.shp")
    catchment = _exit_catchment(engine, _accumulation(valley_chain), out, RES, layout=layout)
    assert catchment.mask_path == out / "watershed.tif"
    assert catchment.boundary_path == out / "watershed.shp"
    assert catchment.mask_path.is_file() and catchment.boundary_path.is_file()
    assert catchment.cell_count == 31 * 31


def test_every_product_carries_the_crs_and_names_what_it_came_from(
    engine, valley_chain, tmp_path
) -> None:
    conditioned, directions, accumulation = valley_chain()
    streams = engine.stream_network(accumulation, threshold=20.0, out=tmp_path / "streams.tif")
    assert conditioned.crs == CRS
    for product in (conditioned, directions, accumulation, streams):
        with rasterio.open(str(product.path)) as src:
            assert str(src.crs) == CRS
    assert directions.conditioned_dem == conditioned
    assert accumulation.directions == directions
    assert (accumulation.units, accumulation.transform) == ("cells", "none")


def test_an_accumulation_float32_cannot_order_is_refused(engine, valley_chain, tmp_path) -> None:
    """Written rather than routed: reaching the bound by routing needs a million cells."""
    values = np.full((31, 31), math.log(LN_FLOAT32_COLLISION_COUNT + 1))
    over = _write_dem(tmp_path / "acc_over_the_bound.tif", values)
    too_large = replace(_accumulation(valley_chain), path=over, transform="ln")
    with pytest.raises(TerrainProductError, match="float32"):
        _exit_catchment(engine, too_large, tmp_path / "c", RES)


def test_the_bound_does_not_fire_on_anything_this_repository_routes(
    engine, valley_chain, tmp_path
) -> None:
    """Anti-vacuity: the guard has to let the real products through."""
    catchment = _exit_catchment(engine, _accumulation(valley_chain, transform="ln"), tmp_path, RES)
    assert catchment.cell_count == 31 * 31


def test_an_absent_cell_is_no_drainage_target_and_both_engines_say_so(tmp_path) -> None:
    """A hole leaves the pit beside it unfilled, on both engines alike.

    A 3x3 nodata block and a pit whose only low way out crosses it: the pit stays
    at 62 m with no downstream cell. This pins the agreement, not the physics (a
    lake mask is where draining into the hole would be right); see ``condition_dem``.
    """
    pytest.importorskip("whitebox_workflows")
    surface = _plane(21, 0, 1)
    surface[9:12, 9:12] = NODATA
    surface[10, 8] -= 30.0
    dem = _write_dem(tmp_path / "holed.tif", surface)
    products = {name: _products(_engine(name), dem, tmp_path / name) for name in IN_TREE_ENGINE_IDS}
    for left, right in zip(*(products[name] for name in sorted(products)), strict=True):
        assert np.array_equal(_read(left.path), _read(right.path)), left.path
    for name, (_conditioned, directions, _accumulation) in products.items():
        assert _read(directions.path)[10, 8] == 0, name
        assert _drains_nowhere(directions) == 0, name


@pytest.fixture(scope="module")
def real_dem_products(tmp_path_factory) -> dict[str, object]:
    """The chain once per in-tree engine on the committed valley DEM (10 000 cells)."""
    pytest.importorskip("whitebox_workflows")
    root = tmp_path_factory.mktemp("real_dem")
    products = {}
    for name in IN_TREE_ENGINE_IDS:
        engine = _engine(name)
        products[name] = (engine, _products(engine, REAL_DEM, root / name)[2])
    return products


@pytest.mark.parametrize("column", [25, 50, 75])
def test_the_two_engines_agree_on_a_real_dem(real_dem_products, tmp_path, column) -> None:
    """The channel at one section, delineated by both engines (band of row 74).

    The sections are mid-basin (3.19, 1.63 and 0.42 km2), so the catchment is not
    the whole grid. The measured gap is zero; the band stays because cross-engine
    tie-breaking is promised by neither engine.
    """
    areas = {}
    for name, (engine, accumulation) in sorted(real_dem_products.items()):
        with rasterio.open(str(accumulation.path)) as src:
            row = int(np.argmax(src.read(1)[:, column]))
            x, y = src.xy(row, column)
            resolution = float(abs(src.transform.a))
        outlet = Outlet(outlet_id=f"channel_col_{column}", x=float(x), y=float(y))
        (catchment,) = engine.delineate(
            accumulation, [outlet], out_dir=tmp_path / name, snap_distance_m=2 * resolution
        )
        areas[name] = catchment.area_m2 / 1_000_000.0

    assert min(areas.values()) > 0.0
    assert max(areas.values()) < 6.25, "a section catchment cannot be the whole 6.25 km2 domain"
    gap_km2 = abs(areas["numpy_d8"] - areas["whitebox_workflows"])
    assert gap_km2 <= tol("terrain_engine_conformance__cross_engine_catchment_area"), areas


def test_the_second_engine_reproduces_the_production_chain_on_a_real_dem(
    real_dem_products,
) -> None:
    """Filled DEM, pointer and accumulation are identical: numpy is no stub."""
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


@pytest.mark.parametrize("dem_name", _REAL_DEMS)
def test_conditioning_leaves_no_interior_cell_without_a_way_out(engine, tmp_path, dem_name) -> None:
    """Before the fill resolved plateaus, numpy left 637 of 5 400 coastal cells draining nowhere."""
    directions = _products(engine, ROOT / dem_name, tmp_path / "out")[1]
    assert _drains_nowhere(directions) == 0


@pytest.mark.parametrize("dem_name", _REAL_DEMS)
def test_a_capped_breach_leaves_no_interior_cell_without_a_way_out(tmp_path, dem_name) -> None:
    """Breaching leaves the depressions its limits refused; zero says the fill ran after it."""
    engine = _engine("whitebox_workflows")
    directions = _products(engine, ROOT / dem_name, tmp_path / "out", method=CAPPED)[1]
    assert _drains_nowhere(directions) == 0


def test_a_capped_breach_reports_what_it_dug_and_nothing_else_does(valley, tmp_path) -> None:
    engine = _engine("whitebox_workflows")
    capped = _condition(engine, valley, tmp_path / "capped.tif", CAPPED)
    filled = _condition(engine, valley, tmp_path / "filled.tif")
    assert capped.breach_report is not None
    assert capped.breach_report.max_dist_cells == 8
    assert filled.breach_report is None


def test_every_engine_serves_a_capped_breach_with_its_report_or_refuses_it(
    engine, tmp_path
) -> None:
    """An engine reading a ``CappedBreach`` as a fill passes neither branch."""
    surface = _valley(31)
    surface[20:23, 14:17] -= 3.0
    dem = _write_dem(tmp_path / "pit.tif", surface)
    try:
        conditioned = _condition(engine, dem, tmp_path / "out" / "conditioned.tif", CAPPED)
    except TerrainCapabilityError:
        return
    assert conditioned.breach_report is not None
    directions = engine.drainage_directions(conditioned, out=tmp_path / "out" / "pointer.tif")
    assert _drains_nowhere(directions) == 0
