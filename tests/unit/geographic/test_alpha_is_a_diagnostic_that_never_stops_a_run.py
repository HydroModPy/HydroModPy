"""The alpha diagnostic describes the current map and never stops the geographic step.

The terrain engine, the network extraction and the clips are replaced by recorders
on the bench valley, where every cell flows south and the mapped channel follows
column 10, so alpha is 1 when the map is the channel itself. What is under test is
what the step does with a map it cannot measure, and that the journal follows the
map on a rebuild and on a cache hit.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.state.paths import preprocessing_dir
from hydromodpy.spatial.geographic import pipeline as runtime_pipeline
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from hydromodpy.spatial.geographic.core.stream_dem_agreement import report_network_dem_agreement
from hydromodpy.spatial.geographic.domain_rasters import DomainRasterProducts
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers import ground_bench as bench
from tests._helpers.terrain_doubles import fake_flow_products

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}
_CHANNEL = LineString(
    [(bench.x_of(bench.AXIS), bench.N * bench.RES - 1.0), (bench.x_of(bench.AXIS), 1.0)]
)
_OFF_CATCHMENT = LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])
_WARNING = "stream/DEM agreement (alpha) was skipped"


def _journal(root: Path) -> Path:
    return preprocessing_dir(root / "results") / "geographic" / "stream_dem_agreement.json"


def _plant(path: Path, line: LineString, *, crs: str | None = bench.CRS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[line], crs=crs).to_file(path)
    return path


def _config(root: Path) -> GeographicConfig:
    root.mkdir(parents=True, exist_ok=True)
    dem = bench.write_raster(root / "dem.tif", bench.valley())
    return GeographicConfig.from_outlet(
        x=bench.x_of(bench.AXIS),
        y=bench.y_of(bench.N - 2),
        dem=dem,
        snap_dist="50 m",
        buff_area="10%",
        crs_project=bench.CRS,
        river_network=_RIVER,
    )


def _runtime(root: Path, monkeypatch, map_path, *, reuse: bool):
    def flow(**kwargs):
        out = Path(kwargs["dem_out_dir_path"])
        out.mkdir(parents=True, exist_ok=True)
        valley = bench.build()
        direc = bench.write_raster(out / "dem_direc.tif", valley.d8, dtype="int32")
        acc = bench.write_raster(out / "dem_acc.tif", valley.acc)
        return fake_flow_products(correc=out / "dem_fill.tif", direc=direc, acc=acc)

    def catchment(**kwargs):
        from shapely.geometry import box

        gpd.GeoDataFrame(geometry=[box(30.0, 30.0, 180.0, 180.0)], crs=bench.CRS).to_file(
            kwargs["paths"].watershed_shp
        )

    def network(**kwargs):
        correcflow = Path(kwargs["correcflow_dir"])
        valley = bench.build()
        streams = bench.write_raster(
            correcflow / "dem_streams_full.tif", valley.streams.astype("float32")
        )
        valley.network.to_file(kwargs["network_shp_path"])
        return RiverNetworkProducts(
            enabled=True,
            hydrographic_network_generated_shp=str(kwargs["network_shp_path"]),
            streams_tif=str(streams),
            network_crs=bench.CRS,
        )

    def domain_rasters(**kwargs):
        paths = kwargs["paths"]
        for target in (paths.watershed_box_buff_dem, paths.watershed_buff_dem, paths.watershed_dem):
            Path(target).write_bytes(Path(kwargs["dem_init_path"]).read_bytes())
        return DomainRasterProducts(
            watershed_box_buff_dem=paths.watershed_box_buff_dem,
            watershed_box_buff_fill="unused.tif",
            watershed_box_buff_direc="unused.tif",
            watershed_buff_dem=paths.watershed_buff_dem,
            watershed_buff_fill="unused.tif",
            watershed_buff_direc="unused.tif",
            watershed_dem=paths.watershed_dem,
            watershed_fill="unused.tif",
            watershed_direc="unused.tif",
            watershed_contour_tif="unused.tif",
        )

    tool = SimpleNamespace(delineation=SimpleNamespace(polygons_to_lines=lambda *a, **k: None))
    monkeypatch.setattr(runtime_pipeline, "resolve_delineation_backend", lambda backend: tool)
    monkeypatch.setattr(runtime_pipeline, "build_regional_flow_products", flow)
    monkeypatch.setattr(runtime_pipeline, "build_standard_catchment", catchment)
    monkeypatch.setattr(runtime_pipeline, "build_river_network_products", network)
    monkeypatch.setattr(runtime_pipeline, "build_domain_rasters", domain_rasters)
    monkeypatch.setattr(
        runtime_pipeline,
        "read_dem_metadata",
        lambda **kwargs: SimpleNamespace(runtime_attributes=lambda: {}),
    )
    return runtime_pipeline.build_geographic_runtime_context(
        config=_config(root),
        out_dir_path=root / "results",
        reuse_existing_outputs=reuse,
        network_map_path=map_path,
    )


def _setup(tmp_path: Path):
    watershed = tmp_path / "watershed.shp"
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)]).buffer(1000.0)], crs=bench.CRS).to_file(
        watershed
    )
    return SimpleNamespace(
        crs_project=bench.CRS,
        paths=SimpleNamespace(
            watershed_shp=str(watershed), geographic_path=str(tmp_path / "geographic")
        ),
    )


@pytest.mark.parametrize("case", ["outside", "no_crs", "missing"])
def test_a_map_that_cannot_be_measured_is_a_warning_through_the_function(
    case, tmp_path, caplog
) -> None:
    setup = _setup(tmp_path)
    d8 = bench.write_raster(tmp_path / "direc.tif", bench.build().d8, dtype="int32")
    maps = {
        "outside": lambda: _plant(tmp_path / "map.gpkg", _OFF_CATCHMENT),
        "no_crs": lambda: _plant(tmp_path / "map.shp", _CHANNEL, crs=None),
        "missing": lambda: tmp_path / "absent.gpkg",
    }
    journal = Path(setup.paths.geographic_path) / "stream_dem_agreement.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{}")

    with caplog.at_level(logging.WARNING):
        result = report_network_dem_agreement(
            setup, network_map_path=maps[case](), d8_pointer_path=d8
        )

    assert result is None
    assert _WARNING in caplog.text
    assert "map" in caplog.text
    assert not journal.exists()


@pytest.mark.parametrize("case", ["outside", "no_crs", "missing"])
def test_a_map_that_cannot_be_measured_does_not_stop_the_geographic_step(
    case, tmp_path, monkeypatch, caplog
) -> None:
    maps = {
        "outside": lambda: _plant(tmp_path / "map.gpkg", _OFF_CATCHMENT),
        "no_crs": lambda: _plant(tmp_path / "map.shp", _CHANNEL, crs=None),
        "missing": lambda: tmp_path / "absent.gpkg",
    }

    with caplog.at_level(logging.WARNING):
        context = _runtime(tmp_path, monkeypatch, maps[case](), reuse=False)

    assert context.catchment_area_km2 > 0.0
    assert _WARNING in caplog.text
    assert not _journal(tmp_path).exists()


def test_a_missing_custom_file_is_a_warning_in_the_resolver(tmp_path, caplog) -> None:
    from hydromodpy.data.variables.hydrography.resolver import resolve_network_map_path

    cfg = SimpleNamespace(
        data=SimpleNamespace(
            hydrography=SimpleNamespace(
                sources=[SimpleNamespace(source="custom", path="absent.gpkg")]
            )
        )
    )

    with caplog.at_level(logging.WARNING):
        resolved = resolve_network_map_path(cfg, config_path=tmp_path / "project.toml")

    assert resolved is None
    assert "path not found" in caplog.text


def test_the_journal_follows_the_map_on_a_rebuild_and_on_a_cache_hit(tmp_path, monkeypatch) -> None:
    channel = _plant(tmp_path / "channel.gpkg", _CHANNEL)
    _runtime(tmp_path, monkeypatch, channel, reuse=False)
    first = json.loads(_journal(tmp_path).read_text())
    assert first["alpha"] == pytest.approx(1.0)

    # Cache hit, another map: the journal describes this one.
    half = _plant(
        tmp_path / "half.gpkg",
        LineString([(bench.x_of(bench.AXIS), 100.0), (bench.x_of(bench.AXIS), 40.0)]),
    )
    _runtime(tmp_path, monkeypatch, half, reuse=True)
    second = json.loads(_journal(tmp_path).read_text())
    assert second["n_network_cells"] < first["n_network_cells"]

    # Cache hit, no map: the stale journal is removed.
    _runtime(tmp_path, monkeypatch, None, reuse=True)
    assert not _journal(tmp_path).exists()

    # Cache hit, a map where there was none: the journal appears.
    _runtime(tmp_path, monkeypatch, channel, reuse=True)
    assert json.loads(_journal(tmp_path).read_text()) == first
