"""Extensive non-regression test for multi-case geographic metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.geographic.cases import run_geographic_cases_from_toml
from tests.regression.golden_utils import REPO_ROOT, resolve_tiered_golden_file
from tests.support.whitebox import configure_whitebox_single_thread

GOLDEN_REFERENCE_FILE = resolve_tiered_golden_file(
    test_file=__file__,
    filename="run_geographic_case_metrics_signatures.json",
)

CASE_IDS = ["base", "canut", "nancon", "aber"]
ABS_TOL_AREA_KM2 = 0.03  # ~5 pixels at 75 m — DEM breach is non-deterministic at catchment edge
ABS_TOL_ELEV_M = 1e-2
ABS_TOL_SUM_ELEV_M = 7e2  # ~4 edge pixels x ~160 m elevation (plus rounding jitter)
ABS_TOL_PIXEL_COUNT = 4  # breach non-determinism flips a few edge pixels

ELEV_METRIC_KEYS = [
    "mean_elevation_catchment_m",
    "mean_elevation_box_buff_m",
    "std_elevation_catchment_m",
    "std_elevation_box_buff_m",
    "min_elevation_catchment_m",
    "max_elevation_catchment_m",
    "min_elevation_box_buff_m",
    "max_elevation_box_buff_m",
    "q05_elevation_catchment_m",
    "q50_elevation_catchment_m",
    "q95_elevation_catchment_m",
    "q05_elevation_box_buff_m",
    "q50_elevation_box_buff_m",
    "q95_elevation_box_buff_m",
]
SUM_METRIC_KEYS = [
    "sum_elevation_catchment_m",
    "sum_elevation_box_buff_m",
]
COUNT_METRIC_KEYS = [
    "valid_pixel_count_catchment",
    "nodata_pixel_count_catchment",
    "valid_pixel_count_box_buff",
    "nodata_pixel_count_box_buff",
]


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
    dem_path = (REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif").as_posix()
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
            ]
        ),
        encoding="utf-8",
    )
    return config_path


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
def test_run_geographic_case_metrics_regression(
    update_goldens,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Validate metrics stability on all geographic demo cases."""
    configure_whitebox_single_thread(monkeypatch)
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
            **{key: float(summaries[case_id][key]) for key in ELEV_METRIC_KEYS},
            **{key: float(summaries[case_id][key]) for key in SUM_METRIC_KEYS},
            **{key: int(summaries[case_id][key]) for key in COUNT_METRIC_KEYS},
        }
        for case_id in CASE_IDS
    }

    if update_goldens:
        _write_json(GOLDEN_REFERENCE_FILE, actual)
        return

    if not GOLDEN_REFERENCE_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_REFERENCE_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_REFERENCE_FILE)
    assert set(actual.keys()) == set(expected.keys())
    for case_id in CASE_IDS:
        assert actual[case_id]["catchment_area_km2"] == pytest.approx(
            expected[case_id]["catchment_area_km2"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        for key in ELEV_METRIC_KEYS:
            assert actual[case_id][key] == pytest.approx(
                expected[case_id][key],
                abs=ABS_TOL_ELEV_M,
                rel=0.0,
            )
        for key in SUM_METRIC_KEYS:
            assert actual[case_id][key] == pytest.approx(
                expected[case_id][key],
                abs=ABS_TOL_SUM_ELEV_M,
                rel=0.0,
            )
        for key in COUNT_METRIC_KEYS:
            assert actual[case_id][key] == pytest.approx(
                expected[case_id][key],
                abs=ABS_TOL_PIXEL_COUNT,
            )
