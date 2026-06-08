"""LAK ex-gwf-lak-p01 validation (Merritt & Konikow 2000, test 1).

End-to-end validation of HMP's home-grown DISV LAK build against the upstream
MODFLOW 6 example. Both models share the SAME single surface-lake footprint on the
same five-layer aquifer; the reference builds its LAK CONNECTIONDATA with the
upstream ``get_lak_connections`` (feet/days), the HMP build with the home-grown
DISV builder (meters/seconds). Two levels:

* STRUCTURAL: the generated CONNECTIONDATA reproduces the upstream 25 VERTICAL +
  20 HORIZONTAL connection set (deterministic, but exercised here on the full
  built model);
* NUMERICAL: the final lake stage, the gross lake-aquifer flux and each build's
  budget closure agree within the documented ``tolerances.toml`` envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validation_cases.numerical.steady.lak_merritt_konikow_p01.comparison import (
    load_tolerances,
    run_lake_p01_scenario,
)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
@pytest.mark.allow_subprocess
def test_lak_p01_matches_reference_within_tolerances(tmp_path: Path) -> None:
    scenario = run_lake_p01_scenario(workspace=tmp_path)
    tolerances = load_tolerances()
    structural_tol = dict(tolerances["structural"])
    stage_tol = dict(tolerances["stage"])
    exchange_tol = dict(tolerances["exchange"])
    budget_tol = dict(tolerances["budget"])

    # STRUCTURAL: home-grown DISV CONNECTIONDATA reproduces the upstream split.
    assert scenario.structural.n_connections == int(structural_tol["n_connections"])
    assert scenario.structural.n_vertical == int(structural_tol["n_vertical"])
    assert scenario.structural.n_horizontal == int(structural_tol["n_horizontal"])
    # The reference (get_lak_connections) and HMP builds agree on the count.
    assert scenario.hmp.n_connections == scenario.reference.n_connections
    assert scenario.hmp.connection_counts == scenario.reference.connection_counts

    # NUMERICAL: stage, gross exchange and budget closure within tolerance.
    assert scenario.final_stage_abs_error_m <= float(stage_tol["final_stage_abs_error_m"])
    assert scenario.rmse_stage_m <= float(stage_tol["rmse_stage_m"])
    assert scenario.lake_gwf_exchange_rel_err <= float(exchange_tol["lake_gwf_exchange_rel_err"])
    assert scenario.max_budget_percent_discrepancy <= float(
        budget_tol["budget_percent_discrepancy"]
    )

    # Sanity: both lakes equilibrate near the surrounding head, well above the bed
    # (the lake fills rather than drying out), so the stage metric is meaningful.
    assert scenario.hmp_stage_m > scenario.geometry.bed_elevation_m
    assert scenario.reference_stage_m > scenario.geometry.bed_elevation_m
