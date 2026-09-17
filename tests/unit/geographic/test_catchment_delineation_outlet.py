"""Characterization tests for the outlet-mode ``CatchmentDelineation`` contract.

Goal:
- lock the current public contract of the catchment delineation facade,
- avoid runtime dependency on the concrete Whitebox backend by mocking it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.features import geometry_mask, rasterize, shapes
from rasterio.transform import from_origin
from shapely.geometry import shape as shapely_shape

from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.whitebox_double import FakeWhiteboxBackend

GOLDEN_FILE_OUTLET = (
    Path(__file__).resolve().parent / "golden" / "catchment_delineation_outlet_contract_golden.json"
)


class _FakeLocation:
    address = "Rennes, 35000, France"


class _FakeNominatim:
    def __init__(self, *args, **kwargs):
        pass

    def reverse(self, *_args, **_kwargs):
        return _FakeLocation()


def _write_synthetic_dem(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_origin(0.0, 1000.0, 100.0, 100.0)
    data = np.arange(100, dtype=np.float32).reshape(10, 10)
    profile = {
        "driver": "GTiff",
        "height": 10,
        "width": 10,
        "count": 1,
        "dtype": np.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst_ds:
        dst_ds.write(data, 1)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _build_outlet_catchment_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> CatchmentDelineation:
    import hydromodpy.spatial.geographic.catchment_delineation as geo_mod

    fake_wbt = FakeWhiteboxBackend()
    monkeypatch.setattr(geo_mod, "resolve_delineation_backend", lambda backend=None: fake_wbt)
    monkeypatch.setattr(geo_mod, "Nominatim", _FakeNominatim)

    dem_path = tmp_path / "inputs" / "dem.tif"
    _write_synthetic_dem(dem_path)

    cfg = GeographicConfig(
        catchment={
            "catch_def": "from_outlet_coord",
            "dem_init_path": dem_path,
            "x_outlet": 450.0,
            "y_outlet": 450.0,
            "snap_dist": 100,
            "buff_area": 20.0,
        },
        crs_project="EPSG:2154",
        dem_correc_type="breach",
    )
    initializing = SimpleNamespace(project_root=str(tmp_path / "case_run_outlet"))
    return CatchmentDelineation(config=cfg, initializing=initializing)


def _catchment_delineation_signature(geo: CatchmentDelineation) -> dict:
    finite_box = np.isfinite(geo.dem_box_buff_data) & (geo.dem_box_buff_data != geo.nodata)
    finite_core = np.isfinite(geo.dem_data) & (geo.dem_data != geo.nodata)

    return {
        "catch_area_km2": float(geo.catch_area),
        "crs_proj": str(geo.crs_proj),
        "dep_code": int(getattr(geo, "dep_code", -1)),
        "shape_box_buff": [int(v) for v in geo.dem_box_buff_data.shape],
        "shape_buff": [int(v) for v in geo.dem_buff_data.shape],
        "shape_core": [int(v) for v in geo.dem_data.shape],
        "dx": float(geo.dx),
        "dy": float(geo.dy),
        "xmin": float(geo.xmin),
        "xmax": float(geo.xmax),
        "ymin": float(geo.ymin),
        "ymax": float(geo.ymax),
        "mean_box_buff": float(np.nanmean(np.where(finite_box, geo.dem_box_buff_data, np.nan))),
        "mean_core": float(np.nanmean(np.where(finite_core, geo.dem_data, np.nan))),
        "top_left_box_buff": float(geo.dem_box_buff_data[0, 0]),
        "center_core": float(geo.dem_data[5, 5]),
    }


def test_catchment_delineation_from_outlet_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Check outlet mode contract on deterministic synthetic inputs."""
    geo = _build_outlet_catchment_case(tmp_path, monkeypatch)

    outlet_path = Path(geo.geographic_path) / "outlet.shp"
    outlet_snap_path = Path(geo.geographic_path) / "outlet_snap.shp"
    watershed_tif_path = Path(geo.watershed)

    assert outlet_path.exists()
    assert outlet_snap_path.exists()
    assert watershed_tif_path.exists()
    assert Path(geo.watershed_shp).exists()
    assert float(geo.catch_area) > 0.0
    assert geo.catch_def == "from_outlet_coord"


def test_catchment_delineation_from_outlet_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Freeze deterministic outlet-mode signature as non-regression baseline."""
    geo = _build_outlet_catchment_case(tmp_path, monkeypatch)
    actual = _catchment_delineation_signature(geo)

    if update_goldens:
        _write_json(GOLDEN_FILE_OUTLET, actual)
        return

    if not GOLDEN_FILE_OUTLET.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE_OUTLET}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE_OUTLET)
    assert actual["shape_box_buff"] == expected["shape_box_buff"]
    assert actual["shape_buff"] == expected["shape_buff"]
    assert actual["shape_core"] == expected["shape_core"]
    assert actual["crs_proj"] == expected["crs_proj"]
    assert actual["dep_code"] == expected["dep_code"]

    for key in (
        "catch_area_km2",
        "dx",
        "dy",
        "xmin",
        "xmax",
        "ymin",
        "ymax",
        "mean_box_buff",
        "mean_core",
        "top_left_box_buff",
        "center_core",
    ):
        assert actual[key] == pytest.approx(expected[key], rel=0.0, abs=1e-9)
