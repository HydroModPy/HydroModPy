"""Golden non-regression test for DEM processing artifacts in geographic case."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from hydromodpy.geographic.cases import run_geographic_case_from_toml
from tests.support.whitebox import configure_whitebox_single_thread


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "run_geographic_dem_processing_golden.json"
DEM_CORRECTION_TYPES = ["breach", "fill"]

ABS_TOL_ELEV_M = 1e-2
ABS_TOL_SUM_M = 0.5
ABS_TOL_SUM_INT = 64.0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_tmp_config(tmp_path: Path, *, dem_correc_type: str) -> Path:
    config_path = tmp_path / f"run_geographic_config_{dem_correc_type}.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    dem_path = (REPO_ROOT / "data" / "Brittany" / "dem" / "regional dem.tif").as_posix()
    data_path = (REPO_ROOT / "examples_legacy" / "example12" / "data").as_posix()
    out_path = (tmp_path / "results").as_posix()

    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                f'catch_name = "example12_geographic_demproc_{dem_correc_type}"',
                f'out_dir_path = "{out_path}"',
                f'data_path = "{data_path}"',
                "",
                "[geographic]",
                'catch_def = "from_outlet_coord"',
                f'dem_init_path = "{dem_path}"',
                "x_outlet = 265611.933",
                "y_outlet = 6784182.776",
                "snap_dist = 50",
                "buff_area = 20.0",
                'crs_project = "EPSG:2154"',
                f'dem_correc_type = "{dem_correc_type}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _raster_signature(path: str | Path) -> dict:
    with rasterio.open(str(path)) as src:
        arr = src.read(1)
        nodata = src.nodata
        mask = np.isfinite(arr)
        if nodata is not None:
            mask &= arr != nodata
        values = arr[mask]

        payload = {
            "shape": [int(src.height), int(src.width)],
            "dtype": str(arr.dtype),
            "nodata": None if nodata is None else float(nodata),
            "valid_pixel_count": int(values.size),
            "nodata_pixel_count": int(arr.size - values.size),
        }
        if values.size == 0:
            payload.update(
                {
                    "min": float("nan"),
                    "max": float("nan"),
                    "mean": float("nan"),
                    "std": float("nan"),
                    "q05": float("nan"),
                    "q50": float("nan"),
                    "q95": float("nan"),
                    "sum": float("nan"),
                }
            )
            return payload

        payload.update(
            {
                "min": float(np.min(values)),
                "max": float(np.max(values)),
                "mean": float(np.mean(values, dtype=np.float64)),
                "std": float(np.std(values, dtype=np.float64)),
                "q05": float(np.quantile(values, 0.05)),
                "q50": float(np.quantile(values, 0.50)),
                "q95": float(np.quantile(values, 0.95)),
                "sum": float(np.sum(values, dtype=np.float64)),
            }
        )
        return payload


def _dem_processing_signature(tmp_path: Path, *, dem_correc_type: str) -> dict:
    config_path = _write_tmp_config(tmp_path, dem_correc_type=dem_correc_type)
    workspace, geographic = run_geographic_case_from_toml(config_path)
    _ = workspace

    correc_name = "dem_fill.tif" if dem_correc_type == "fill" else "dem_breach.tif"
    correc_path = Path(geographic.correcflow_path) / correc_name
    direc_path = Path(geographic.correcflow_path) / "dem_direc.tif"
    acc_path = Path(geographic.correcflow_path) / "dem_acc.tif"

    return {
        "dem_correc_type": dem_correc_type,
        "catchment_area_km2": float(geographic.catch_area),
        "flow_products": {
            "dem_correc": _raster_signature(correc_path),
            "dem_direc": _raster_signature(direc_path),
            "dem_acc": _raster_signature(acc_path),
        },
        "domain_products": {
            "watershed_box_buff_dem": _raster_signature(geographic.watershed_box_buff_dem),
            "watershed_dem": _raster_signature(geographic.watershed_dem),
            "watershed_fill": _raster_signature(geographic.watershed_fill),
            "watershed_direc": _raster_signature(geographic.watershed_direc),
        },
    }


def _assert_raster_sig_close(actual: dict, expected: dict) -> None:
    assert actual["shape"] == expected["shape"]
    assert actual["dtype"] == expected["dtype"]
    assert actual["nodata"] == expected["nodata"]
    assert actual["valid_pixel_count"] == expected["valid_pixel_count"]
    assert actual["nodata_pixel_count"] == expected["nodata_pixel_count"]

    for key in ("min", "max", "mean", "std", "q05", "q50", "q95"):
        assert float(actual[key]) == pytest.approx(float(expected[key]), abs=ABS_TOL_ELEV_M, rel=0.0)
    sum_tol = ABS_TOL_SUM_INT if str(actual["dtype"]).startswith("int") else ABS_TOL_SUM_M
    assert float(actual["sum"]) == pytest.approx(float(expected["sum"]), abs=sum_tol, rel=0.0)


@pytest.mark.slow
def test_run_geographic_dem_processing_golden(
    update_goldens: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Validate DEM intermediate products for both correction branches (fill/breach).

    Covered products:
    - corrected DEM (`dem_fill` / `dem_breach`)
    - D8 direction (`dem_direc`)
    - D8 accumulation (`dem_acc`)
    - key domain rasters derived from these intermediates.
    """
    configure_whitebox_single_thread(monkeypatch)

    actual = {
        dem_correc_type: _dem_processing_signature(
            tmp_path / dem_correc_type,
            dem_correc_type=dem_correc_type,
        )
        for dem_correc_type in DEM_CORRECTION_TYPES
    }

    if update_goldens:
        _write_json(GOLDEN_FILE, actual)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)
    assert set(actual.keys()) == set(expected.keys())
    for dem_correc_type in DEM_CORRECTION_TYPES:
        actual_sig = actual[dem_correc_type]
        expected_sig = expected[dem_correc_type]

        assert actual_sig["dem_correc_type"] == expected_sig["dem_correc_type"]
        assert actual_sig["catchment_area_km2"] == pytest.approx(
            expected_sig["catchment_area_km2"],
            abs=1e-4,
            rel=0.0,
        )

        for raster_key in ("dem_correc", "dem_direc", "dem_acc"):
            _assert_raster_sig_close(
                actual_sig["flow_products"][raster_key],
                expected_sig["flow_products"][raster_key],
            )

        for raster_key in (
            "watershed_box_buff_dem",
            "watershed_dem",
            "watershed_fill",
            "watershed_direc",
        ):
            _assert_raster_sig_close(
                actual_sig["domain_products"][raster_key],
                expected_sig["domain_products"][raster_key],
            )
