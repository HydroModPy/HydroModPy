"""The sealed regional flow job: built once, reused by address, refused when damaged.

The capped breach joined the request without moving an old address. The two
pinned digests were computed at the commit before it existed, with a stub
engine whose name, version and digest are fixed, over ``dem-bytes-for-pinning``.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from hydromodpy.core.exceptions import JobUsageError, TerrainProductError
from hydromodpy.schema.job import provenance
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.seal import verify_job
from hydromodpy.spatial.geographic.core.flow_products import (
    CORRECTED_DEM_NAMES,
    conditioning_method,
    corrected_dem_name,
)
from hydromodpy.spatial.geographic.core.pipeline_steps import build_standard_catchment
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import build_geographic_paths
from hydromodpy.spatial.geographic.regional_flow_job import (
    RegionalFlowRequest,
    _resolved,
    copy_regional_flow_from_job,
    load_regional_flow_job,
    materialize_regional_flow_job,
    regional_flow_identity,
)
from hydromodpy.spatial.terrain import CappedBreach
from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine
from tests._helpers.geotiffs import write_geotiff

PINNED = {
    "fill": "sha256:ae0b66f1d8395b84fbad6e88bc6d1e34eb30e748590617874873bbde1a870d54",
    "breach": "sha256:ceb76da4c50af4dc16cec6e6e54653d730135226fe57d1bcfb85c0b2f239ab7d",
}


@pytest.fixture
def flow_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(provenance, "git_state", lambda: {"commit": None, "dirty": None})
    dem = write_geotiff(
        tmp_path / "dem.tif",
        np.arange(64, dtype=float).reshape(8, 8),
        origin=(300000, 6700000),
        cell=25,
        nodata=-9999.0,
    )
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


@pytest.mark.parametrize(
    ("change", "error", "match"),
    [
        ({"dem_correc_type": None}, ValueError, "dem_correc_type is required"),
        ({"expected_job_id": "sha256:other"}, JobUsageError, "disagree with expected_job_id"),
    ],
)
def test_a_reader_given_inputs_that_cannot_name_the_job_is_refused(
    tmp_path, flow_request, change, error, match
) -> None:
    result = materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)

    with pytest.raises(error, match=match):
        load_regional_flow_job(job_dir=result.job_dir, **{**flow_request, **change})


def test_an_unfinished_job_is_not_resumed_with_other_inputs(
    tmp_path, flow_request, monkeypatch
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("routing failed")

    monkeypatch.setattr(NumpyTerrainEngine, "condition_dem", fail)
    with pytest.raises(RuntimeError):
        materialize_regional_flow_job(job_dir=tmp_path / "regional", **flow_request)
    monkeypatch.undo()

    with pytest.raises(JobUsageError, match="names other inputs"):
        materialize_regional_flow_job(
            job_dir=tmp_path / "regional", **{**flow_request, "dem_correc_type": "breach"}
        )


@pytest.mark.parametrize(
    ("config", "match"),
    [
        (SimpleNamespace(reg_fold=None), "reg_fold is required"),
        (
            SimpleNamespace(reg_fold="job", river_network=SimpleNamespace(enabled=True)),
            "River network products cannot use a shared regional flow job",
        ),
    ],
)
def test_a_child_without_a_job_or_with_a_river_network_cannot_copy_one(config, match) -> None:
    with pytest.raises(ValueError, match=match):
        copy_regional_flow_from_job(
            config=config, routing_dem_path="dem.tif", output_dir="out", crs_project=None
        )


# --- the capped breach in the address ---------------------------------------------


class _StubEngine:
    engine_id = "stub"
    engine_version = "1.0"

    def engine_digest(self) -> str:
        return "d" * 64


@pytest.fixture
def pinned_dem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.regional_flow_job.terrain_registry.create",
        lambda engine_id, backend=None: _StubEngine(),
    )
    path = tmp_path / "dem.bin"
    path.write_bytes(b"dem-bytes-for-pinning")
    return path


def _identity(dem: Path, method: str, capped: CappedBreach | None = None) -> str:
    return regional_flow_identity(
        dem_init_path=dem,
        dem_correc_type=method,
        crs_project="EPSG:2154",
        engine_id="whitebox_workflows",
        capped_breach=capped,
    )


@pytest.mark.parametrize("method", ["fill", "breach"])
def test_a_fill_or_breach_request_keeps_the_address_and_the_inputs_it_had(
    pinned_dem, method
) -> None:
    request = RegionalFlowRequest(
        dem_init_path=pinned_dem, dem_correc_type=method, crs_project="EPSG:2154"
    )
    inputs, _job_id, _size = _resolved(request)

    assert _identity(pinned_dem, method) == PINNED[method]
    assert set(inputs) == {"dem_sha256", "dem_correc_type", "crs_project", "engine"}
    assert "capped_breach" not in request.document()


def test_the_limits_enter_the_address_of_the_capped_breach_and_only_it(pinned_dem) -> None:
    base = _identity(pinned_dem, "capped_breach", CappedBreach(0.5, 200.0))
    request = RegionalFlowRequest(
        dem_init_path=pinned_dem,
        dem_correc_type="capped_breach",
        capped_breach={"max_depth_m": 0.5, "max_distance_m": 200.0},
        crs_project="EPSG:2154",
    )
    inputs, _job_id, _size = _resolved(request)

    assert base not in PINNED.values()
    assert base == _identity(pinned_dem, "capped_breach", CappedBreach(0.5, 200.0))
    assert base != _identity(pinned_dem, "capped_breach", CappedBreach(0.6, 200.0))
    assert base != _identity(pinned_dem, "capped_breach", CappedBreach(0.5, 250.0))
    assert inputs["capped_breach"] == {"max_depth_m": 0.5, "max_distance_m": 200.0}
    assert request.breach_limits() == CappedBreach(0.5, 200.0)


def test_limits_without_the_method_or_the_method_without_limits_are_refused(pinned_dem) -> None:
    with pytest.raises(ValidationError):
        _identity(pinned_dem, "fill", CappedBreach(0.5, 200.0))
    with pytest.raises(ValidationError):
        _identity(pinned_dem, "capped_breach")
    with pytest.raises(ValueError, match="needs its limits"):
        conditioning_method("capped_breach")
    with pytest.raises(ValueError, match="has none"):
        conditioning_method("fill", CappedBreach(0.5, 200.0))


def test_the_method_maps_to_the_port_value_and_a_file_of_its_own() -> None:
    limits = CappedBreach(0.5, 200.0)

    assert conditioning_method("fill") == "fill"
    assert conditioning_method("breach") == "breach"
    assert conditioning_method("capped_breach", limits) is limits
    assert corrected_dem_name("capped_breach") == "dem_capped_breach.tif"
    assert len(set(CORRECTED_DEM_NAMES.values())) == len(CORRECTED_DEM_NAMES)
