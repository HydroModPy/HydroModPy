"""Both geographic entry points route on the ground and clip the model top from it.

The terrain engine and the network extraction are replaced by recorders that hand
back the rasters of the bench valley: what is under test is which DEM each step is
given, and what the corrections wrote, not Whitebox.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from hydromodpy.spatial.geographic import pipeline as runtime_pipeline
from hydromodpy.spatial.geographic.core import domain_geographic_pipeline as domain_pipeline
from hydromodpy.spatial.geographic.core.ground_corrections import (
    CROSSINGS_REPORT_FILENAME,
    GROUND_DAM_FILENAME,
    GROUND_FILENAME,
)
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from hydromodpy.spatial.geographic.domain_rasters import DomainRasterProducts
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers import ground_bench as bench
from tests._helpers.terrain_doubles import fake_flow_products

ROAD_ROW = 10
HEIGHT = 2.5
_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}
_FIRST_AREA_KM2 = 0.0225
_SECOND_AREA_KM2 = 0.0196


class _Terrain:
    """Recorders standing for the flow products, the catchment and the network."""

    def __init__(self) -> None:
        self.routing: list[str] = []
        self.top: list[str] = []
        self.catchments = 0

    def flow(self, **kwargs):
        self.routing.append(str(kwargs["dem_init_path"]))
        out = Path(kwargs["dem_out_dir_path"])
        out.mkdir(parents=True, exist_ok=True)
        valley = bench.build()
        direc = bench.write_raster(out / "dem_direc.tif", valley.d8, dtype="int32")
        acc = bench.write_raster(out / "dem_acc.tif", valley.acc)
        return fake_flow_products(correc=out / "dem_fill.tif", direc=direc, acc=acc)

    def catchment(self, **kwargs):
        self.catchments += 1
        side = 180.0 if self.catchments == 1 else 170.0
        frame = gpd.GeoDataFrame(geometry=[box(30.0, 30.0, side, side)], crs=bench.CRS)
        frame.to_file(kwargs["paths"].watershed_shp)

    def network(self, **kwargs):
        correcflow = Path(kwargs["correcflow_dir"])
        valley = bench.build()
        bench.write_raster(correcflow / "dem_streams_full.tif", valley.streams.astype("float32"))
        valley.network.to_file(kwargs["network_shp_path"])
        return RiverNetworkProducts(
            enabled=True,
            hydrographic_network_generated_shp=str(kwargs["network_shp_path"]),
            streams_tif=str(correcflow / "dem_streams_full.tif"),
            network_crs=bench.CRS,
        )

    def clip(self, **kwargs):
        self.top.append(str(kwargs["dem_init_path"]))
        _real_clip(**kwargs)

    def domain_rasters(self, **kwargs):
        self.top.append(str(kwargs["dem_init_path"]))
        return DomainRasterProducts(*(["unused.tif"] * 10))


_real_clip = domain_pipeline.clip_dem_to_box_buffer


def _config(tmp_path: Path, *, raw: np.ndarray, **sections) -> GeographicConfig:
    dem = bench.write_raster(tmp_path / "dem.tif", raw)
    return GeographicConfig.from_outlet(
        x=bench.x_of(bench.AXIS),
        y=bench.y_of(bench.N - 2),
        dem=dem,
        snap_dist="50 m",
        buff_area="10%",
        crs_project=bench.CRS,
        river_network=_RIVER,
        **sections,
    )


def _dam_sections(tmp_path: Path) -> dict:
    line = bench.road_along(ROAD_ROW)
    path = tmp_path / "dam.gpkg"
    gpd.GeoDataFrame(geometry=[line], crs=bench.CRS).to_file(path, driver="GPKG")
    return {"dam_carve": {"enabled": True, "line_path": path, "buffer_m": 6.0}}


def _crossing_sections(tmp_path: Path) -> dict:
    path = tmp_path / "crossings.gpkg"
    bench.structures(("road", bench.road_along(ROAD_ROW))).to_file(path, driver="GPKG")
    return {"crossings": {"enabled": True, "path": path}}


def _read(path: str) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


def _domain(tmp_path: Path, monkeypatch, config: GeographicConfig):
    terrain = _Terrain()
    monkeypatch.setattr(domain_pipeline, "build_regional_flow_products", terrain.flow)
    monkeypatch.setattr(domain_pipeline, "build_standard_catchment", terrain.catchment)
    monkeypatch.setattr(domain_pipeline, "build_river_network_products", terrain.network)
    monkeypatch.setattr(domain_pipeline, "clip_dem_to_box_buffer", terrain.clip)
    workspace = SimpleNamespace(project_root=tmp_path / "results")
    features = domain_pipeline.build_geographic_derived_features(config=config, workspace=workspace)
    return terrain, features


def _runtime(tmp_path: Path, monkeypatch, config: GeographicConfig):
    terrain = _Terrain()
    tool = SimpleNamespace(delineation=SimpleNamespace(polygons_to_lines=lambda *a, **k: None))
    monkeypatch.setattr(runtime_pipeline, "resolve_delineation_backend", lambda backend: tool)
    monkeypatch.setattr(runtime_pipeline, "build_regional_flow_products", terrain.flow)
    monkeypatch.setattr(runtime_pipeline, "build_standard_catchment", terrain.catchment)
    monkeypatch.setattr(runtime_pipeline, "build_river_network_products", terrain.network)
    monkeypatch.setattr(runtime_pipeline, "build_domain_rasters", terrain.domain_rasters)
    monkeypatch.setattr(
        runtime_pipeline,
        "read_dem_metadata",
        lambda **kwargs: SimpleNamespace(runtime_attributes=lambda: {}),
    )
    context = runtime_pipeline.build_geographic_runtime_context(
        config=config, out_dir_path=tmp_path / "results"
    )
    return terrain, context


def _correcflow(tmp_path: Path) -> Path:
    from hydromodpy.core.state.paths import preprocessing_dir

    return preprocessing_dir(tmp_path / "results") / "demcorrecflow"


ENTRY_POINTS = pytest.mark.parametrize("run", [_domain, _runtime], ids=["domain", "runtime"])


@ENTRY_POINTS
def test_without_a_correction_the_raw_dem_is_routed_and_clipped_untouched(
    run, tmp_path, monkeypatch
) -> None:
    config = _config(tmp_path, raw=bench.valley())

    terrain, _ = run(tmp_path, monkeypatch, config)

    raw = str(config.dem_init_path)
    assert terrain.routing == [raw]
    assert terrain.top == [raw]
    assert not list(_correcflow(tmp_path).glob("dem_ground*"))


@ENTRY_POINTS
def test_a_carved_dam_reaches_the_routing_and_the_top(run, tmp_path, monkeypatch) -> None:
    raw = bench.build(embankment_rows=(ROAD_ROW,), height=8.0).dem
    config = _config(tmp_path, raw=raw, **_dam_sections(tmp_path))

    terrain, _ = run(tmp_path, monkeypatch, config)

    ground = str(_correcflow(tmp_path) / GROUND_DAM_FILENAME)
    assert terrain.routing == [ground]
    assert terrain.top == [ground]
    carved = _read(ground)
    assert (carved[ROAD_ROW, :] < raw[ROAD_ROW, :]).all()
    assert carved[0, 0] == raw[0, 0]


@ENTRY_POINTS
def test_a_declared_crossing_is_notched_and_delineated_again(run, tmp_path, monkeypatch) -> None:
    raw = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT).dem
    config = _config(tmp_path, raw=raw, **_crossing_sections(tmp_path))

    terrain, _ = run(tmp_path, monkeypatch, config)

    ground = str(_correcflow(tmp_path) / GROUND_FILENAME)
    assert terrain.routing == [str(config.dem_init_path), ground]
    assert terrain.top == [ground]
    notched = _read(ground)
    assert notched[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))
    assert np.argwhere(notched != raw).tolist() == [[ROAD_ROW, bench.AXIS]]


@ENTRY_POINTS
def test_the_notch_writes_its_report_next_to_the_corrected_dem(
    run, tmp_path, monkeypatch, caplog
) -> None:
    raw = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT).dem
    config = _config(tmp_path, raw=raw, **_crossing_sections(tmp_path))

    with caplog.at_level("INFO"):
        run(tmp_path, monkeypatch, config)

    report = json.loads((_correcflow(tmp_path) / CROSSINGS_REPORT_FILENAME).read_text())
    assert report["crossing_points"] == {"road": 1}
    assert report["notched"] == {"road": 1}
    assert report["pixels_lowered"] == 1
    assert report["max_lowering_m"] == pytest.approx(HEIGHT)
    assert report["catchment_area_km2_before"] == pytest.approx(_FIRST_AREA_KM2)
    assert report["catchment_area_km2_after"] == pytest.approx(_SECOND_AREA_KM2)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Crossing notch")]
    assert len(lines) == 1
    assert "1 notched" in lines[0]


@ENTRY_POINTS
def test_a_notch_that_lowers_nothing_does_not_delineate_again(run, tmp_path, monkeypatch) -> None:
    config = _config(tmp_path, raw=bench.valley(), **_crossing_sections(tmp_path))

    terrain, _ = run(tmp_path, monkeypatch, config)

    ground = str(_correcflow(tmp_path) / GROUND_FILENAME)
    assert terrain.routing == [str(config.dem_init_path)]
    assert terrain.top == [ground]
    assert (_read(ground) == bench.valley()).all()
    report = json.loads((_correcflow(tmp_path) / CROSSINGS_REPORT_FILENAME).read_text())
    assert report["pixels_lowered"] == 0
    assert report["catchment_area_km2_after"] == pytest.approx(_FIRST_AREA_KM2)


def test_the_runtime_context_hands_the_ground_as_the_top(tmp_path, monkeypatch) -> None:
    raw = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT).dem
    config = _config(tmp_path, raw=raw, **_crossing_sections(tmp_path))

    _, context = _runtime(tmp_path, monkeypatch, config)

    assert context.top_dem_path == str(_correcflow(tmp_path) / GROUND_FILENAME)


def test_the_dam_is_carved_before_the_notch_reads_it(tmp_path, monkeypatch) -> None:
    raw = bench.build(embankment_rows=(ROAD_ROW,), height=8.0).dem
    config = _config(tmp_path, raw=raw, **_dam_sections(tmp_path), **_crossing_sections(tmp_path))

    terrain, _ = _domain(tmp_path, monkeypatch, config)

    ground = str(_correcflow(tmp_path) / GROUND_FILENAME)
    assert terrain.routing[0] == str(_correcflow(tmp_path) / GROUND_DAM_FILENAME)
    assert terrain.top == [ground]


@ENTRY_POINTS
def test_a_notch_that_lowers_nothing_logs_its_line_once(run, tmp_path, monkeypatch, caplog) -> None:
    config = _config(tmp_path, raw=bench.valley(), **_crossing_sections(tmp_path))

    with caplog.at_level("INFO"):
        run(tmp_path, monkeypatch, config)

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Crossing notch")]
    assert len(lines) == 1


@pytest.mark.parametrize(
    ("run", "module"),
    [(_domain, domain_pipeline), (_runtime, runtime_pipeline)],
    ids=["domain", "runtime"],
)
def test_the_burn_guard_reads_the_first_delineation_before_the_notch(
    run, module, tmp_path, monkeypatch
) -> None:
    seen: list[float] = []
    monkeypatch.setattr(
        module,
        "check_catchment_area_drift",
        lambda **kwargs: seen.append(kwargs["burned_area_km2"]),
    )
    raw = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT).dem
    config = _config(tmp_path, raw=raw, **_crossing_sections(tmp_path))

    run(tmp_path, monkeypatch, config)

    assert seen == [pytest.approx(_FIRST_AREA_KM2)]
