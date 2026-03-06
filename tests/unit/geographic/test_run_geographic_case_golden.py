"""Golden non-regression test for geographic case metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.geographic.cases.run_geographic_case import run_geographic_cases_from_toml


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "run_geographic_case_metrics_golden.json"
CASE_IDS = ["base", "canut", "nancon", "aber"]
ABS_TOL_AREA_KM2 = 1e-4
ABS_TOL_ELEV_M = 1e-2


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_tmp_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "run_geographic_config.toml"
    dem_path = (REPO_ROOT / "data" / "Brittany" / "dem" / "regional dem.tif").as_posix()
    data_path = (REPO_ROOT / "examples_legacy" / "example12" / "data").as_posix()
    out_path = (tmp_path / "results").as_posix()

    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                'catch_name = "example12_geographic_case_test"',
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
                'dem_correc_type = "breach"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.slow
def test_run_geographic_case_metrics_golden(update_goldens, tmp_path):
    """
    Validate catchment area and mean catchment elevation on 4 geographic cases.

    Cases:
    - base: outlet from TOML
    - canut: polygon shapefile (from_polyg_shp)
    - nancon: outlet coordinates
    - aber: outlet coordinates
    """
    config_path = _write_tmp_config(tmp_path)
    summaries = run_geographic_cases_from_toml(
        config_path,
        case_ids=CASE_IDS,
        show_plot=False,
        outputs_root=tmp_path / "figures",
    )

    actual = {
        case_id: {
            "catchment_area_km2": float(summaries[case_id]["catchment_area_km2"]),
            "mean_elevation_catchment_m": float(summaries[case_id]["mean_elevation_catchment_m"]),
        }
        for case_id in CASE_IDS
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
    for case_id in CASE_IDS:
        assert actual[case_id]["catchment_area_km2"] == pytest.approx(
            expected[case_id]["catchment_area_km2"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        assert actual[case_id]["mean_elevation_catchment_m"] == pytest.approx(
            expected[case_id]["mean_elevation_catchment_m"],
            abs=ABS_TOL_ELEV_M,
            rel=0.0,
        )

