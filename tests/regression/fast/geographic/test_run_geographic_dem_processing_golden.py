"""Golden non-regression test for DEM processing artifacts in geographic case."""

from pathlib import Path

import numpy as np
import pytest
import rasterio

from tests._helpers.geographic_cases import (
    NAIZIN,
    delineate_case_toml,
    golden_reference,
    outlet_case_toml,
    within,
)
from tests._helpers.whitebox import configure_whitebox_single_thread
from tests.regression.golden_utils import resolve_tiered_golden_file

GOLDEN_FILE = resolve_tiered_golden_file(
    test_file=__file__, filename="run_geographic_dem_processing_golden.json"
)
DEM_CORRECTION_TYPES = ["breach", "fill"]
DOMAIN_RASTERS = ("watershed_box_buff_dem", "watershed_dem", "watershed_fill", "watershed_direc")

ABS_TOL_ELEV_M = 3e-2
STATISTICS = {
    "min": np.min,
    "max": np.max,
    "mean": lambda values: np.mean(values, dtype=np.float64),
    "std": lambda values: np.std(values, dtype=np.float64),
    "q05": lambda values: np.quantile(values, 0.05),
    "q50": lambda values: np.quantile(values, 0.50),
    "q95": lambda values: np.quantile(values, 0.95),
    "sum": lambda values: np.sum(values, dtype=np.float64),
}


def _raster_signature(path: str | Path) -> dict:
    with rasterio.open(str(path)) as src:
        arr, nodata = src.read(1), src.nodata
    mask = np.isfinite(arr) if nodata is None else np.isfinite(arr) & (arr != nodata)
    values = arr[mask]
    return {
        "shape": [int(n) for n in arr.shape],
        "dtype": str(arr.dtype),
        "nodata": None if nodata is None else float(nodata),
        "valid_pixel_count": int(values.size),
        "nodata_pixel_count": int(arr.size - values.size),
        **{
            name: float(stat(values)) if values.size else float("nan")
            for name, stat in STATISTICS.items()
        },
    }


def _tolerances(signature: dict) -> dict[str, float]:
    total = 20.0
    if signature["dtype"].startswith("int"):
        # Keep the aggregate D8-pointer sum at least as loose as the accepted
        # mean drift; otherwise large rasters can pass the mean check and fail
        # only because that same small drift is multiplied over every valid cell.
        total = max(512.0, ABS_TOL_ELEV_M * int(signature["valid_pixel_count"]))
    return {**dict.fromkeys(list(STATISTICS)[:-1], ABS_TOL_ELEV_M), "sum": total}


def _dem_processing_signature(root: Path, method: str) -> dict:
    config_path = outlet_case_toml(
        root / f"run_geographic_config_{method}.toml", NAIZIN, root=root, dem_correc_type=method
    )
    geographic = delineate_case_toml(config_path)
    flow = Path(geographic.correcflow_path)
    names = {"dem_correc": f"dem_{method}", "dem_direc": "dem_direc", "dem_acc": "dem_acc"}
    return {
        "dem_correc_type": method,
        "catchment_area_km2": float(geographic.catch_area),
        "flow_products": {key: _raster_signature(flow / f"{n}.tif") for key, n in names.items()},
        "domain_products": {
            key: _raster_signature(getattr(geographic, key)) for key in DOMAIN_RASTERS
        },
    }


@pytest.mark.regression
@pytest.mark.fast
def test_run_geographic_dem_processing_golden(update_goldens, tmp_path, monkeypatch) -> None:
    """The corrected DEM, the D8 pointer and accumulation, and the domain rasters of each branch."""
    configure_whitebox_single_thread(monkeypatch)
    actual = {m: _dem_processing_signature(tmp_path / m, m) for m in DEM_CORRECTION_TYPES}
    expected = golden_reference(GOLDEN_FILE, actual, update_goldens)
    if expected is None:
        return
    assert set(actual) == set(expected)
    for method, signature in actual.items():
        reference = expected[method]
        assert signature["dem_correc_type"] == reference["dem_correc_type"]
        assert signature["catchment_area_km2"] == pytest.approx(
            reference["catchment_area_km2"], abs=1e-4, rel=0.0
        )
        for group in ("flow_products", "domain_products"):
            for name, raster in signature[group].items():
                assert raster == within(reference[group][name], _tolerances(raster)), name
