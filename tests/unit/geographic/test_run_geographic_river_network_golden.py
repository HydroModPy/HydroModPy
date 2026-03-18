"""Golden non-regression test for river-network geographic artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio

from hydromodpy.geographic.cases import run_geographic_case_from_toml
from tests.support.whitebox import configure_whitebox_single_thread


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "run_geographic_river_network_golden.json"

ABS_TOL_FLOAT = 1e-3
ABS_TOL_LENGTH_M = 1.0
ABS_TOL_DRAINAGE_DENSITY = 1e-6


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_tmp_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "run_geographic_river_network_config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    dem_path = (REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_canut.tif").as_posix()
    out_path = (tmp_path / "results").as_posix()

    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                f'project_root = "{out_path}"',
                "",
                "[geographic]",
                'catch_def = "from_outlet_coord"',
                f'dem_init_path = "{dem_path}"',
                "x_outlet = 265611.933",
                "y_outlet = 6784182.776",
                "snap_dist = 50",
                "buff_area = 20.0",
                'crs_project = "EPSG:2154"',
                'dem_correc_type = "breach"',
                "",
                "[geographic.river_network]",
                "enabled = true",
                'threshold_mode = "area_km2"',
                "threshold_area_km2 = 0.5",
                "prune_short_streams = false",
                "min_stream_length_m = 0.0",
                "compute_strahler_order = true",
                "compute_stream_links = true",
                "all_vertices = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _raster_signature(path: str | Path) -> dict:
    with rasterio.open(str(path)) as src:
        arr = np.asarray(src.read(1))
        nodata = src.nodata
        mask = np.isfinite(arr)
        if nodata is not None:
            mask &= arr != nodata
        active = arr[(arr > 0) & mask]

        payload = {
            "shape": [int(src.height), int(src.width)],
            "dtype": str(arr.dtype),
            "nodata": None if nodata is None else float(nodata),
            "valid_pixel_count": int(np.count_nonzero(mask)),
            "nodata_pixel_count": int(arr.size - np.count_nonzero(mask)),
            "active_pixel_count": int(active.size),
            "sum_active": float(np.sum(active, dtype=np.float64)) if active.size else 0.0,
            "max_active": float(np.max(active)) if active.size else None,
        }
        return payload


def _vector_signature(path: str | Path) -> dict:
    gdf = gpd.read_file(str(path))
    total_length = 0.0 if gdf.empty else float(np.sum(np.asarray(gdf.length, dtype=float)))
    return {
        "feature_count": int(len(gdf)),
        "total_length_m": float(total_length),
    }


def _river_network_signature(tmp_path: Path) -> dict:
    config_path = _write_tmp_config(tmp_path)
    workspace, geographic = run_geographic_case_from_toml(config_path)
    _ = workspace

    summary_path = Path(geographic.river_network_summary_json)
    if not summary_path.exists():
        raise AssertionError(f"Missing river network summary JSON: {summary_path}")
    summary = _load_json(summary_path)

    payload = {
        "summary": {
            "enabled": bool(summary["enabled"]),
            "threshold_mode": str(summary["threshold_mode"]),
            "threshold_value": float(summary["threshold_value"]),
            "threshold_cells": float(summary["threshold_cells"]),
            "stream_pixel_count": int(summary["stream_pixel_count"]),
            "segment_count": int(summary["segment_count"]),
            "network_total_length_m": float(summary["network_total_length_m"]),
            "max_strahler_order": (
                None if summary["max_strahler_order"] is None else float(summary["max_strahler_order"])
            ),
            "catchment_area_km2": float(summary["catchment_area_km2"]),
            "drainage_density_km_per_km2": float(summary["drainage_density_km_per_km2"]),
        },
        "streams": _raster_signature(geographic.river_streams_tif),
        "stream_order_strahler": _raster_signature(geographic.river_stream_order_strahler_tif),
        "stream_link_id": _raster_signature(geographic.river_stream_link_id_tif),
        "network_vector": _vector_signature(geographic.river_network_shp),
    }
    return payload


@pytest.mark.slow
def test_run_geographic_river_network_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Validate river-network raster/vector signatures against a golden reference."""
    configure_whitebox_single_thread(monkeypatch)
    actual = _river_network_signature(tmp_path)

    if update_goldens:
        _write_json(GOLDEN_FILE, actual)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)

    assert actual["summary"]["enabled"] is expected["summary"]["enabled"]
    assert actual["summary"]["threshold_mode"] == expected["summary"]["threshold_mode"]
    assert actual["summary"]["stream_pixel_count"] == expected["summary"]["stream_pixel_count"]
    assert actual["summary"]["segment_count"] == expected["summary"]["segment_count"]
    assert actual["summary"]["max_strahler_order"] == expected["summary"]["max_strahler_order"]

    for key in (
        "threshold_value",
        "threshold_cells",
        "catchment_area_km2",
    ):
        assert float(actual["summary"][key]) == pytest.approx(
            float(expected["summary"][key]),
            abs=ABS_TOL_FLOAT,
            rel=0.0,
        )

    for key in ("network_total_length_m",):
        assert float(actual["summary"][key]) == pytest.approx(
            float(expected["summary"][key]),
            abs=ABS_TOL_LENGTH_M,
            rel=0.0,
        )

    assert float(actual["summary"]["drainage_density_km_per_km2"]) == pytest.approx(
        float(expected["summary"]["drainage_density_km_per_km2"]),
        abs=ABS_TOL_DRAINAGE_DENSITY,
        rel=0.0,
    )

    for raster_key in ("streams", "stream_order_strahler", "stream_link_id"):
        assert actual[raster_key]["shape"] == expected[raster_key]["shape"]
        assert actual[raster_key]["dtype"] == expected[raster_key]["dtype"]
        assert actual[raster_key]["nodata"] == expected[raster_key]["nodata"]
        assert actual[raster_key]["valid_pixel_count"] == expected[raster_key]["valid_pixel_count"]
        assert actual[raster_key]["nodata_pixel_count"] == expected[raster_key]["nodata_pixel_count"]
        assert actual[raster_key]["active_pixel_count"] == expected[raster_key]["active_pixel_count"]
        assert float(actual[raster_key]["sum_active"]) == pytest.approx(
            float(expected[raster_key]["sum_active"]),
            abs=ABS_TOL_FLOAT,
            rel=0.0,
        )
        assert actual[raster_key]["max_active"] == expected[raster_key]["max_active"]

    assert actual["network_vector"]["feature_count"] == expected["network_vector"]["feature_count"]
    assert float(actual["network_vector"]["total_length_m"]) == pytest.approx(
        float(expected["network_vector"]["total_length_m"]),
        abs=ABS_TOL_LENGTH_M,
        rel=0.0,
    )
