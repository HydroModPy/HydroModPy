"""Regional materialization counts actual terrain work and verifies reuse."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import JobUsageError, TerrainProductError
from hydromodpy.schema.job import provenance
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.seal import verify_job
from hydromodpy.spatial.geographic.core.pipeline_steps import build_standard_catchment
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.regional_flow_copy import copy_regional_flow_from_job
from hydromodpy.spatial.geographic.regional_flow_job import (
    RegionalFlowRequest,
    load_regional_flow_job,
    materialize_regional_flow_job,
    regional_flow_identity,
)
from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine


@pytest.fixture
def flow_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(provenance, "git_state", lambda: {"commit": None, "dirty": None})
    dem = tmp_path / "dem.tif"
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="float64",
        crs="EPSG:2154",
        transform=from_origin(300000, 6700000, 25, 25),
        nodata=-9999.0,
    ) as raster:
        raster.write(np.arange(64, dtype=float).reshape(8, 8), 1)
    return {
        "dem_init_path": dem,
        "dem_correc_type": "fill",
        "crs_project": "EPSG:2154",
        "engine_id": "numpy_d8",
    }


def test_ten_distinct_catchments_compute_each_routing_product_once(
    tmp_path: Path, flow_request: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: Counter[str] = Counter()

    def counted(name, original):
        def run(self, *args, **kwargs):
            calls[name] += 1
            return original(self, *args, **kwargs)

        return run

    for name in ("condition_dem", "drainage_directions", "flow_accumulation", "delineate"):
        monkeypatch.setattr(
            NumpyTerrainEngine, name, counted(name, getattr(NumpyTerrainEngine, name))
        )
    results = [
        materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)
        for _ in range(10)
    ]
    watersheds = []
    for site in range(10):
        row, col = 1 + site // 5, 1 + site % 5
        x_outlet = 300000 + (col + 0.5) * 25
        y_outlet = 6700000 - (row + 0.5) * 25
        config = GeographicConfig.model_validate(
            {
                "catchment": {
                    "catch_def": "from_outlet_coord",
                    "dem_init_path": flow_request["dem_init_path"],
                    "x_outlet": x_outlet,
                    "y_outlet": y_outlet,
                    "snap_dist": 1,
                    "buff_area": 10,
                },
                "dem_correc_type": "fill",
                "terrain_engine": "numpy_d8",
                "reg_fold": results[0].job_dir,
            }
        )
        paths = build_geographic_paths(tmp_path / f"site_{site}")
        flow = copy_regional_flow_from_job(
            config=config,
            routing_dem_path=config.dem_init_path,
            output_dir=paths.correcflow_path,
            crs_project="EPSG:2154",
        )
        catchment = build_standard_catchment(
            config=config,
            paths=paths,
            accumulation=flow.accumulation,
            crs_project="EPSG:2154",
            backend=object(),
        )
        assert catchment.x_outlet_snapped == x_outlet
        assert catchment.y_outlet_snapped == y_outlet
        assert Path(catchment.watershed_shp).is_file()
        watershed = gpd.read_file(catchment.watershed_shp)
        assert not watershed.empty
        assert float(watershed.area.sum()) > 0
        watersheds.append(watershed.geometry.union_all().wkb)

    assert len(set(watersheds)) == 10
    assert calls == {
        "condition_dem": 1,
        "drainage_directions": 1,
        "flow_accumulation": 1,
        "delineate": 10,
    }
    assert sum(not result.outcome.reused for result in results) == 1
    assert len({result.job_id for result in results}) == 1
    assert verify_job(JobDirectory.open(tmp_path / "regional")).ok
    reloaded = load_regional_flow_job(job_dir=tmp_path / "regional")
    assert reloaded.products.acc == results[0].products.acc
    assert reloaded.products.accumulation.transform == "ln"


def test_identity_uses_dem_content_and_effective_routing_parameters(
    tmp_path: Path, flow_request: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = regional_flow_identity(**flow_request)
    copied = tmp_path / "copy.tif"
    shutil.copyfile(flow_request["dem_init_path"], copied)
    assert regional_flow_identity(**{**flow_request, "dem_init_path": copied}) == original
    assert regional_flow_identity(**{**flow_request, "dem_correc_type": "breach"}) != original
    assert regional_flow_identity(**{**flow_request, "crs_project": "EPSG:32630"}) != original
    with rasterio.open(copied, "r+") as raster:
        data = raster.read(1)
        data[1, 1] += 1
        raster.write(data, 1)
    assert regional_flow_identity(**{**flow_request, "dem_init_path": copied}) != original
    monkeypatch.setattr(NumpyTerrainEngine, "engine_version", "new-build")
    assert regional_flow_identity(**flow_request) != original


@pytest.mark.parametrize("damage", ["remove", "change"])
def test_a_damaged_sealed_stack_is_refused(
    tmp_path: Path, flow_request: dict[str, object], damage: str
) -> None:
    result = materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)
    target = Path(result.products.acc)
    if damage == "remove":
        target.unlink()
    else:
        with rasterio.open(target, "r+") as raster:
            data = raster.read(1)
            data[1, 1] += 1
            raster.write(data, 1)
    with pytest.raises(TerrainProductError, match="cannot be reused"):
        materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)


def test_different_inputs_never_overwrite_a_sealed_job(
    tmp_path: Path, flow_request: dict[str, object]
) -> None:
    result = materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)
    seal = (result.job_dir / "manifest.json").read_bytes()
    with pytest.raises(JobUsageError, match="sealed under"):
        materialize_regional_flow_job(
            job_dir=result.job_dir, **{**flow_request, "dem_correc_type": "breach"}
        )
    assert (result.job_dir / "manifest.json").read_bytes() == seal


def test_reader_validates_the_routing_inputs_before_delivering_products(
    tmp_path: Path, flow_request: dict[str, object]
) -> None:
    result = materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)
    assert load_regional_flow_job(job_dir=result.job_dir, **flow_request).job_id == result.job_id
    with pytest.raises(JobUsageError, match="sealed under"):
        load_regional_flow_job(
            job_dir=result.job_dir, **{**flow_request, "dem_correc_type": "breach"}
        )


def test_sealed_stack_is_readable_without_source_or_mutable_request(
    tmp_path: Path, flow_request: dict[str, object]
) -> None:
    result = materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)
    Path(flow_request["dem_init_path"]).unlink()
    (result.job_dir / "request.json").unlink()
    loaded = load_regional_flow_job(job_dir=result.job_dir, expected_job_id=result.job_id)
    assert loaded.products == result.products


def test_interrupted_work_is_not_a_reusable_success(
    tmp_path: Path, flow_request: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("routing failed")

    monkeypatch.setattr(NumpyTerrainEngine, "condition_dem", fail)
    job_dir = tmp_path / "regional"
    with pytest.raises(RuntimeError, match="routing failed"):
        materialize_regional_flow_job(job_dir=job_dir, **flow_request)
    assert not (job_dir / "manifest.json").exists()
    assert json.loads((job_dir / "outcome.json").read_text())["status"] == "failed"
    with pytest.raises(TerrainProductError, match="cannot be reused"):
        load_regional_flow_job(job_dir=job_dir)


def test_regional_request_rejects_outlet_parameters(flow_request: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RegionalFlowRequest.model_validate({**flow_request, "x_outlet": 300000})
