"""A Jenson snap keeps an outlet on the nearest stream, where the window snap can jump.

Two valleys run side by side down one slope. The outlet is declared two cells
from the floor of the small one, and the floor of a larger one lies five cells
away, still inside the snap window. The window snap takes the largest
accumulation of the window, which is on the larger valley, so it delineates the
wrong catchment. The Jenson snap takes the nearest cell of the stream network
and stays on the stream the outlet was declared on.

The surface is tie-free by construction, so the answers are exact and the two
engines of the tree can be held to them.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from hydromodpy.core.exceptions import TerrainProductError, TerrainRequestError
from hydromodpy.spatial.geographic.core.catchment_from_point import extract_catchment_from_point
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.geographic.core.pipeline_steps import build_standard_catchment
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.pipeline import _geographic_cache_fingerprint
from hydromodpy.spatial.terrain import (
    ConditioningExtent,
    JensonSnap,
    Outlet,
    registry,
)

# Whitebox's native binding is not fork-safe under xdist distribution.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

RES = 25.0
SIZE = 41
CRS = "EPSG:2154"
SMALL_FLOOR = 8
LARGE_FLOOR = 15
LAST_SMALL_COLUMN = 11
"""The ridge sits between columns 11 and 12, so the small valley is columns 0 to 11."""

OUTLET_ROW = 25
OUTLET_COL = 10
SNAP_DISTANCE_M = 250.0
"""Five cells each side: the window holds both floors, at 2 and 5 cells."""

THRESHOLD_CELLS = 100.0
"""Above what a valley side accumulates, below what either floor does by row 8."""


def _two_valleys() -> np.ndarray:
    rows, cols = np.mgrid[0:SIZE, 0:SIZE]
    walls = np.minimum(np.abs(cols - SMALL_FLOOR), np.abs(cols - LARGE_FLOOR))
    return 100.0 - rows * 0.5 + walls * 2.0


def _write_dem(path: Path) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=SIZE,
        width=SIZE,
        count=1,
        dtype="float32",
        crs=CRS,
        nodata=-9999.0,
        transform=rasterio.transform.from_origin(0.0, SIZE * RES, RES, RES),
    ) as dst:
        dst.write(_two_valleys().astype("float32"), 1)
    return path


def _centre_x(col: int) -> float:
    return (col + 0.5) * RES


def _centre_y(row: int) -> float:
    return (SIZE - row - 0.5) * RES


def _declared() -> Outlet:
    return Outlet(outlet_id="declared", x=_centre_x(OUTLET_COL), y=_centre_y(OUTLET_ROW))


@pytest.fixture(
    params=[
        "numpy_d8",
        # Whitebox fills depressions in a child interpreter.
        pytest.param("whitebox_workflows", marks=pytest.mark.allow_subprocess),
    ]
)
def engine(request):
    if request.param == "whitebox_workflows":
        pytest.importorskip("whitebox_workflows")
        from tests._helpers.whitebox import configure_whitebox_single_thread

        monkeypatch = pytest.MonkeyPatch()
        configure_whitebox_single_thread(monkeypatch)
        monkeypatch.undo()
    return registry.create(request.param)


@pytest.fixture
def products(engine, tmp_path):
    """The chain a caller runs: condition, point, accumulate, draw the streams."""
    out = tmp_path / "out"
    conditioned = engine.condition_dem(
        _write_dem(tmp_path / "dem.tif"),
        method="fill",
        extent=ConditioningExtent.regional(),
        out=out / "conditioned.tif",
    )
    directions = engine.drainage_directions(conditioned, out=out / "pointer.tif")
    accumulation = engine.flow_accumulation(
        directions, units="cells", transform="none", out=out / "acc.tif"
    )
    streams = engine.stream_network(accumulation, threshold=THRESHOLD_CELLS, out=out / "s.tif")
    return directions, accumulation, streams, out


def _delineate(engine, accumulation, out, *, snap, outlet=None):
    (catchment,) = engine.delineate(
        accumulation,
        [outlet or _declared()],
        out_dir=out / "catchment",
        snap_distance_m=SNAP_DISTANCE_M,
        snap=snap,
    )
    return catchment


def _mask_columns(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        data = src.read(1)
    return np.unique(np.nonzero(data == 1)[1])


def test_the_window_snap_jumps_onto_the_larger_neighbour(engine, products) -> None:
    """The failure the Jenson snap exists for, measured."""
    _directions, accumulation, _streams, out = products

    catchment = _delineate(engine, accumulation, out, snap="window")

    assert catchment.snapped_x == pytest.approx(_centre_x(LARGE_FLOOR))
    assert catchment.cell_count == (SIZE - LAST_SMALL_COLUMN - 1) * (OUTLET_ROW + 5 + 1)
    assert _mask_columns(catchment.mask_path).min() > LAST_SMALL_COLUMN


def test_the_jenson_snap_stays_on_the_nearest_stream(engine, products) -> None:
    _directions, accumulation, streams, out = products

    catchment = _delineate(engine, accumulation, out, snap=JensonSnap(streams=streams))

    assert catchment.snapped_x == pytest.approx(_centre_x(SMALL_FLOOR))
    assert catchment.snapped_y == pytest.approx(_centre_y(OUTLET_ROW))
    assert catchment.snap_distance_m == pytest.approx(2 * RES)
    assert catchment.cell_count == (LAST_SMALL_COLUMN + 1) * (OUTLET_ROW + 1)
    assert _mask_columns(catchment.mask_path).max() <= LAST_SMALL_COLUMN


def test_the_jenson_snap_reads_no_accumulation(engine, products) -> None:
    """A transformed accumulation is not read, so the window snap's refusals do not apply."""
    directions, _accumulation, streams, out = products
    transformed = engine.flow_accumulation(
        directions, units="m2", transform="ln", out=out / "acc_ln_m2.tif"
    )

    catchment = _delineate(engine, transformed, out, snap=JensonSnap(streams=streams))

    assert catchment.snapped_x == pytest.approx(_centre_x(SMALL_FLOOR))


