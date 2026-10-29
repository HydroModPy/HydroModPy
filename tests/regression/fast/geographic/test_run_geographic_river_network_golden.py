"""Golden non-regression test for river-network geographic artifacts."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio

from hydromodpy.spatial.geographic.cases.reference_catchment_delineation_case.run_case import (
    run_geographic_case_from_toml,
)
from tests._helpers.geographic_cases import (
    CASE_RIVER_NETWORK,
    NAIZIN,
    golden_reference,
    outlet_case_toml,
    river_network_summary_signature,
    within,
)
from tests._helpers.whitebox import configure_whitebox_single_thread
from tests.regression.golden_utils import load_json_payload, resolve_tiered_golden_file

GOLDEN_FILE = resolve_tiered_golden_file(
    test_file=__file__, filename="run_geographic_river_network_golden.json"
)
RASTERS = ("streams", "stream_order_strahler", "stream_link_id")
ABS_TOL_FLOAT = 1e-3
ABS_TOL_LENGTH_M = 1.0
SUMMARY_TOLERANCES = {
    **dict.fromkeys(("threshold_value", "threshold_cells", "catchment_area_km2"), ABS_TOL_FLOAT),
    "network_total_length_m": ABS_TOL_LENGTH_M,
    "drainage_density_km_per_km2": 1e-6,
}


def _raster_signature(path: str | Path) -> dict:
    with rasterio.open(str(path)) as src:
        arr, nodata = np.asarray(src.read(1)), src.nodata
    mask = np.isfinite(arr) if nodata is None else np.isfinite(arr) & (arr != nodata)
    active = arr[(arr > 0) & mask]
    return {
        "shape": [int(n) for n in arr.shape],
        "dtype": str(arr.dtype),
        "nodata": None if nodata is None else float(nodata),
        "valid_pixel_count": int(np.count_nonzero(mask)),
        "nodata_pixel_count": int(arr.size - np.count_nonzero(mask)),
        "active_pixel_count": int(active.size),
        "sum_active": float(np.sum(active, dtype=np.float64)) if active.size else 0.0,
        "max_active": float(np.max(active)) if active.size else None,
    }


def _river_network_signature(root: Path) -> dict:
    config_path = outlet_case_toml(
        root / "run_geographic_river_network_config.toml",
        NAIZIN,
        root=root,
        river_network=CASE_RIVER_NETWORK,
    )
    _workspace, geographic = run_geographic_case_from_toml(config_path)
    summary = Path(geographic.hydrographic_network_generated_summary_json)
    assert summary.exists(), f"Missing river network summary JSON: {summary}"
    network = gpd.read_file(str(geographic.hydrographic_network_generated_shp))
    length = 0.0 if network.empty else float(np.sum(np.asarray(network.length, dtype=float)))
    return {
        "summary": river_network_summary_signature(load_json_payload(summary)),
        **{name: _raster_signature(getattr(geographic, f"river_{name}_tif")) for name in RASTERS},
        "network_vector": {"feature_count": int(len(network)), "total_length_m": length},
    }


@pytest.mark.regression
@pytest.mark.fast
def test_run_geographic_river_network_golden(update_goldens, tmp_path, monkeypatch) -> None:
    """Validate river-network raster/vector signatures against a golden reference."""
    configure_whitebox_single_thread(monkeypatch)
    actual = _river_network_signature(tmp_path)
    expected = golden_reference(GOLDEN_FILE, actual, update_goldens)
    if expected is None:
        return
    assert actual["summary"] == within(expected["summary"], SUMMARY_TOLERANCES)
    for name in RASTERS:
        assert actual[name] == within(expected[name], {"sum_active": ABS_TOL_FLOAT}), name
    tolerance = {"total_length_m": ABS_TOL_LENGTH_M}
    assert actual["network_vector"] == within(expected["network_vector"], tolerance)
