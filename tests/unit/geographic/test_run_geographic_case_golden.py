"""Golden non-regression test for geographic case metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.geographic.cases.run_geographic_case import run_geographic_cases_from_toml


REPO_ROOT = Path(__file__).resolve().parents[3]
# Keep unit coverage focused on the largest basin only for runtime reasons.
GOLDEN_FILE = (
    Path(__file__).resolve().parent / "golden" / "run_geographic_case_metrics_nancon_golden.json"
)
CASE_IDS = ["nancon"]
ABS_TOL_AREA_KM2 = 1e-4
ABS_TOL_ELEV_M = 1e-2
ABS_TOL_SUM_ELEV_M = 1e-1

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


def _configure_whitebox_single_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reduce run-to-run variance by forcing the workflows backend to one worker."""
    monkeypatch.setenv("RAYON_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("NUMEXPR_NUM_THREADS", "1")

    from hydromodpy.backends import clear_whitebox_backend_cache, get_whitebox_backend

    clear_whitebox_backend_cache()
    tool = get_whitebox_backend()
    env = getattr(tool, "_env", None)
    if env is not None and hasattr(env, "max_procs"):
        env.max_procs = 1


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
def test_run_geographic_case_metrics_golden(update_goldens, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """
    Validate DEM-sensitive geographic metrics on the largest geographic case.

    Kept as one-case unit test to keep execution time bounded.
    Full 4-case non-regression is covered in regression/extensive tests.
    """
    _configure_whitebox_single_thread(monkeypatch)
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
            assert actual[case_id][key] == expected[case_id][key]

