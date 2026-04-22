"""Extensive non-regression test for multi-case river-network signatures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.cases import run_geographic_cases_from_toml
from tests.regression.golden_utils import REPO_ROOT, resolve_tiered_golden_file
from tests._helpers.whitebox import configure_whitebox_single_thread

GOLDEN_REFERENCE_FILE = resolve_tiered_golden_file(
    test_file=__file__,
    filename="run_geographic_case_river_network_signatures.json",
)

CASE_IDS = ["base", "canut", "nancon", "aber"]
ABS_TOL_THRESHOLD_CELLS = 1e-6
ABS_TOL_LENGTH_M = 1.0
ABS_TOL_AREA_KM2 = 1e-4
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
    dem_path = (REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif").as_posix()
    out_path = (tmp_path / "results").as_posix()

    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
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
                "compute_strahler_order = true",
                "compute_stream_links = true",
                "all_vertices = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _collect_case_signature(project_root: str | Path) -> dict:
    summary_path = (
        Path(project_root)
        / ".solver_scratch/_preprocessing"
        / "geographic"
        / "river_network_summary.json"
    )
    if not summary_path.exists():
        raise AssertionError(f"Missing river network summary: {summary_path}")

    with summary_path.open("r", encoding="utf-8") as stream:
        summary = json.load(stream)

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


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
def test_run_geographic_case_river_network_regression(
    update_goldens,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Validate river-network summary stability on all geographic demo cases."""
    configure_whitebox_single_thread(monkeypatch)
    config_path = _write_tmp_config(tmp_path)
    summaries = run_geographic_cases_from_toml(
        config_path,
        case_ids=CASE_IDS,
        show_plot=False,
        outputs_root=tmp_path / "figures",
    )

    actual = {
        case_id: _collect_case_signature(summaries[case_id]["project_root"]) for case_id in CASE_IDS
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
        assert actual[case_id]["enabled"] is expected[case_id]["enabled"]
        assert actual[case_id]["threshold_mode"] == expected[case_id]["threshold_mode"]
        assert actual[case_id]["stream_pixel_count"] == expected[case_id]["stream_pixel_count"]
        assert actual[case_id]["segment_count"] == expected[case_id]["segment_count"]
        assert actual[case_id]["max_strahler_order"] == expected[case_id]["max_strahler_order"]

        assert actual[case_id]["threshold_value"] == pytest.approx(
            expected[case_id]["threshold_value"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        assert actual[case_id]["threshold_cells"] == pytest.approx(
            expected[case_id]["threshold_cells"],
            abs=ABS_TOL_THRESHOLD_CELLS,
            rel=0.0,
        )
        assert actual[case_id]["network_total_length_m"] == pytest.approx(
            expected[case_id]["network_total_length_m"],
            abs=ABS_TOL_LENGTH_M,
            rel=0.0,
        )
        assert actual[case_id]["catchment_area_km2"] == pytest.approx(
            expected[case_id]["catchment_area_km2"],
            abs=ABS_TOL_AREA_KM2,
            rel=0.0,
        )
        assert actual[case_id]["drainage_density_km_per_km2"] == pytest.approx(
            expected[case_id]["drainage_density_km_per_km2"],
            abs=ABS_TOL_DRAINAGE_DENSITY,
            rel=0.0,
        )