def test_an_outlet_with_no_stream_in_its_window_is_refused(engine, products) -> None:
    """Never delineate from a hillside cell: the catchment would be a few cells."""
    _directions, accumulation, streams, out = products
    far_from_both = Outlet(outlet_id="far", x=_centre_x(28), y=_centre_y(OUTLET_ROW))

    with pytest.raises(TerrainProductError, match="no cell of the stream network"):
        _delineate(
            engine,
            accumulation,
            out,
            snap=JensonSnap(streams=streams),
            outlet=far_from_both,
        )


def test_a_network_drawn_from_another_pointer_is_refused(engine, products) -> None:
    directions, accumulation, streams, out = products
    elsewhere = dataclasses.replace(directions, path=out / "another_pointer.tif")
    other = dataclasses.replace(streams, directions=elsewhere)

    with pytest.raises(TerrainProductError, match="another pointer"):
        _delineate(engine, accumulation, out, snap=JensonSnap(streams=other))


def test_an_unknown_snap_method_is_refused(engine, products) -> None:
    _directions, accumulation, _streams, out = products

    with pytest.raises(TerrainRequestError, match="Unknown snap method"):
        _delineate(engine, accumulation, out, snap="nearest")


def _outlet_config(**overrides) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=_centre_x(OUTLET_COL),
        y=_centre_y(OUTLET_ROW),
        dem="dem.tif",
        snap_dist=SNAP_DISTANCE_M,
        crs_project=CRS,
        terrain_engine="numpy_d8",
        **overrides,
    )


def test_the_window_snap_is_the_default() -> None:
    assert _outlet_config().snap_method == "window"


def test_a_jenson_snap_needs_the_threshold_of_the_river_network() -> None:
    with pytest.raises(ValidationError, match="threshold_area_km2"):
        _outlet_config(snap_method="jenson")


def test_a_jenson_snap_does_not_need_the_river_network_to_be_enabled() -> None:
    config = _outlet_config(snap_method="jenson", river_network={"threshold_area_km2": 0.5})

    assert config.snap_method == "jenson"
    assert config.river_network.enabled is False


def test_an_unknown_snap_method_is_refused_by_the_config() -> None:
    with pytest.raises(ValidationError, match="snap_method"):
        _outlet_config(snap_method="nearest")


def test_the_snap_method_is_part_of_the_cache_fingerprint_only_when_it_is_not_the_window() -> None:
    window = _outlet_config()
    jenson = _outlet_config(snap_method="jenson", river_network={"threshold_area_km2": 0.5})

    assert _geographic_cache_fingerprint(window) == _geographic_cache_fingerprint(
        _outlet_config(snap_method="window")
    )
    assert _geographic_cache_fingerprint(window) != _geographic_cache_fingerprint(jenson)


@pytest.fixture
def routed(tmp_path):
    """The regional flow stack of the pipeline, on the numpy engine."""
    dem = _write_dem(tmp_path / "dem.tif")
    paths = build_geographic_paths(tmp_path / "geographic_run")
    flow = build_regional_flow_products(
        dem_init_path=dem,
        dem_out_dir_path=paths.correcflow_path,
        dem_correc_type="fill",
        crs_project=CRS,
        engine_id="numpy_d8",
    )
    return dem, paths, flow


def _catchment_of(config, paths, flow):
    return build_standard_catchment(
        config=config,
        paths=paths,
        accumulation=flow.accumulation,
        crs_project=CRS,
        backend=object(),
    )


def test_the_pipeline_snaps_onto_the_network_its_river_section_draws(routed) -> None:
    """The threshold is read in km2 and turned into cells on the grid of the routing."""
    _dem, paths, flow = routed
    area_km2 = THRESHOLD_CELLS * RES * RES / 1.0e6
    window = _outlet_config()
    jenson = _outlet_config(snap_method="jenson", river_network={"threshold_area_km2": area_km2})

    on_window = _catchment_of(window, paths, flow)
    on_jenson = _catchment_of(jenson, paths, flow)

    assert on_window.x_outlet_snapped == pytest.approx(_centre_x(LARGE_FLOOR))
    assert on_jenson.x_outlet_snapped == pytest.approx(_centre_x(SMALL_FLOOR))
    assert on_jenson.snap_distance_m == pytest.approx(2 * RES)


def test_a_jenson_snap_with_no_threshold_is_refused_before_any_work(routed, tmp_path) -> None:
    _dem, paths, flow = routed

    with pytest.raises(ValueError, match="stream_threshold_cells"):
        extract_catchment_from_point(
            x_outlet=_centre_x(OUTLET_COL),
            y_outlet=_centre_y(OUTLET_ROW),
            snap_dist=int(SNAP_DISTANCE_M),
            accumulation=flow.accumulation,
            output_dir=tmp_path / "geo",
            engine_id="numpy_d8",
            snap_method="jenson",
        )
