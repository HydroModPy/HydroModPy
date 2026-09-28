"""``[geographic.snap_streams]`` reaches the stream burn of the routing DEM.

The burn runs before any mesh exists, so the mapped network is snapped on the
raster grid of the conditioned raw DEM. ``apply`` burns the snapped cells,
``diagnose`` burns the raw lines and publishes the snap, ``off`` changes
nothing. The conditioning pass of the terrain engine is replaced by a copy of
the DEM: the V valley below is already conditioned, and the test must not
depend on a routing binary.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.spatial.geographic.core import raster_stream_snap
from hydromodpy.spatial.geographic.core.raster_stream_snap import (
    RASTER_SNAP_LINES,
    RASTER_SNAP_MANIFEST,
    raster_snap_settings,
    snapped_lines_for_mapped_file,
)
from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
    report_network_dem_agreement,
)
from hydromodpy.spatial.geographic.core.stream_enforcement import (
    burn_streams_into_routing_dem,
    burned_dem_from_config,
)
from hydromodpy.spatial.geographic.geographic_config import (
    GeographicConfig,
    StreamEnforcementConfig,
)

N_ROWS = 41
N_COLS = 31
AXIS = 15
CELL = 25.0
TOP = N_ROWS * CELL
DEPTH = 30.0
FIRST_ROW = 5
DEM = (
    1000.0 - np.arange(N_ROWS)[:, None] + 2.0 * np.abs(np.arange(N_COLS)[None, :] - AXIS)
).astype("float32")


def _column_line(column: int) -> LineString:
    x = (column + 0.5) * CELL
    return LineString([(x, TOP - (FIRST_ROW + 0.5) * CELL), (x, 0.5 * CELL)])


@pytest.fixture
def case(tmp_path: Path, monkeypatch):
    dem_path = tmp_path / "dem.tif"
    profile = {
        "driver": "GTiff",
        "height": N_ROWS,
        "width": N_COLS,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, TOP, CELL, CELL),
        "nodata": -9999.0,
    }
    with rasterio.open(dem_path, "w", **profile) as dst:
        dst.write(DEM, 1)
    network = tmp_path / "streams.gpkg"
    gpd.GeoDataFrame({"id": [1]}, geometry=[_column_line(AXIS + 1)], crs="EPSG:2154").to_file(
        network, driver="GPKG"
    )
    paths = SimpleNamespace(
        correcflow_path=str(tmp_path / "demcorrecflow"),
        geographic_path=str(tmp_path / "geographic"),
        watershed_shp=str(tmp_path / "geographic" / "watershed.shp"),
    )
    Path(paths.correcflow_path).mkdir()
    Path(paths.geographic_path).mkdir()
    setup = SimpleNamespace(dem_init_path=str(dem_path), crs_project="EPSG:2154", paths=paths)

    conditioned: list[dict] = []

    def _copy_as_conditioned(**kwargs):
        conditioned.append(kwargs)
        out = Path(kwargs["dem_out_dir_path"])
        out.mkdir(parents=True, exist_ok=True)
        target = out / "dem_fill.tif"
        shutil.copyfile(kwargs["dem_init_path"], target)
        return SimpleNamespace(correc=str(target))

    monkeypatch.setattr(raster_stream_snap, "build_regional_flow_products", _copy_as_conditioned)
    return SimpleNamespace(
        tmp_path=tmp_path, dem=dem_path, network=network, setup=setup, conditioned=conditioned
    )


def _config(case, *, mode: str, burn: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        enforce_streams=StreamEnforcementConfig(
            enabled=burn, stream_geometry_path=case.network, depth_m=DEPTH
        ),
        snap_streams=SnapStreamsConfig(mode=mode),
        dem_correc_type="fill",
        terrain_engine=None,
    )


def _lowered(path: str) -> np.ndarray:
    with rasterio.open(path) as src:
        return np.isclose(DEM - src.read(1), DEPTH)


def _manifest(case) -> dict:
    path = Path(case.setup.paths.geographic_path) / RASTER_SNAP_MANIFEST
    return json.loads(path.read_text(encoding="utf-8"))


def test_apply_burns_the_snapped_cells(case) -> None:
    burned = burned_dem_from_config(_config(case, mode="apply"), case.setup)
    lowered = _lowered(burned)

    assert lowered[FIRST_ROW:, AXIS].all()
    assert not lowered[:, AXIS + 1].any()
    assert case.conditioned[0]["dem_correc_type"] == "fill"
    manifest = _manifest(case)
    assert manifest["mode"] == "apply"
    assert manifest["source_path"] == str(case.network.resolve())
    assert manifest["indices"]["snap_displacement_p90_m"] == pytest.approx(CELL)
    assert manifest["indices"]["snap_rejected_share"] == 0.0
    assert Path(manifest["lines_path"]).is_file()


def test_diagnose_burns_the_raw_lines_and_publishes_the_snap(case) -> None:
    burned = burned_dem_from_config(_config(case, mode="diagnose"), case.setup)
    lowered = _lowered(burned)

    assert lowered[FIRST_ROW:, AXIS + 1].all()
    assert not lowered[:, AXIS].any()
    assert _manifest(case)["mode"] == "diagnose"


def test_off_burns_exactly_what_it_burned_before(case) -> None:
    burned = burned_dem_from_config(_config(case, mode="off"), case.setup)
    reference = str(case.tmp_path / "reference.tif")
    settings = StreamEnforcementConfig()
    burn_streams_into_routing_dem(
        dem_in_path=case.dem,
        dem_out_path=reference,
        stream_lines=[_column_line(AXIS + 1)],
        mode="constant",
        depth_m=DEPTH,
        adaptive_percentile=settings.adaptive_percentile,
        relief_report_percentile=settings.relief_report_percentile,
        all_touched=settings.rasterize_all_touched,
        nodata_fallback=settings.dem_nodata_fallback,
    )

    with rasterio.open(burned) as got, rasterio.open(reference) as want:
        assert np.array_equal(got.read(1), want.read(1))
    assert case.conditioned == []
    assert not (Path(case.setup.paths.geographic_path) / RASTER_SNAP_MANIFEST).exists()


def test_the_snap_is_published_without_a_burn(case) -> None:
    routing = burned_dem_from_config(_config(case, mode="apply", burn=False), case.setup)

    assert routing == str(case.dem)
    assert _manifest(case)["mode"] == "apply"


def test_without_a_mapped_network_there_is_no_raster_pass(case) -> None:
    config = SimpleNamespace(
        enforce_streams=StreamEnforcementConfig(),
        snap_streams=SnapStreamsConfig(mode="apply"),
    )

    assert raster_snap_settings(config) is None
    assert burned_dem_from_config(config, case.setup) == str(case.dem)
    assert case.conditioned == []


def test_the_snapped_lines_follow_the_axis(case) -> None:
    burned_dem_from_config(_config(case, mode="apply"), case.setup)
    lines = gpd.read_file(Path(case.setup.paths.geographic_path) / RASTER_SNAP_LINES)
    xs = np.concatenate([np.asarray(line.coords)[:, 0] for line in lines.geometry])

    assert np.allclose(xs, (AXIS + 0.5) * CELL)


def test_a_consumer_reads_the_snapped_lines_only_in_apply(case) -> None:
    geographic = case.setup.paths.geographic_path
    burned_dem_from_config(_config(case, mode="apply"), case.setup)
    assert snapped_lines_for_mapped_file(case.network, geographic) is not None
    assert snapped_lines_for_mapped_file(case.tmp_path / "other.gpkg", geographic) is None

    burned_dem_from_config(_config(case, mode="diagnose"), case.setup)
    assert snapped_lines_for_mapped_file(case.network, geographic) is None


def _write_south_pointer_and_catchment(case) -> str:
    pointer = str(case.tmp_path / "direc.tif")
    profile = {
        "driver": "GTiff",
        "height": N_ROWS,
        "width": N_COLS,
        "count": 1,
        "dtype": "int16",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, TOP, CELL, CELL),
        "nodata": -32768,
    }
    with rasterio.open(pointer, "w", **profile) as dst:
        dst.write(np.full((N_ROWS, N_COLS), 8, dtype="int16"), 1)
    gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(0.0, 0.0, N_COLS * CELL, TOP)], crs="EPSG:2154"
    ).to_file(case.setup.paths.watershed_shp)
    return pointer


@pytest.mark.parametrize(("mode", "snapped"), [("apply", True), ("diagnose", False)])
def test_the_agreement_measures_the_map_that_was_burned(case, mode, snapped) -> None:
    config = _config(case, mode=mode)
    burned_dem_from_config(config, case.setup)
    pointer = _write_south_pointer_and_catchment(case)

    agreement = report_network_dem_agreement(config, case.setup, d8_pointer_path=pointer)

    assert agreement is not None
    assert agreement.snapped is snapped


def _fingerprint(dem: Path, network: Path | None, mode: str) -> str:
    from hydromodpy.spatial.geographic.pipeline import _geographic_cache_fingerprint

    enforce = {} if network is None else {"stream_geometry_path": str(network)}
    payload = {
        "source_mode": "standard",
        "catchment": {"catch_def": "dem", "dem_init_path": str(dem)},
        "enforce_streams": {"enabled": network is not None, **enforce},
        "snap_streams": {"mode": mode},
    }
    return _geographic_cache_fingerprint(GeographicConfig.model_validate(payload))


def test_the_snap_invalidates_the_geographic_cache_only_when_the_raster_pass_runs(case) -> None:
    with_network = {mode: _fingerprint(case.dem, case.network, mode) for mode in ("off", "apply")}
    without = {mode: _fingerprint(case.dem, None, mode) for mode in ("off", "apply")}

    assert with_network["apply"] != with_network["off"]
    assert without["apply"] == without["off"]
