"""Extensive non-regression test for multi-case geographic outputs."""

import pytest

from hydromodpy.spatial.geographic.cases.reference_catchment_delineation_case.run_case import (
    run_geographic_cases_from_toml,
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
from tests.regression.golden_utils import resolve_tiered_golden_file

METRICS_GOLDEN, RIVER_NETWORK_GOLDEN = (
    resolve_tiered_golden_file(
        test_file=__file__, filename=f"run_geographic_case_{name}_signatures.json"
    )
    for name in ("metrics", "river_network")
)
CASE_IDS = ["base", "canut", "nancon", "aber"]

ABS_TOL_AREA_KM2 = 0.03  # ~5 pixels at 75 m; DEM breach is non-deterministic at catchment edge.
ABS_TOL_LENGTH_M = 1200.0
ZONES = ("catchment", "box_buff")
ELEV_METRIC_KEYS = [f"{s}_elevation_{z}_m" for s in ("mean", "std") for z in ZONES] + [
    f"{s}_elevation_{z}_m"
    for group in (("min", "max"), ("q05", "q50", "q95"))
    for z in ZONES
    for s in group
]
SUM_METRIC_KEYS = [f"sum_elevation_{z}_m" for z in ZONES]
COUNT_METRIC_KEYS = [f"{kind}_pixel_count_{z}" for z in ZONES for kind in ("valid", "nodata")]
METRIC_TOLERANCES = {
    "catchment_area_km2": ABS_TOL_AREA_KM2,
    **dict.fromkeys(ELEV_METRIC_KEYS, 1e-2),
    **dict.fromkeys(SUM_METRIC_KEYS, 7e2),  # ~4 edge pixels x ~160 m elevation, plus rounding.
    **dict.fromkeys(COUNT_METRIC_KEYS, 4),  # breach non-determinism flips a few edge pixels.
}
RIVER_NETWORK_TOLERANCES = {
    "stream_pixel_count": 15,
    "segment_count": 15,
    "max_strahler_order": 1.0,
    "threshold_value": ABS_TOL_AREA_KM2,
    "threshold_cells": 1e-6,
    "network_total_length_m": ABS_TOL_LENGTH_M,
    "catchment_area_km2": ABS_TOL_AREA_KM2,
}


def _metrics(summary: dict) -> dict[str, float | int]:
    return {
        "catchment_area_km2": float(summary["catchment_area_km2"]),
        **{key: float(summary[key]) for key in ELEV_METRIC_KEYS + SUM_METRIC_KEYS},
        **{key: int(summary[key]) for key in COUNT_METRIC_KEYS},
    }


def _river_network(summary: dict) -> dict:
    network = summary.get("river_network_summary")
    assert isinstance(network, dict), (
        f"Missing river network summary payload: {summary.get('hydrographic_network_generated_summary_json')}"
    )
    return river_network_summary_signature(network)


def _river_network_within(expected: dict) -> dict:
    area = max(float(expected["catchment_area_km2"]), 1.0e-9)
    density = ABS_TOL_LENGTH_M / 1000.0 / area + 1e-6
    tolerances = {**RIVER_NETWORK_TOLERANCES, "drainage_density_km_per_km2": density}
    return within(expected, tolerances)


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
def test_run_geographic_case_regression_suite(update_goldens, tmp_path, monkeypatch) -> None:
    """Validate metrics and river-network stability on all geographic demo cases."""
    configure_whitebox_single_thread(monkeypatch)
    # The extensive suite keeps the default minimal stream length.
    network = {k: v for k, v in CASE_RIVER_NETWORK.items() if k != "min_stream_length_m"}
    config_path = outlet_case_toml(
        tmp_path / "run_geographic_regression_config.toml",
        NAIZIN,
        root=tmp_path / "results",
        river_network=network,
    )
    summaries = run_geographic_cases_from_toml(
        config_path,
        case_ids=CASE_IDS,
        show_plot=False,
        outputs_root=tmp_path / "figures",
        write_plot=False,
    )
    metrics = {case_id: _metrics(summaries[case_id]) for case_id in CASE_IDS}
    networks = {case_id: _river_network(summaries[case_id]) for case_id in CASE_IDS}
    metrics_expected = golden_reference(METRICS_GOLDEN, metrics, update_goldens)
    networks_expected = golden_reference(RIVER_NETWORK_GOLDEN, networks, update_goldens)
    if update_goldens:
        return
    assert metrics == {
        case_id: within(values, METRIC_TOLERANCES)
        for case_id, values in metrics_expected.items()
        if not case_id.startswith("_")
    }
    assert networks == {
        case_id: _river_network_within(values)
        for case_id, values in networks_expected.items()
        if not case_id.startswith("_")
    }
