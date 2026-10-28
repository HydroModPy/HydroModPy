"""Golden non-regression test for river-network geographic artifacts."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio

from hydromodpy.spatial.geographic.cases import run_geographic_case_from_toml
from tests._helpers.geographic_cases import (
    CASE_RIVER_NETWORK,
    NAIZIN,
    outlet_case_toml,
    river_network_summary_signature,
    write_json,
)
from tests._helpers.whitebox import configure_whitebox_single_thread
from tests.regression.golden_utils import load_json_payload, resolve_tiered_golden_file

GOLDEN_FILE = resolve_tiered_golden_file(
    test_file=__file__,
    filename="run_geographic_river_network_golden.json",
)

ABS_TOL_FLOAT = 1e-3
ABS_TOL_LENGTH_M = 1.0
ABS_TOL_DRAINAGE_DENSITY = 1e-6


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
    config_path = outlet_case_toml(
        tmp_path / "run_geographic_river_network_config.toml",
        NAIZIN,
        root=tmp_path,
        river_network=CASE_RIVER_NETWORK,
    )
    _workspace, geographic = run_geographic_case_from_toml(config_path)

    summary_path = Path(geographic.hydrographic_network_generated_summary_json)
    if not summary_path.exists():
        raise AssertionError(f"Missing river network summary JSON: {summary_path}")
    summary = load_json_payload(summary_path)

    payload = {
        "summary": river_network_summary_signature(summary),
        "streams": _raster_signature(geographic.river_streams_tif),
        "stream_order_strahler": _raster_signature(geographic.river_stream_order_strahler_tif),
        "stream_link_id": _raster_signature(geographic.river_stream_link_id_tif),
        "network_vector": _vector_signature(geographic.hydrographic_network_generated_shp),
    }
    return payload


@pytest.mark.regression
@pytest.mark.fast
def test_run_geographic_river_network_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Validate river-network raster/vector signatures against a golden reference."""
    configure_whitebox_single_thread(monkeypatch)
    actual = _river_network_signature(tmp_path)

    if update_goldens:
        write_json(GOLDEN_FILE, actual)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = load_json_payload(GOLDEN_FILE)

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
        assert (
            actual[raster_key]["nodata_pixel_count"] == expected[raster_key]["nodata_pixel_count"]
        )
        assert (
            actual[raster_key]["active_pixel_count"] == expected[raster_key]["active_pixel_count"]
        )
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
