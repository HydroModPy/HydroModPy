"""Extensive non-regression test for multi-case geographic outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.cases import run_geographic_cases_from_toml
from tests._helpers.whitebox import configure_whitebox_single_thread
from tests.regression.golden_utils import REPO_ROOT, resolve_tiered_golden_file

METRICS_GOLDEN_REFERENCE_FILE = resolve_tiered_golden_file(
    test_file=__file__,
    filename="run_geographic_case_metrics_signatures.json",
)
RIVER_NETWORK_GOLDEN_REFERENCE_FILE = resolve_tiered_golden_file(
    test_file=__file__,
    filename="run_geographic_case_river_network_signatures.json",
)

CASE_IDS = ["base", "canut", "nancon", "aber"]

ABS_TOL_AREA_KM2 = 0.03  # ~5 pixels at 75 m; DEM breach is non-deterministic at catchment edge.
ABS_TOL_ELEV_M = 1e-2
ABS_TOL_SUM_ELEV_M = 7e2  # ~4 edge pixels x ~160 m elevation (plus rounding jitter).
ABS_TOL_PIXEL_COUNT = 4  # breach non-determinism flips a few edge pixels.
ABS_TOL_STREAM_PIXEL_COUNT = 15

ABS_TOL_THRESHOLD_CELLS = 1e-6
ABS_TOL_LENGTH_M = 1200.0
ABS_TOL_DRAINAGE_DENSITY = 1e-6

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
    config_path = tmp_path / "run_geographic_regression_config.toml"
    dem_path = (REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif").as_posix()
    out_path = (tmp_path / "results").as_posix()

    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                f'project_root = "{out_path}"',
                f'root = "{out_path}"',
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
                "compute_strahler_order = true",
                "compute_stream_links = true",
                "all_vertices = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _build_metrics_payload(
    summaries: dict[str, dict[str, object]],
) -> dict[str, dict[str, float | int]]:
    return {
        case_id: {
            "catchment_area_km2": float(summaries[case_id]["catchment_area_km2"]),
            **{key: float(summaries[case_id][key]) for key in ELEV_METRIC_KEYS},
            **{key: float(summaries[case_id][key]) for key in SUM_METRIC_KEYS},
            **{key: int(summaries[case_id][key]) for key in COUNT_METRIC_KEYS},
        }
        for case_id in CASE_IDS
    }


def _collect_case_signature(
    case_summary: dict[str, object],
) -> dict[str, bool | str | float | int | None]:
    summary = case_summary.get("river_network_summary")
    if not isinstance(summary, dict):
        summary_path = case_summary.get("river_network_summary_json")
        raise AssertionError(f"Missing river network summary payload: {summary_path}")

    return {
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
    }


def _build_river_network_payload(
    summaries: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {case_id: _collect_case_signature(summaries[case_id]) for case_id in CASE_IDS}


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
def test_run_geographic_case_regression_suite(
    update_goldens,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Validate metrics and river-network stability on all geographic demo cases."""
    configure_whitebox_single_thread(monkeypatch)
    config_path = _write_tmp_config(tmp_path)
    summaries = run_geographic_cases_from_toml(
        config_path,
        case_ids=CASE_IDS,
        show_plot=False,
        outputs_root=tmp_path / "figures",
        write_plot=False,
    )

    metrics_actual = _build_metrics_payload(summaries)
    river_network_actual = _build_river_network_payload(summaries)

    if update_goldens:
        _write_json(METRICS_GOLDEN_REFERENCE_FILE, metrics_actual)
        _write_json(RIVER_NETWORK_GOLDEN_REFERENCE_FILE, river_network_actual)
        return

    if not METRICS_GOLDEN_REFERENCE_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {METRICS_GOLDEN_REFERENCE_FILE}. "
            "Run tests with --update-goldens to generate it."
        )
    if not RIVER_NETWORK_GOLDEN_REFERENCE_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {RIVER_NETWORK_GOLDEN_REFERENCE_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    metrics_expected = _load_json(METRICS_GOLDEN_REFERENCE_FILE)
    metrics_expected = {
        key: value for key, value in metrics_expected.items() if not key.startswith("_")
    }
    assert set(metrics_actual.keys()) == set(metrics_expected.keys())
    for case_id in CASE_IDS:
        assert metrics_actual[case_id]["catchment_area_km2"] == pytest.approx(
            metrics_expected[case_id]["catchment_area_km2"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        for key in ELEV_METRIC_KEYS:
            assert metrics_actual[case_id][key] == pytest.approx(
                metrics_expected[case_id][key],
                abs=ABS_TOL_ELEV_M,
                rel=0.0,
            )
        for key in SUM_METRIC_KEYS:
            assert metrics_actual[case_id][key] == pytest.approx(
                metrics_expected[case_id][key],
                abs=ABS_TOL_SUM_ELEV_M,
                rel=0.0,
            )
        for key in COUNT_METRIC_KEYS:
            assert metrics_actual[case_id][key] == pytest.approx(
                metrics_expected[case_id][key],
                abs=ABS_TOL_PIXEL_COUNT,
            )

    river_network_expected = _load_json(RIVER_NETWORK_GOLDEN_REFERENCE_FILE)
    river_network_expected = {
        key: value for key, value in river_network_expected.items() if not key.startswith("_")
    }
    assert set(river_network_actual.keys()) == set(river_network_expected.keys())
    for case_id in CASE_IDS:
        assert (
            river_network_actual[case_id]["enabled"] is river_network_expected[case_id]["enabled"]
        )
        assert (
            river_network_actual[case_id]["threshold_mode"]
            == river_network_expected[case_id]["threshold_mode"]
        )
        assert river_network_actual[case_id]["stream_pixel_count"] == pytest.approx(
            river_network_expected[case_id]["stream_pixel_count"],
            abs=ABS_TOL_STREAM_PIXEL_COUNT,
        )
        assert river_network_actual[case_id]["segment_count"] == pytest.approx(
            river_network_expected[case_id]["segment_count"],
            abs=ABS_TOL_STREAM_PIXEL_COUNT,
        )
        assert (
            river_network_actual[case_id]["max_strahler_order"]
            == river_network_expected[case_id]["max_strahler_order"]
        )

        assert river_network_actual[case_id]["threshold_value"] == pytest.approx(
            river_network_expected[case_id]["threshold_value"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        assert river_network_actual[case_id]["threshold_cells"] == pytest.approx(
            river_network_expected[case_id]["threshold_cells"],
            abs=ABS_TOL_THRESHOLD_CELLS,
            rel=0.0,
        )
        assert river_network_actual[case_id]["network_total_length_m"] == pytest.approx(
            river_network_expected[case_id]["network_total_length_m"],
            abs=ABS_TOL_LENGTH_M,
            rel=0.0,
        )
        assert river_network_actual[case_id]["catchment_area_km2"] == pytest.approx(
            river_network_expected[case_id]["catchment_area_km2"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        assert river_network_actual[case_id]["drainage_density_km_per_km2"] == pytest.approx(
            river_network_expected[case_id]["drainage_density_km_per_km2"],
            abs=(
                ABS_TOL_LENGTH_M
                / 1000.0
                / max(float(river_network_expected[case_id]["catchment_area_km2"]), 1.0e-9)
                + ABS_TOL_DRAINAGE_DENSITY
            ),
            rel=0.0,
        )
